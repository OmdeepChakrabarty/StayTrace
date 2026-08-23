import React from 'react'

export default function ShipmentStats({ items }) {
  if (!items || items.length === 0) return null
  return (
    <dl className="stats-grid">
      {items.map((item) => (
        <div className="stat-card" key={item.label}>
          <dt className="stat-label">{item.label}</dt>
          <dd className={`stat-value ${item.muted ? 'muted' : ''}`}>{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}
