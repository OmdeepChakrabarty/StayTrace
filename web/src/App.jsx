import React, { useState, useEffect } from 'react'
import { checkHealth, trackParcel, listParcels, deleteParcel } from './api'

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

export default function App() {
  const [health, setHealth] = useState({ status: 'checking', database: 'unknown' })
  const [trackingNumber, setTrackingNumber] = useState('')
  const [selectedCarrier, setSelectedCarrier] = useState('auto')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [activeParcel, setActiveParcel] = useState(null)
  const [parcelsList, setParcelsList] = useState([])
  const [listLoading, setListLoading] = useState(false)
  const [filterStatus, setFilterStatus] = useState('all')

  useEffect(() => {
    // Initial health check
    checkHealth()
      .then((data) => setHealth(data))
      .catch(() => setHealth({ status: 'offline', database: 'disconnected' }))

    fetchParcels()
  }, [])

  const fetchParcels = async () => {
    try {
      setListLoading(true)
      const data = await listParcels('', filterStatus === 'all' ? '' : filterStatus)
      setParcelsList(data.parcels || [])
    } catch (err) {
      console.error('Failed to load parcels:', err)
    } finally {
      setListLoading(false)
    }
  }

  useEffect(() => {
    fetchParcels()
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
      const result = await trackParcel(trackingNumber, selectedCarrier)
      setActiveParcel(result)
      fetchParcels()
    } catch (err) {
      setError(err.message || 'Failed to track package. Please check the tracking number.')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (tn, e) => {
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

  return (
    <div className="container">
      {/* Header */}
      <header className="app-header">
        <div className="brand">
          <div className="brand-icon">📦</div>
          <div>
            <h1 className="brand-title">StayTrace</h1>
          </div>
        </div>

        <div className="system-status">
          <span className={`status-dot ${health.status}`}></span>
          <span>API: {health.status}</span>
        </div>
      </header>

      {/* Main Track Card */}
      <section className="track-card">
        <h2 className="card-title">Track a Shipment</h2>
        <form className="track-form" onSubmit={handleTrack}>
          <div className="input-group">
            <input
              type="text"
              className="form-control"
              placeholder="Enter tracking number (e.g. 9400100000000000000000, 1Z999...)"
              value={trackingNumber}
              onChange={(e) => setTrackingNumber(e.target.value)}
              disabled={loading}
            />
          </div>

          <select
            className="form-control carrier-select"
            value={selectedCarrier}
            onChange={(e) => setSelectedCarrier(e.target.value)}
            disabled={loading}
          >
            {CARRIERS.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>

          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? 'Tracking...' : 'Track Package'}
          </button>
        </form>
      </section>

      {/* Error Alert */}
      {error && (
        <div className="alert">
          <div className="alert-message">
            <strong>Error: </strong> {error}
          </div>
          <button className="btn btn-secondary" onClick={() => handleTrack()}>
            Retry
          </button>
        </div>
      )}

      {/* Active Parcel Details */}
      {activeParcel && (
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

          {/* Details Grid */}
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

          {/* Events Checkpoint Timeline */}
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

      {/* History Table */}
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

        {listLoading ? (
          <p className="empty-state">Loading tracked shipments...</p>
        ) : parcelsList.length > 0 ? (
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
                      onClick={(e) => handleDelete(p.tracking_number, e)}
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
    </div>
  )
}
