import React, { useState, useEffect, useMemo, useRef } from 'react'
import { checkHealth, trackParcel, listParcels, deleteParcel } from './api'
import { trackContainer, listContainers, getContainer, runHealingDemo } from './api'
import AsciiEarth from './components/AsciiEarth'
import AsciiShip from './components/AsciiShip'
import Hotbar from './components/Hotbar'
import SelfHealing from './components/SelfHealing'
import Timeline from './components/Timeline'
import DemoMenu from './components/DemoMenu'

const OCEAN_STATUS_LABELS = {
  booked: 'BOOKED',
  gate_in: 'GATE IN',
  loaded: 'LOADED ON VESSEL',
  in_transit: 'IN TRANSIT',
  transshipment: 'TRANSSHIPMENT',
  discharged: 'DISCHARGED',
  customs_hold: 'CUSTOMS HOLD',
  gate_out: 'GATE OUT',
  delivered: 'DELIVERED',
  unknown: 'UNKNOWN',
}

const CARRIERS = [
  { id: 'auto', name: 'Auto Detect' },
  { id: 'usps', name: 'USPS' },
  { id: 'fedex', name: 'FedEx' },
  { id: 'ups', name: 'UPS' },
  { id: 'dhl', name: 'DHL' },
  { id: 'amazon', name: 'Amazon Logistics' },
  { id: 'ontrac', name: 'OnTrac' },
  { id: 'other', name: 'Other' },
]

const PARCEL_FILTERS = ['all', 'in_transit', 'out_for_delivery', 'delivered', 'pre_transit', 'exception']

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

function usePath() {
  const [path, setPath] = useState(window.location.pathname)
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const navigate = (to) => {
    window.history.pushState({}, '', to)
    setPath(to)
    window.scrollTo(0, 0)
  }
  return [path, navigate]
}

function Brand({ onClick }) {
  return (
    <button type="button" className="brand" onClick={onClick} aria-label="StayTrace home">
      <span className="brand-block" aria-hidden="true">▮</span>
      <span className="brand-text">STAYTRACE</span>
      <span className="brand-cursor" aria-hidden="true">_</span>
    </button>
  )
}

function Header({ onHome, onParcel, showParcelLink = true }) {
  return (
    <header className="topbar">
      <Brand onClick={onHome} />
      {showParcelLink && (
        <button type="button" className="top-link" onClick={onParcel}>
          TRACK PACKAGE →
        </button>
      )}
    </header>
  )
}

/* ================= ENGINE DEMO ================= */

