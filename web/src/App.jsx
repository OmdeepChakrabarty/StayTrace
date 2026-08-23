import React, { useState, useEffect } from 'react'
import { checkHealth, trackParcel, listParcels, deleteParcel } from './api'
import { trackContainer, listContainers, getContainer, runHealingDemo } from './api'
import TrackingSearch from './components/TrackingSearch'
import ShipmentHeader from './components/ShipmentHeader'
import RouteProgress from './components/RouteProgress'
import ExtractionHealth from './components/ExtractionHealth'
import ShipmentStats from './components/ShipmentStats'
import Timeline from './components/Timeline'

const CARRIERS = [
  { id: 'auto', name: 'Auto Detect Carrier' },
  { id: 'usps', name: 'USPS' },
  { id: 'fedex', name: 'FedEx' },
  { id: 'ups', name: 'UPS' },
  { id: 'dhl', name: 'DHL' },
  { id: 'amazon', name: 'Amazon Logistics' },
  { id: 'ontrac', name: 'OnTrac' },
  { id: 'other', name: 'Other' },
]

const SHIPPING_LINES = [
  { id: 'auto', name: 'Auto Detect Line' },
  { id: 'msc', name: 'MSC' },
  { id: 'maersk', name: 'Maersk' },
  { id: 'cma_cgm', name: 'CMA CGM' },
  { id: 'cosco', name: 'COSCO' },
  { id: 'hapag_lloyd', name: 'Hapag-Lloyd' },
  { id: 'one', name: 'ONE' },
  { id: 'evergreen', name: 'Evergreen' },
  { id: 'zim', name: 'ZIM' },
]

const OCEAN_STATUS_LABELS = {
  booked: 'Booked',
  gate_in: 'Gate In',
  loaded: 'Loaded on Vessel',
  in_transit: 'In Transit',
  transshipment: 'Transshipment',
  discharged: 'Discharged',
  customs_hold: 'Customs Hold',
  gate_out: 'Gate Out',
  delivered: 'Delivered',
  unknown: 'Unknown',
}

const LINE_MARQUEE = ['MSC', 'MAERSK', 'CMA CGM', 'COSCO', 'ONE', 'HAPAG-LLOYD']

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 17c3-6 6-9 9-9s5 2 5 4-2 3-4 3" />
        <circle cx="19" cy="7" r="1.6" fill="currentColor" stroke="none" />
      </svg>
    </span>
  )
}

