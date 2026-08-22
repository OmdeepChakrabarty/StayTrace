import React, { useState, useEffect } from 'react'
import { checkHealth, trackParcel, listParcels, deleteParcel } from './api'
import { trackContainer, listContainers, getContainer, runHealingDemo } from './api'

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
  { id: 'auto', name: 'Auto Detect Shipping Line' },
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
  in_transit: 'In Transit / Underway',
  transshipment: 'Transshipment',
  discharged: 'Discharged',
  customs_hold: 'Customs Hold',
  gate_out: 'Gate Out for Delivery',
  delivered: 'Delivered',
  unknown: 'Unknown',
}

function HealingBadge({ healingStatus }) {
  if (healingStatus === 'healed') {
    return <span className="heal-badge heal-healed" title="Website structure changed - extraction self-recovered">⚡ Self-Healed</span>
  }
  if (healingStatus === 'failed') {
    return <span className="heal-badge heal-failed" title="Recovery could not be safely performed">⚠ Recovery Failed</span>
  }
  return <span className="heal-badge heal-normal" title="Standard extraction succeeded">✓ Normal Extraction</span>
}

function ScraperHealthPanel({ shipment }) {
  const [open, setOpen] = useState(false)
  let details = null
  try {
    details = shipment.healing_details ? JSON.parse(shipment.healing_details) : null
  } catch {
    details = null
  }

  return (
    <div className="health-panel">
      <button className="health-toggle" onClick={() => setOpen(!open)}>
        <HealingBadge healingStatus={shipment.healing_status} />
        <span className="health-toggle-label">{open ? 'Hide' : 'Scraper Health'} ▾</span>
      </button>
      {open && (
        <div className="health-details">
          {details ? (
            <>
              <div className="health-row">
                <span>Original extraction:</span>
                <strong>{details.original_strategy_status === 'passed' ? 'PASSED' : 'FAILED'}</strong>
              </div>
              <div className="health-row">
                <span>Recovery:</span>
                <strong>
                  {details.extraction_status === 'normal'
                    ? 'NOT REQUIRED'
                    : details.extraction_status === 'healed'
                      ? 'SUCCESS'
                      : 'REJECTED'}
                </strong>
              </div>
              {details.failed_fields?.length > 0 && (
                <div className="health-row">
                  <span>Fields needing recovery:</span>
                  <strong>{details.failed_fields.join(', ')}</strong>
                </div>
              )}
              {details.recovered_fields?.length > 0 && (
                <div className="health-row">
                  <span>Fields recovered:</span>
                  <strong>{details.recovered_fields.join(', ')}</strong>
                </div>
              )}
              <div className="health-row">
                <span>Validation:</span>
                <strong>{details.validation_result === 'passed' ? 'PASSED' : details.validation_result === 'rejected_ambiguous' ? 'REJECTED (AMBIGUOUS)' : 'FAILED'}</strong>
              </div>
              <div className="health-row">
                <span>Confidence:</span>
                <strong>{(details.confidence * 100).toFixed(0)}%</strong>
              </div>
              {details.recovery_strategy !== 'none' && details.extraction_status === 'healed' && (
                <div className="health-note">
                  Website structure change detected. Semantic recovery strategy applied: {details.recovery_strategy}
                </div>
              )}
            </>
          ) : (
            <div className="health-note">
              {shipment.healing_status === 'failed'
                ? 'Recovery was rejected due to ambiguous or conflicting source evidence.'
                : 'No structural anomalies detected during extraction.'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function OceanRoute({ shipment }) {
  return (
    <div className="ocean-route">
      <div className={`route-node ${shipment.actual_departure ? 'done' : ''}`}>
        <div className="route-port">{shipment.origin_port || 'Origin Port'}</div>
        {shipment.origin_port_code && <div className="route-code">{shipment.origin_port_code}</div>}
        <div className="route-mark">{shipment.actual_departure ? '✓' : '○'}</div>
        <div className="route-date">{shipment.estimated_departure ? `ETD ${shipment.estimated_departure.slice(0, 10)}` : ''}</div>
      </div>

      <div className={`route-line ${shipment.actual_departure ? 'active' : ''}`}>
        <div className="route-vessel">{shipment.vessel_name || ''}</div>
        <div className="route-voyage">{shipment.voyage_number ? `Voy ${shipment.voyage_number}` : ''}</div>
      </div>

      {shipment.current_location &&
        shipment.current_location !== shipment.origin_port &&
        shipment.current_location !== shipment.destination_port && (
          <div className="route-node current">
            <div className="route-port">{shipment.current_location}</div>
            <div className="route-mark">◉</div>
            <div className="route-date">Last Known Location</div>
          </div>
        )}

      <div className="route-node destination">
        <div className="route-port">{shipment.destination_port || 'Destination Port'}</div>
        {shipment.destination_port_code && <div className="route-code">{shipment.destination_port_code}</div>}
        <div className="route-mark">{shipment.status === 'delivered' ? '✓' : '●'}</div>
        <div className="route-date">{shipment.estimated_arrival ? `ETA ${shipment.estimated_arrival.slice(0, 10)}` : ''}</div>
      </div>
    </div>
  )
}

function SelfHealingDemo() {
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
    <section className="history-card demo-card">
      <div className="history-header">
        <h2 className="card-title" style={{ margin: 0 }}>Self-Healing Demo</h2>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className={`btn btn-secondary ${scenario === 'original' ? 'active-scenario' : ''}`} onClick={() => runDemo('original')}>Original Page</button>
          <button className={`btn btn-secondary ${scenario === 'redesigned' ? 'active-scenario' : ''}`} onClick={() => runDemo('redesigned')}>Simulated Redesign</button>
          <button className={`btn btn-secondary ${scenario === 'ambiguous' ? 'active-scenario' : ''}`} onClick={() => runDemo('ambiguous')}>Ambiguous Data</button>
        </div>
      </div>
      <p className="demo-disclaimer">
        Controlled engineering simulation of a website structural change — not live carrier data.
      </p>

      {loading && <p className="empty-state">Running extraction simulation...</p>}

      {!loading && demo && t && (
        <div className="demo-results">
          <div className="demo-flow">
            <div className="demo-step">
              <div className="demo-step-title">Carrier page</div>
              <div className="demo-step-desc">{demo.description}</div>
            </div>
            <div className="demo-arrow">↓</div>
            <div className="demo-step">
              <div className="demo-step-title">Original extraction strategy</div>
              <div className={t.original_strategy_status === 'passed' ? 'ok-text' : 'fail-text'}>
                {t.original_strategy_status === 'passed' ? '✓ PASSED' : '✗ FAILED'}
              </div>
            </div>
            {t.original_strategy_status === 'failed' && (
              <>
                <div className="demo-arrow">↓</div>
                <div className="demo-step">
                  <div className="demo-step-title">Self-Healing Recovery ({t.recovery_strategy})</div>
                  <div className={t.extraction_status === 'healed' ? 'ok-text' : 'fail-text'}>
                    {t.extraction_status === 'healed' ? `⚡ RECOVERED: ${t.recovered_fields.join(', ')}` : `⚠ ${t.validation_result}`}
                  </div>
                </div>
              </>
            )}
            <div className="demo-arrow">↓</div>
            <div className="demo-step">
              <div className="demo-step-title">Deterministic Validation</div>
              <div className={t.validation_result === 'passed' ? 'ok-text' : 'fail-text'}>
                {t.validation_result === 'passed' ? '✓ PASSED' : '⚠ REJECTED'}
              </div>
              <div className="demo-step-desc">Confidence: {(t.confidence * 100).toFixed(0)}%</div>
            </div>
          </div>
          {demo.extracted_shipment?.container_number && (
            <div className="demo-extract">
              Recovered shipment: <strong>{demo.extracted_shipment.container_number}</strong>
              {' · '}{demo.extracted_shipment.shipping_line}
              {' · '}{OCEAN_STATUS_LABELS[demo.extracted_shipment.status] || demo.extracted_shipment.status}
            </div>
          )}
        </div>
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
    fetchParcels()
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

  const handleSelectContainer = async (cntr, e) => {
    if (e) e.stopPropagation()
    try {
      const full = await getContainer(cntr)
      setActiveContainer(full)
      setContainerNumber(full.container_number || cntr)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      console.error('Failed to load container:', err)
    }
  }

  return (
    <div className="container">
      {/* Header */}
      <header className="app-header">
        <div className="brand">
          <div className="brand-icon">📦</div>
          <div>
            <h1 className="brand-title">StayTrace</h1>
            <div className="brand-subtitle">Self-Healing Shipment Intelligence</div>
          </div>
        </div>

        <div className="system-status">
          <span className={`status-dot ${health.status}`}></span>
          <span>API: {health.status}</span>
        </div>
      </header>

      {/* ============ PRIMARY HERO: OCEAN SHIPMENT TRACKING ============ */}
      <section className="hero-section">
        <h2 className="hero-tagline">Track ocean freight across changing logistics systems.</h2>
        <form className="track-form ocean-form" onSubmit={handleTrackContainer}>
          <div className="input-group">
            <input
              type="text"
              className="form-control form-control-lg"
              placeholder="Container Number (e.g. MSCU1234566)"
              value={containerNumber}
              onChange={(e) => setContainerNumber(e.target.value)}
              disabled={oceanLoading}
            />
          </div>

          <select
            className="form-control carrier-select carrier-select-lg"
            value={selectedLine}
            onChange={(e) => setSelectedLine(e.target.value)}
            disabled={oceanLoading}
          >
            {SHIPPING_LINES.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>

          <button type="submit" className="btn btn-primary btn-primary-lg" disabled={oceanLoading}>
            {oceanLoading ? 'Tracking...' : 'Track Shipment'}
          </button>
        </form>

        <div className="hero-secondary">
          Tracking an individual package?
          <button className="btn-link" onClick={() => setMode(mode === 'parcel' ? 'ocean' : 'parcel')}>
            {mode === 'parcel' ? 'Hide Parcel Tracking ▴' : 'Track Parcel ▾'}
          </button>
        </div>
      </section>

      {/* ============ SECONDARY: PARCEL TRACKING (collapsible) ============ */}
      {mode === 'parcel' && (
        <section className="track-card parcel-secondary">
          <h3 className="card-title-sm">Individual Package Tracking</h3>
          <form className="track-form" onSubmit={handleTrackParcel}>
            <div className="input-group">
              <input
                type="text"
                className="form-control"
                placeholder="Enter tracking number (e.g. 9400100000000000000000, 1Z999...)"
                value={trackingNumber}
                onChange={(e) => setTrackingNumber(e.target.value)}
                disabled={parcelLoading}
              />
            </div>

            <select
              className="form-control carrier-select"
              value={selectedCarrier}
              onChange={(e) => setSelectedCarrier(e.target.value)}
              disabled={parcelLoading}
            >
              {CARRIERS.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>

            <button type="submit" className="btn btn-primary" disabled={parcelLoading}>
              {parcelLoading ? 'Tracking...' : 'Track Package'}
            </button>
          </form>
        </section>
      )}

      {/* Ocean error */}
      {oceanError && (
        <div className="alert">
          <div className="alert-message">
            <strong>Error: </strong> {oceanError}
          </div>
          <button className="btn btn-secondary" onClick={() => handleTrackContainer()}>
            Retry
          </button>
        </div>
      )}

      {/* ============ OCEAN SHIPMENT RESULT ============ */}
      {activeContainer && (
        <section className="results-card ocean-results">
          <ScraperHealthPanel shipment={activeContainer} />

          <div className="parcel-header">
            <div className="tracking-info">
              <div className="carrier-tag">{(activeContainer.shipping_line || 'Shipping Line').toUpperCase()}</div>
              <div className="tracking-num">{activeContainer.container_number || activeContainer.tracking_number}</div>
            </div>
            <div className={`status-badge ${activeContainer.status}`}>
              {OCEAN_STATUS_LABELS[activeContainer.status] || activeContainer.status || 'Unknown'}
            </div>
          </div>

          {/* Route visualization */}
          <OceanRoute shipment={activeContainer} />

          {/* Details Grid */}
          <div className="details-grid">
            <div className="detail-item">
              <span className="detail-label">Vessel</span>
              <span className="detail-value">{activeContainer.vessel_name || 'Not specified'}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">Voyage</span>
              <span className="detail-value">{activeContainer.voyage_number || 'Not specified'}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">Last Known Location</span>
              <span className="detail-value">{activeContainer.current_location || activeContainer.destination_port || 'Not specified'}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">ETA at Destination</span>
              <span className="detail-value">{activeContainer.estimated_arrival || 'Pending'}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">Actual Departure</span>
              <span className="detail-value">{activeContainer.actual_departure || 'Not departed'}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">Last Updated</span>
              <span className="detail-value">{activeContainer.updated_at || 'Just now'}</span>
            </div>
          </div>

          {/* Event Timeline */}
          <h3 className="timeline-title">Shipment Timeline ({activeContainer.events?.length || 0} Checkpoints)</h3>
          {activeContainer.events && activeContainer.events.length > 0 ? (
            <div className="timeline">
              {activeContainer.events.map((ev, idx) => (
                <div key={idx} className="timeline-item">
                  <div className="timeline-dot"></div>
                  <div className="timeline-time">{ev.timestamp}</div>
                  <div className="timeline-desc">{ev.description || ev.status}</div>
                  {(ev.vessel || ev.voyage) && (
                    <div className="timeline-loc">🚢 {ev.vessel || ''}{ev.voyage ? ` · Voy ${ev.voyage}` : ''}</div>
                  )}
                  {ev.location && !ev.vessel && <div className="timeline-loc">📍 {ev.location}{ev.location_code ? ` (${ev.location_code})` : ''}</div>}
                  {ev.location && ev.vessel && <div className="timeline-loc">📍 {ev.location}{ev.location_code ? ` (${ev.location_code})` : ''}</div>}
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-state">No checkpoint events recorded yet for this shipment.</p>
          )}
        </section>
      )}

      {/* ============ SELF-HEALING DEMO ============ */}
      <SelfHealingDemo />

      {/* ============ CONTAINER HISTORY ============ */}
      <section className="history-card">
        <div className="history-header">
          <h2 className="card-title" style={{ margin: 0 }}>Recent Ocean Shipments</h2>
          <button className="btn btn-secondary" onClick={fetchContainers} style={{ padding: '0.4rem 0.8rem' }}>
            ↻
          </button>
        </div>

        {containersList.length > 0 ? (
          <table className="parcels-table">
            <thead>
              <tr>
                <th>Container</th>
                <th>Line</th>
                <th>Status</th>
                <th>Route</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {containersList.map((c) => (
                <tr
                  key={c.container_number || c.tracking_number}
                  className="clickable-row"
                  onClick={() => handleSelectContainer(c.container_number || c.tracking_number)}
                >
                  <td style={{ fontFamily: 'monospace', fontWeight: 600 }}>{c.container_number || c.tracking_number}</td>
                  <td style={{ textTransform: 'uppercase' }}>{c.shipping_line || c.carrier}</td>
                  <td>
                    <span className={`status-badge ${c.status}`}>
                      {OCEAN_STATUS_LABELS[c.status] || c.status}
                    </span>
                  </td>
                  <td style={{ fontSize: '0.85rem' }}>
                    {c.origin_port || '?'} → {c.destination_port || '?'}
                  </td>
                  <td style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>{c.updated_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="empty-state">No tracked ocean shipments yet. Enter a container number above to begin.</p>
        )}
      </section>

      {/* ============ PARCEL HISTORY (existing feature) ============ */}
      {mode === 'parcel' && (
        <section className="history-card">
          <div className="history-header">
            <h2 className="card-title" style={{ margin: 0 }}>Recent Tracked Parcels</h2>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <select
                className="form-control"
                style={{ width: '140px', padding: '0.4rem 0.6rem' }}
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value)}
              >
                <option value="all">All Statuses</option>
                <option value="in_transit">In Transit</option>
                <option value="out_for_delivery">Out for Delivery</option>
                <option value="delivered">Delivered</option>
                <option value="pre_transit">Pre-Transit</option>
                <option value="exception">Exception</option>
              </select>
              <button className="btn btn-secondary" onClick={fetchParcels} style={{ padding: '0.4rem 0.8rem' }}>
                ↻
              </button>
            </div>
          </div>

          {parcelsList.length > 0 ? (
            <table className="parcels-table">
              <thead>
                <tr>
                  <th>Tracking Number</th>
                  <th>Carrier</th>
                  <th>Status</th>
                  <th>Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {parcelsList.map((p) => (
                  <tr
                    key={p.tracking_number}
                    className="clickable-row"
                    onClick={() => handleSelectParcel(p)}
                  >
                    <td style={{ fontFamily: 'monospace', fontWeight: 600 }}>{p.tracking_number}</td>
                    <td style={{ textTransform: 'uppercase' }}>{p.carrier}</td>
                    <td>
                      <span className={`status-badge ${p.status}`}>
                        {p.status ? p.status.replace('_', ' ') : 'unknown'}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>{p.updated_at}</td>
                    <td>
                      <button
                        className="btn btn-danger"
                        onClick={(e) => handleDeleteParcel(p.tracking_number, e)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="empty-state">No tracked parcels in database. Enter a tracking number above to begin.</p>
          )}
        </section>
      )}

      {/* Active Parcel Details (existing experience) */}
      {mode === 'parcel' && activeParcel && (
        <section className="results-card">
          <div className="parcel-header">
            <div className="tracking-info">
              <div className="carrier-tag">{activeParcel.carrier || 'Carrier Unknown'}</div>
              <div className="tracking-num">{activeParcel.tracking_number}</div>
            </div>
            <div className={`status-badge ${activeParcel.status}`}>
              {activeParcel.status ? activeParcel.status.replace('_', ' ') : 'Unknown'}
            </div>
          </div>

          <div className="details-grid">
            <div className="detail-item">
              <span className="detail-label">Origin / Sender</span>
              <span className="detail-value">{activeParcel.sender_address || 'Not specified'}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">Destination</span>
              <span className="detail-value">{activeParcel.recipient_address || 'Not specified'}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">Estimated Delivery</span>
              <span className="detail-value">{activeParcel.estimated_delivery || 'Pending'}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">Service</span>
              <span className="detail-value">{activeParcel.service_type || 'Standard'}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">Weight</span>
              <span className="detail-value">{activeParcel.weight ? `${activeParcel.weight} kg` : 'N/A'}</span>
            </div>
            <div className="detail-item">
              <span className="detail-label">Last Updated</span>
              <span className="detail-value">{activeParcel.updated_at || 'Just now'}</span>
            </div>
          </div>

          <h3 className="timeline-title">Tracking History ({activeParcel.events?.length || 0} Checkpoints)</h3>
          {activeParcel.events && activeParcel.events.length > 0 ? (
            <div className="timeline">
              {activeParcel.events.map((ev, idx) => (
                <div key={idx} className="timeline-item">
                  <div className="timeline-dot"></div>
                  <div className="timeline-time">{ev.timestamp}</div>
                  <div className="timeline-desc">{ev.description || ev.status}</div>
                  {ev.location && <div className="timeline-loc">📍 {ev.location}</div>}
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-state">No checkpoint events recorded yet for this shipment.</p>
          )}
        </section>
      )}

      {/* Parcel error */}
      {mode === 'parcel' && parcelError && (
        <div className="alert">
          <div className="alert-message">
            <strong>Error: </strong> {parcelError}
          </div>
          <button className="btn btn-secondary" onClick={() => handleTrackParcel()}>
            Retry
          </button>
        </div>
      )}
    </div>
  )
}