function EngineDemo() {
  const [open, setOpen] = useState(false)
  const [scenario, setScenario] = useState('redesigned')
  const [demo, setDemo] = useState(null)
  const [loading, setLoading] = useState(false)

  const run = async (scen) => {
    setLoading(true)
    setScenario(scen)
    setDemo(null)
    try {
      setDemo(await runHealingDemo(scen))
    } catch {
      setDemo(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open && !demo && !loading) run(scenario)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const t = demo?.telemetry

  return (
    <section className="engine">
      <button type="button" className="link-dim" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? '▾ hide self-healing engine' : '▸ how the self-healing engine works'}
      </button>

      {open && (
        <div className="engine-panel">
          <div className="engine-head">
            <span className="engine-title">SELF-HEALING ENGINE · SIMULATION</span>
            <div className="segmented">
              {[
                ['original', 'ORIGINAL PAGE'],
                ['redesigned', 'REDESIGN'],
                ['ambiguous', 'AMBIGUOUS'],
              ].map(([id, label]) => (
                <button key={id} type="button" className={`segment ${scenario === id ? 'active' : ''}`} onClick={() => run(id)} disabled={loading}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <p className="engine-note">
            Controlled simulation of a carrier page structure change — not live data.
          </p>

          {loading && (
            <p className="engine-status">running extraction…</p>
          )}

          {!loading && !demo && <p className="engine-status">simulation unavailable.</p>}

          {!loading && demo && t && (
            <div className="engine-flow">
              <div className="ef-row">
                <span className="ef-k">CARRIER PAGE</span>
                <span className="ef-v">{demo.description}</span>
              </div>
              <div className="ef-row">
                <span className="ef-k">ORIGINAL STRATEGY</span>
                <span className={`ef-v ${t.original_strategy_status === 'passed' ? 'ok' : 'bad'}`}>
                  {t.original_strategy_status === 'passed' ? '✓ PASSED' : '✗ FAILED'}
                </span>
              </div>
              {t.original_strategy_status === 'failed' && (
                <div className="ef-row highlight">
                  <span className="ef-k">SELF-HEALING · {t.recovery_strategy}</span>
                  <span className={`ef-v ${t.extraction_status === 'healed' ? 'ok' : 'bad'}`}>
                    {t.extraction_status === 'healed'
                      ? `⚡ RECOVERED: ${t.recovered_fields.join(', ')}`
                      : `⚠ ${t.validation_result}`}
                  </span>
                </div>
              )}
              <div className="ef-row">
                <span className="ef-k">VALIDATION</span>
                <span className={`ef-v ${t.validation_result === 'passed' ? 'ok' : 'bad'}`}>
                  {t.validation_result === 'passed' ? '✓ PASSED' : '⚠ REJECTED'}
                  {' · '}
                  {(t.confidence * 100).toFixed(0)}%
                </span>
              </div>
              {demo.extracted_shipment?.container_number && (
                <div className="ef-row">
                  <span className="ef-k">EXTRACTED</span>
                  <span className="ef-v mono">
                    {demo.extracted_shipment.container_number} ·{' '}
                    {(demo.extracted_shipment.shipping_line || '').toUpperCase()} ·{' '}
                    {OCEAN_STATUS_LABELS[demo.extracted_shipment.status] || demo.extracted_shipment.status}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

/* ================= RESULT VIEW ================= */

function Stat({ label, value, mono }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={`stat-value ${mono ? 'mono' : ''} ${value ? '' : 'missing'}`}>{value || '— pending'}</span>
    </div>
  )
}

function ResultView({ shipment, onNewSearch }) {
  const number = shipment.container_number || shipment.tracking_number
  const status = OCEAN_STATUS_LABELS[shipment.status] || (shipment.status || 'UNKNOWN').toUpperCase()

  return (
    <div className="result">
      <div className="result-top reveal" style={{ '--d': '0ms' }}>
        <div className="result-id">
          <span className="result-line">{(shipment.shipping_line || '').toUpperCase()}</span>
          <h1 className="result-number">{number}</h1>
        </div>
        <div className="result-right">
          <SelfHealing shipment={shipment} />
        </div>
      </div>

      <AsciiShip active />

      <div className="route-strip reveal" style={{ '--d': '120ms' }}>
        <div className="route-port">
          <span className="rp-name">{shipment.origin_port || 'ORIGIN'}</span>
          {shipment.origin_port_code && <span className="rp-code">[{shipment.origin_port_code}]</span>}
          <span className="rp-date">
            {shipment.actual_departure
              ? `DEPARTED ${shipment.actual_departure.slice(0, 10)}`
              : shipment.estimated_departure
                ? `ETD ${shipment.estimated_departure.slice(0, 10)}`
                : ''}
          </span>
        </div>

        <div className="route-dash" aria-hidden="true">
          <span className={`route-fill ${shipment.status === 'delivered' ? 'full' : shipment.actual_departure ? 'partial' : ''}`} />
          <span className="route-status">{status}</span>
        </div>

        <div className="route-port right">
          <span className="rp-name">{shipment.destination_port || 'DESTINATION'}</span>
          {shipment.destination_port_code && <span className="rp-code">[{shipment.destination_port_code}]</span>}
          <span className="rp-date">
            {shipment.estimated_arrival ? `ETA ${shipment.estimated_arrival.slice(0, 10)}` : 'ETA PENDING'}
          </span>
        </div>
      </div>

      <div className="stats reveal" style={{ '--d': '220ms' }}>
        <Stat label="VESSEL" value={shipment.vessel_name} />
        <Stat label="VOYAGE" value={shipment.voyage_number} mono />
        <Stat label="CURRENT LOCATION" value={shipment.current_location} />
        <Stat label="ETA" value={shipment.estimated_arrival} mono />
        <Stat label="LAST UPDATED" value={shipment.updated_at} mono />
      </div>

      <section className="panel reveal" style={{ '--d': '300ms' }}>
        <div className="panel-head">
          <span className="panel-title">TRACKING HISTORY</span>
          <span className="panel-count">// {shipment.events?.length || 0} checkpoints</span>
        </div>
        <Timeline events={shipment.events} />
      </section>

      <div className="reveal" style={{ '--d': '380ms' }}>
        <button type="button" className="new-search" onClick={onNewSearch}>
          ← NEW SEARCH
        </button>
      </div>
    </div>
  )
}

/* ================= HOME ================= */

function Home({
  query,
  setQuery,
  onSubmit,
  locating,
  error,
  reduced,
  recent,
  onOpenRecent,
  goParcel,
}) {
  return (
    <div className="home">
      <AsciiEarth dim={locating} />

      <section className={`hero ${locating ? 'away' : ''}`}>
        <p className="eyebrow rise" style={{ '--d': '50ms' }}>
          {'>'} SELF-HEALING SHIPMENT INTELLIGENCE
        </p>
        <h1 className="title rise" style={{ '--d': '150ms' }}>
          STAYTRACE<span className="title-cursor" aria-hidden="true">▮</span>
        </h1>
        <p className="tagline rise" style={{ '--d': '260ms' }}>
          Track ocean freight across changing logistics systems.
        </p>

        <div className="hotbar-slot rise" style={{ '--d': '380ms' }}>
          <Hotbar
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onSubmit={onSubmit}
            loading={false}
            reducedMotion={reduced}
          />
        </div>

        <div className="under-bar rise" style={{ '--d': '500ms' }}>
          <DemoMenu onPick={(id) => onOpenRecent(id, true)} />
          <span className="dot-sep" aria-hidden="true">·</span>
          <button type="button" className="link-dim parcel-jump" onClick={goParcel}>
            track individual packages →
          </button>
        </div>
      </section>

      {error && (
        <div className="alert" role="alert">
          <span>! {error}</span>
        </div>
      )}

      {!locating && recent.length > 0 && (
        <section className="recent rise" style={{ '--d': '600ms' }}>
          <span className="recent-label">RECENT</span>
          <div className="recent-chips">
            {recent.map((c) => (
              <button
                key={c.container_number || c.tracking_number}
                type="button"
                className="recent-chip"
                onClick={() => onOpenRecent(c.container_number || c.tracking_number)}
              >
                <code>{c.container_number || c.tracking_number}</code>
                <span>{(c.shipping_line || '').toUpperCase()}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <EngineDemo />

      <footer className="footer">
        <span className={`health-dot ${health}`} title={`API ${health}`} />
        STAYTRACE · self-healing shipment intelligence
      </footer>
    </div>
  )
}

/* ================= LOCATING OVERLAY ================= */

const SPINNER_FRAMES = ['|', '/', '─', '\\']

function Locating({ number, done }) {
  const [frame, setFrame] = useState(0)
  useEffect(() => {
    if (prefersReducedMotion()) return
    const id = setInterval(() => setFrame((f) => (f + 1) % SPINNER_FRAMES.length), 120)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="locating" aria-live="polite">
      <AsciiShip active />
      <p className="locating-msg">
        <span className="spin-char" aria-hidden={!done}>{done ? '✓' : SPINNER_FRAMES[frame]}</span>{' '}
        {done ? 'SHIPMENT LOCATED' : `LOCATING ${number} …`}
      </p>
    </div>
  )
}

/* ================= PARCEL PAGE ================= */

function ParcelPage({ navigate }) {
  const [trackingNumber, setTrackingNumber] = useState('')
  const [carrier, setCarrier] = useState('auto')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [activeParcel, setActiveParcel] = useState(null)
  const [parcelsList, setParcelsList] = useState([])
  const [filterStatus, setFilterStatus] = useState('all')

  const fetchParcels = async () => {
    try {
      const data = await listParcels('', filterStatus === 'all' ? '' : filterStatus)
      setParcelsList((data.parcels || []).filter((p) => p.shipment_type !== 'ocean_container'))
    } catch (err) {
      console.error('Failed to load parcels:', err)
    }
  }

  useEffect(() => {
    fetchParcels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterStatus])

  const handleTrack = async (e) => {
    if (e) e.preventDefault()
    if (!trackingNumber.trim()) {
      setError('Please enter a tracking number.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const result = await trackParcel(trackingNumber, carrier)
      setActiveParcel(result)
      fetchParcels()
    } catch (err) {
      setError(err.message || 'Failed to track package.')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (tn, e) => {
    e.stopPropagation()
    if (!window.confirm(`Remove parcel ${tn} from history?`)) return
    try {
      await deleteParcel(tn)
      if (activeParcel?.tracking_number === tn) setActiveParcel(null)
      fetchParcels()
    } catch (err) {
      alert(`Error deleting parcel: ${err.message}`)
    }
  }

  const selectParcel = (p) => {
    setActiveParcel(p)
    setTrackingNumber(p.tracking_number)
    setCarrier(p.carrier || 'auto')
    window.scrollTo({ top: 0 })
  }

  return (
    <div className="parcel-page">
      <div className="bg-glow" aria-hidden="true" />
      <Header onHome={() => navigate('/')} showParcelLink={false} />

      <main className="parcel-main">
        <p className="eyebrow rise">{'>'} PARCEL MODE</p>
        <h1 className="page-title rise" style={{ '--d': '100ms' }}>INDIVIDUAL PACKAGES</h1>
        <p className="tagline left rise" style={{ '--d': '200ms' }}>
          USPS · FedEx · UPS · DHL · Amazon · OnTrac — auto-detected by format.
        </p>

        <form className="parcel-form rise" style={{ '--d': '300ms' }} onSubmit={handleTrack} role="search">
          <input
            type="text"
            className="parcel-input"
            placeholder="ENTER TRACKING NUMBER"
            value={trackingNumber}
            onChange={(e) => setTrackingNumber(e.target.value)}
            disabled={loading}
            aria-label="Tracking number"
            autoComplete="off"
            spellCheck="false"
          />
          <select
            className="parcel-select"
            value={carrier}
            onChange={(e) => setCarrier(e.target.value)}
            disabled={loading}
            aria-label="Carrier"
          >
            {CARRIERS.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <button type="submit" className="hotbar-submit" disabled={loading || !trackingNumber.trim()}>
            {loading ? <span className="hotbar-spinner" aria-label="Loading" /> : 'TRACE →'}
          </button>
        </form>

        {error && <div className="alert" role="alert"><span>! {error}</span></div>}

        {activeParcel && (
          <article className="panel rise">
            <div className="panel-head wrap">
              <div>
                <span className="result-line">{(activeParcel.carrier || 'CARRIER UNKNOWN').toUpperCase()}</span>
                <h2 className="parcel-number">{activeParcel.tracking_number}</h2>
              </div>
              <span className={`status-tag status-${activeParcel.status || 'unknown'}`}>
                ● {(activeParcel.status || 'unknown').replace('_', ' ').toUpperCase()}
              </span>
            </div>

            <div className="stats">
              <Stat label="ORIGIN / SENDER" value={activeParcel.sender_address} />
              <Stat label="DESTINATION" value={activeParcel.recipient_address} />
              <Stat label="ESTIMATED DELIVERY" value={activeParcel.estimated_delivery} mono />
              <Stat label="SERVICE" value={activeParcel.service_type} />
              <Stat label="WEIGHT" value={activeParcel.weight ? `${activeParcel.weight} kg` : null} mono />
              <Stat label="LAST UPDATED" value={activeParcel.updated_at} mono />
            </div>

            <Timeline events={activeParcel.events} />
          </article>
        )}

        <section className="panel rise" style={{ '--d': '400ms' }}>
          <div className="panel-head">
            <span className="panel-title">TRACKED PARCELS</span>
            <select
              className="filter-select"
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              aria-label="Filter parcels by status"
            >
              <option value="all">ALL STATUSES</option>
              {PARCEL_FILTERS.filter((f) => f !== 'all').map((f) => (
                <option key={f} value={f}>{f.replace('_', ' ').toUpperCase()}</option>
              ))}
            </select>
          </div>

          {parcelsList.length === 0 ? (
            <p className="empty-state">No tracked parcels yet.</p>
          ) : (
            <ul className="parcel-list">
              {parcelsList.map((p) => (
                <li key={p.tracking_number} className="parcel-row">
                  <button type="button" className="parcel-open" onClick={() => selectParcel(p)}>
                    <code>{p.tracking_number}</code>
                    <span className="pr-carrier">{(p.carrier || '').toUpperCase()}</span>
                    <span className={`status-tag status-sm status-${p.status || 'unknown'}`}>
                      ● {(p.status || 'unknown').replace('_', ' ')}
                    </span>
                    <span className="pr-updated">{p.updated_at}</span>
                  </button>
                  <button type="button" className="danger-btn" aria-label={`Remove ${p.tracking_number}`} onClick={(e) => handleDelete(p.tracking_number, e)}>
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <button type="button" className="new-search" onClick={() => navigate('/')}>
          ← OCEAN FREIGHT
        </button>
      </main>
    </div>
  )
}

/* ================= APP ================= */

export default function App() {
  const [path, navigate] = usePath()
  const [reduced] = useMemo(prefersReducedMotion, [])
  const [health, setHealth] = useState('checking')

  // Ocean state
  const [query, setQuery] = useState('')
  const [phase, setPhase] = useState('idle') // idle | locating | done
  const [locatedNumber, setLocatedNumber] = useState('')
  const [shipment, setShipment] = useState(null)
  const [error, setError] = useState(null)
  const [recent, setRecent] = useState([])
  const liveRef = useRef(null)

  useEffect(() => {
    checkHealth()
      .then(() => setHealth('ok'))
      .catch(() => setHealth('offline'))
    listContainers('', '', 8)
      .then((data) => setRecent(data.containers || []))
      .catch((err) => console.error('Failed to load containers:', err))
  }, [])

  const announce = (msg) => {
    if (liveRef.current) liveRef.current.textContent = msg
  }

  const runTransition = async (num, fetcher) => {
    setError(null)
    setLocatedNumber(num.toUpperCase())
    setPhase('locating')
    announce(`Locating shipment ${num}`)
    const minDelay = reduced ? 150 : 1250
    try {
      const [result] = await Promise.all([fetcher(num), sleep(minDelay)])
      setShipment(result)
      setQuery(num)
      setPhase('done')
      announce(`Shipment ${num} located`)
    } catch (err) {
      setError(err.message || 'Failed to track container shipment.')
      setPhase('idle')
      announce('Tracking failed')
    }
  }

  const handleSubmit = (e) => {
    if (e) e.preventDefault()
    const num = query.trim()
    if (!num) {
      setError('Please enter a container number.')
      return
    }
    runTransition(num, (n) => trackContainer(n))
  }

  const handleOpenRecent = (num, fillOnly = false) => {
    if (fillOnly) {
      setQuery(num)
      document.querySelector('.hotbar-input')?.focus()
      return
    }
    runTransition(num, (n) => getContainer(n))
  }

  const newSearch = () => {
    setShipment(null)
    setPhase('idle')
    setQuery('')
    setError(null)
    window.scrollTo({ top: 0 })
    setTimeout(() => document.querySelector('.hotbar-input')?.focus(), 80)
  }

  if (path === '/parcel') {
    return (
      <>
        <ParcelPage navigate={navigate} />
        <div ref={liveRef} className="sr-only" aria-live="polite" />
      </>
    )
  }

  return (
    <div className="app">
      <div className="bg-glow" aria-hidden="true" />
      <Header onHome={newSearch} onParcel={() => navigate('/parcel')} />

      <main className="main">
        <div ref={liveRef} className="sr-only" aria-live="polite" />

        {phase !== 'done' && (
          <Home
            query={query}
            setQuery={setQuery}
            onSubmit={handleSubmit}
            locating={phase === 'locating'}
            error={error}
            reduced={reduced}
            recent={recent}
            onOpenRecent={handleOpenRecent}
            goParcel={() => navigate('/parcel')}
          />
        )}

        {phase === 'locating' && <Locating number={locatedNumber} done={false} />}

        {phase === 'done' && shipment && (
          <ResultView shipment={shipment} onNewSearch={newSearch} />
        )}
      </main>
    </div>
  )
}