function SelfHealingDemo({ onNotify }) {
  const [scenario, setScenario] = useState('redesigned')
  const [demo, setDemo] = useState(null)
  const [loading, setLoading] = useState(false)

  const runDemo = async (scen) => {
    setLoading(true)
    setScenario(scen)
    setDemo(null)
    try {
      const result = await runHealingDemo(scen)
      setDemo(result)
    } catch {
      setDemo(null)
      onNotify && onNotify('Self-healing demo is unavailable right now.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    runDemo('redesigned')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const t = demo?.telemetry

  return (
    <section className="panel demo-panel">
      <div className="panel-head">
        <div>
          <h2 className="panel-title">Self-healing engine</h2>
          <p className="panel-sub">
            Controlled engineering simulation of a carrier page structure change — not live data.
          </p>
        </div>
        <div className="segmented" role="group" aria-label="Demo scenario">
          {[
            ['original', 'Original Page'],
            ['redesigned', 'Simulated Redesign'],
            ['ambiguous', 'Ambiguous Data'],
          ].map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={`segment ${scenario === id ? 'active' : ''}`}
              onClick={() => runDemo(id)}
              disabled={loading}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="demo-flow">
          <div className="skeleton-line w60" />
          <div className="skeleton-line w80" />
          <div className="skeleton-line w40" />
        </div>
      )}

      {!loading && !demo && <p className="empty-state">Simulation unavailable.</p>}

      {!loading && demo && t && (
        <div className="demo-flow">
          <div className="demo-step">
            <span className="demo-step-kicker">Carrier page</span>
            <p className="demo-step-desc">{demo.description}</p>
          </div>
          <div className="demo-step">
            <span className="demo-step-kicker">Original extraction strategy</span>
            <p className={t.original_strategy_status === 'passed' ? 'verdict ok' : 'verdict bad'}>
              {t.original_strategy_status === 'passed' ? '✓ Passed' : '✗ Failed'}
            </p>
          </div>
          {t.original_strategy_status === 'failed' && (
            <div className="demo-step highlight">
              <span className="demo-step-kicker">Self-healing recovery · {t.recovery_strategy}</span>
              <p className={t.extraction_status === 'healed' ? 'verdict ok' : 'verdict bad'}>
                {t.extraction_status === 'healed'
                  ? `⚡ Recovered: ${t.recovered_fields.join(', ')}`
                  : `⚠ ${t.validation_result}`}
              </p>
            </div>
          )}
          <div className="demo-step">
            <span className="demo-step-kicker">Deterministic validation</span>
            <p className={t.validation_result === 'passed' ? 'verdict ok' : 'verdict bad'}>
              {t.validation_result === 'passed' ? '✓ Passed' : '⚠ Rejected'}
              <span className="confidence-chip">{(t.confidence * 100).toFixed(0)}% confidence</span>
            </p>
          </div>
          {demo.extracted_shipment?.container_number && (
            <p className="demo-extract">
              Recovered shipment{' '}
              <strong>{demo.extracted_shipment.container_number}</strong>
              {' · '}
              {(demo.extracted_shipment.shipping_line || '').toUpperCase()}
              {' · '}
              {OCEAN_STATUS_LABELS[demo.extracted_shipment.status] || demo.extracted_shipment.status}
            </p>
          )}
        </div>
      )}
    </section>
  )
}

function ShipmentList({ title, items, renderMeta, onSelect, emptyMessage }) {
  return (
    <section className="panel">
      <h2 className="panel-title">{title}</h2>
      {items.length === 0 ? (
        <p className="empty-state">{emptyMessage}</p>
      ) : (
        <ul className="ship-list">
          {items.map((item) => {
            const key = item.container_number || item.tracking_number
            return (
              <li key={key}>
                <button type="button" className="ship-row" onClick={() => onSelect(key)}>
                  <span className="ship-row-num">{key}</span>
                  <span className="ship-row-line">
                    {(item.shipping_line || item.carrier || '').toUpperCase() || '—'}
                  </span>
                  <span className={`status-pill status-sm status-${item.status || 'unknown'}`}>
                    <span className="status-pill-dot" aria-hidden="true" />
                    {OCEAN_STATUS_LABELS[item.status] || item.status || 'Unknown'}
                  </span>
                  <span className="ship-row-meta">{renderMeta(item)}</span>
                  <svg className="ship-row-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="m9 18 6-6-6-6" />
                  </svg>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

export default function App() {
  // mode: 'ocean' (primary hero) | 'parcel' (secondary)
  const [mode, setMode] = useState('ocean')
  const [health, setHealth] = useState({ status: 'checking', database: 'unknown' })

  // Ocean state
  const [containerNumber, setContainerNumber] = useState('')
  const [selectedLine, setSelectedLine] = useState('auto')
  const [oceanLoading, setOceanLoading] = useState(false)
  const [oceanError, setOceanError] = useState(null)
  const [activeContainer, setActiveContainer] = useState(null)
  const [containersList, setContainersList] = useState([])

  // Parcel state
  const [trackingNumber, setTrackingNumber] = useState('')
  const [selectedCarrier, setSelectedCarrier] = useState('auto')
  const [parcelLoading, setParcelLoading] = useState(false)
  const [parcelError, setParcelError] = useState(null)
  const [activeParcel, setActiveParcel] = useState(null)
  const [parcelsList, setParcelsList] = useState([])
  const [filterStatus, setFilterStatus] = useState('all')

  useEffect(() => {
    checkHealth()
      .then((data) => setHealth(data))
      .catch(() => setHealth({ status: 'offline', database: 'disconnected' }))
    fetchContainers()
    fetchParcels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchContainers = async () => {
    try {
      const data = await listContainers('', '', 50)
      setContainersList(data.containers || [])
    } catch (err) {
      console.error('Failed to load containers:', err)
    }
  }

  const fetchParcels = async () => {
    try {
      const data = await listParcels('', filterStatus === 'all' ? '' : filterStatus)
      setParcelsList((data.parcels || []).filter((p) => p.shipment_type !== 'ocean_container'))
    } catch (err) {
      console.error('Failed to load parcels:', err)
    }
  }

  useEffect(() => {
    if (mode === 'parcel') fetchParcels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterStatus])

  const handleTrackContainer = async (e) => {
    if (e) e.preventDefault()
    if (!containerNumber.trim()) {
      setOceanError('Please enter a container number.')
      return
    }

    setOceanLoading(true)
    setOceanError(null)

    try {
      const result = await trackContainer(containerNumber, selectedLine)
      setActiveContainer(result)
      window.scrollTo({ top: 0 })
      fetchContainers()
    } catch (err) {
      setOceanError(err.message || 'Failed to track container shipment.')
    } finally {
      setOceanLoading(false)
    }
  }

  const handleTrackParcel = async (e) => {
    if (e) e.preventDefault()
    if (!trackingNumber.trim()) {
      setParcelError('Please enter a tracking number.')
      return
    }

    setParcelLoading(true)
    setParcelError(null)

    try {
      const result = await trackParcel(trackingNumber, selectedCarrier)
      setActiveParcel(result)
      fetchParcels()
    } catch (err) {
      setParcelError(err.message || 'Failed to track package. Please check the tracking number.')
    } finally {
      setParcelLoading(false)
    }
  }

  const resetToHome = () => {
    setActiveContainer(null)
    setOceanError(null)
    setContainerNumber('')
    window.scrollTo({ top: 0 })
  }

  const handleDeleteParcel = async (tn, e) => {
    e.stopPropagation()
    if (!window.confirm(`Remove parcel ${tn} from history?`)) return

    try {
      await deleteParcel(tn)
      if (activeParcel && activeParcel.tracking_number === tn) {
        setActiveParcel(null)
      }
      fetchParcels()
    } catch (err) {
      alert(`Error deleting parcel: ${err.message}`)
    }
  }

  const handleSelectParcel = (parcel) => {
    setActiveParcel(parcel)
    setTrackingNumber(parcel.tracking_number)
    setSelectedCarrier(parcel.carrier || 'auto')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleSelectContainer = async (cntr) => {
    try {
      const full = await getContainer(cntr)
      setActiveContainer(full)
      setContainerNumber(full.container_number || cntr)
      window.scrollTo({ top: 0 })
    } catch (err) {
      console.error('Failed to load container:', err)
    }
  }

  const containerId = activeContainer
    ? activeContainer.container_number || activeContainer.tracking_number
    : ''

  return (
    <div className="page">
      <div className="bg-glow bg-glow-a" aria-hidden="true" />
      <div className="bg-glow bg-glow-b" aria-hidden="true" />

      <header className="topbar">
        <button type="button" className="brand" onClick={resetToHome} aria-label="StayTrace home">
          <BrandMark />
          <span className="brand-name">StayTrace</span>
          {!activeContainer && <span className="brand-tag">Shipment intelligence</span>}
        </button>

        <div className="topbar-right">
          {activeContainer && (
            <>
              <code className="tracking-chip">{containerId}</code>
              <button type="button" className="ghost-btn" onClick={resetToHome}>
                New search
              </button>
            </>
          )}
          <span className="health-pill" title={`API ${health.status} · Database ${health.database ?? 'unknown'}`}>
            <span className={`health-dot ${health.status}`} aria-hidden="true" />
            API {health.status}
          </span>
        </div>
      </header>

      <main className="main">
        {/* ================= HOME ================= */}
        {!activeContainer && (
          <div className="home fade-in">
            <section className="hero">
              <p className="hero-eyebrow">Shipment intelligence</p>
              <h1 className="hero-title">
                Track any shipment,
                <br />
                across every carrier.
              </h1>
              <p className="hero-sub">
                Ocean containers and parcels — normalized from raw carrier sources with a
                self-healing extraction engine.
              </p>

              <TrackingSearch
                value={containerNumber}
                onChange={(e) => setContainerNumber(e.target.value)}
                onSubmit={handleTrackContainer}
                loading={oceanLoading}
                placeholder="Enter container / tracking number"
                options={SHIPPING_LINES}
                selectValue={selectedLine}
                onSelectChange={(e) => setSelectedLine(e.target.value)}
                buttonLabel={oceanLoading ? 'Tracking' : 'Track'}
              />

              <p className="carrier-marquee" aria-label="Supported shipping lines">
                {LINE_MARQUEE.join(' · ')}
              </p>

              <div className="hero-secondary">
                Tracking an individual package?
                <button type="button" className="link-btn" onClick={() => setMode(mode === 'parcel' ? 'ocean' : 'parcel')}>
                  {mode === 'parcel' ? 'Hide parcel tracking' : 'Track a parcel'}
                </button>
              </div>

              {mode === 'parcel' && (
                <div className="parcel-panel slide-down">
                  <TrackingSearch
                    value={trackingNumber}
                    onChange={(e) => setTrackingNumber(e.target.value)}
                    onSubmit={handleTrackParcel}
                    loading={parcelLoading}
                    placeholder="Enter tracking number (e.g. 94001…, 1Z999…)"
                    options={CARRIERS}
                    selectValue={selectedCarrier}
                    onSelectChange={(e) => setSelectedCarrier(e.target.value)}
                    buttonLabel={parcelLoading ? 'Tracking' : 'Track'}
                    size="md"
                  />

                  {activeParcel && (
                    <article className="parcel-result rise">
                      <ShipmentHeader
                        number={activeParcel.tracking_number}
                        line={(activeParcel.carrier || 'Carrier unknown').toUpperCase()}
                        status={activeParcel.status}
                      />
                      <ShipmentStats
                        items={[
                          { label: 'Origin / Sender', value: activeParcel.sender_address || 'Not available', muted: !activeParcel.sender_address },
                          { label: 'Destination', value: activeParcel.recipient_address || 'Not available', muted: !activeParcel.recipient_address },
                          { label: 'Estimated delivery', value: activeParcel.estimated_delivery || 'Pending', muted: !activeParcel.estimated_delivery },
                          { label: 'Service', value: activeParcel.service_type || 'Standard' },
                          { label: 'Weight', value: activeParcel.weight ? `${activeParcel.weight} kg` : 'N/A', muted: !activeParcel.weight },
                          { label: 'Last updated', value: activeParcel.updated_at || 'Just now' },
                        ]}
                      />
                      <Timeline events={activeParcel.events} />
                    </article>
                  )}

                  {parcelError && (
                    <div className="alert" role="alert">
                      <span>{parcelError}</span>
                      <button type="button" className="ghost-btn" onClick={() => handleTrackParcel()}>
                        Retry
                      </button>
                    </div>
                  )}

                  {parcelsList.length > 0 && (
                    <div className="parcel-history">
                      <div className="parcel-history-head">
                        <h3 className="mini-title">Recent parcels</h3>
                        <select
                          className="filter-select"
                          value={filterStatus}
                          onChange={(e) => setFilterStatus(e.target.value)}
                          aria-label="Filter parcels by status"
                        >
                          <option value="all">All statuses</option>
                          <option value="in_transit">In transit</option>
                          <option value="out_for_delivery">Out for delivery</option>
                          <option value="delivered">Delivered</option>
                          <option value="pre_transit">Pre-transit</option>
                          <option value="exception">Exception</option>
                        </select>
                      </div>
                      <ul className="ship-list">
                        {parcelsList.map((p) => (
                          <li key={p.tracking_number}>
                            <div
                              className="ship-row"
                              role="button"
                              tabIndex={0}
                              onClick={() => handleSelectParcel(p)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault()
                                  handleSelectParcel(p)
                                }
                              }}
                            >
                              <span className="ship-row-num">{p.tracking_number}</span>
                              <span className="ship-row-line">{(p.carrier || '').toUpperCase()}</span>
                              <span className={`status-pill status-sm status-${p.status || 'unknown'}`}>
                                <span className="status-pill-dot" aria-hidden="true" />
                                {p.status ? p.status.replace('_', ' ') : 'unknown'}
                              </span>
                              <span className="ship-row-meta">{p.updated_at}</span>
                              <svg className="ship-row-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                <path d="m9 18 6-6-6-6" />
                              </svg>
                            </div>
                            <button
                              type="button"
                              className="danger-btn"
                              aria-label={`Remove parcel ${p.tracking_number}`}
                              onClick={(e) => handleDeleteParcel(p.tracking_number, e)}
                            >
                              Remove
                            </button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </section>

            {oceanLoading && (
              <section className="loading-strip" role="status" aria-live="polite">
                <span className="spinner spinner-dark" />
                Locating shipment and extracting checkpoints…
              </section>
            )}

            {oceanError && (
              <div className="alert" role="alert">
                <span>{oceanError}</span>
                <button type="button" className="ghost-btn" onClick={() => handleTrackContainer()}>
                  Retry
                </button>
              </div>
            )}

            <SelfHealingDemo onNotify={setOceanError} />

            <ShipmentList
              title="Recent ocean shipments"
              items={containersList}
              emptyMessage="No tracked ocean shipments yet. Enter a container number above to begin."
              onSelect={handleSelectContainer}
              renderMeta={(c) =>
                `${c.origin_port || '?'} → ${c.destination_port || '?'}${c.updated_at ? ` · ${c.updated_at}` : ''}`
              }
            />
          </div>
        )}

        {/* ================= RESULT WORKSPACE ================= */}
        {activeContainer && (
          <div className="workspace fade-in">
            <ShipmentHeader
              number={containerId}
              line={(activeContainer.shipping_line || 'Shipping line').toUpperCase()}
              status={activeContainer.status}
              labels={OCEAN_STATUS_LABELS}
            />

            <RouteProgress shipment={activeContainer} />

            <ExtractionHealth shipment={activeContainer} />

            <ShipmentStats
              items={[
                { label: 'Vessel', value: activeContainer.vessel_name || 'Not available', muted: !activeContainer.vessel_name },
                { label: 'Voyage', value: activeContainer.voyage_number || 'Not available', muted: !activeContainer.voyage_number },
                { label: 'Current location', value: activeContainer.current_location || activeContainer.destination_port || 'Pending', muted: !(activeContainer.current_location || activeContainer.destination_port) },
                { label: 'ETA at destination', value: activeContainer.estimated_arrival || 'Pending', muted: !activeContainer.estimated_arrival },
                { label: 'Actual departure', value: activeContainer.actual_departure || 'Not departed', muted: !activeContainer.actual_departure },
                { label: 'Last updated', value: activeContainer.updated_at || 'Just now' },
              ]}
            />

            <section className="panel timeline-panel">
              <div className="panel-head">
                <h2 className="panel-title">Tracking history</h2>
                <span className="count-chip">{activeContainer.events?.length || 0} checkpoints</span>
              </div>
              <Timeline events={activeContainer.events} />
            </section>

            {containersList.length > 0 && (
              <ShipmentList
                title="Other tracked shipments"
                items={containersList.filter(
                  (c) => (c.container_number || c.tracking_number) !== containerId
                )}
                emptyMessage=""
                onSelect={handleSelectContainer}
                renderMeta={(c) => `${c.origin_port || '?'} → ${c.destination_port || '?'}`}
              />
            )}
          </div>
        )}
      </main>

      <footer className="footer">
        StayTrace — self-healing shipment intelligence
      </footer>
    </div>
  )
}
