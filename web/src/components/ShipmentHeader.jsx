import React from 'react'

export function StatusPill({ status, labels }) {
  const label = (labels && labels[status]) || status || 'Unknown'
  return (
    <span className={`status-pill status-${status || 'unknown'}`}>
      <span className="status-pill-dot" aria-hidden="true" />
      {label}
    </span>
  )
}

export default function ShipmentHeader({ number, line, status, labels }) {
  return (
    <header className="shipment-header">
      <div className="shipment-id">
        {line && <span className="carrier-badge">{line}</span>}
        <h1 className="shipment-number">{number}</h1>
      </div>
      <StatusPill status={status} labels={labels} />
    </header>
  )
}
