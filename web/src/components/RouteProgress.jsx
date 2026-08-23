import React from 'react'

export default function RouteProgress({ shipment }) {
  if (!shipment) return null

  const departed = Boolean(shipment.actual_departure)
  const delivered = shipment.status === 'delivered'
  const hasCurrent =
    shipment.current_location &&
    shipment.current_location !== shipment.origin_port &&
    shipment.current_location !== shipment.destination_port

  return (
    <div className="route" role="img" aria-label={`Route from ${shipment.origin_port || 'origin'} to ${shipment.destination_port || 'destination'}`}>
      <div className="route-endpoint">
        <span className="route-port">{shipment.origin_port || 'Origin'}</span>
        {shipment.origin_port_code && <span className="route-code">{shipment.origin_port_code}</span>}
        <span className="route-date">
          {shipment.actual_departure
            ? `Departed ${shipment.actual_departure.slice(0, 10)}`
            : shipment.estimated_departure
              ? `ETD ${shipment.estimated_departure.slice(0, 10)}`
              : ''}
        </span>
      </div>

      <div className="route-track">
        <div className="route-rail" aria-hidden="true">
          <div className={`route-progress ${delivered ? 'full' : departed ? 'partial' : ''}`} />
        </div>
        {(shipment.vessel_name || shipment.voyage_number) && (
          <div className="route-vessel-chip">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M2 21c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2c1.3 0 1.9.5 2.5 1" />
              <path d="M19.4 14 22 9l-8-3V2h-4v4L2 9l2.6 5" />
              <path d="M12 6v8" />
            </svg>
            <span>
              {shipment.vessel_name || 'Vessel unknown'}
              {shipment.voyage_number ? ` · Voy ${shipment.voyage_number}` : ''}
            </span>
          </div>
        )}
      </div>

      {hasCurrent && (
        <div className="route-endpoint current">
          <span className="route-port">{shipment.current_location}</span>
          <span className="route-date">Last known position</span>
        </div>
      )}

      <div className="route-endpoint destination">
        <span className="route-port">{shipment.destination_port || 'Destination'}</span>
        {shipment.destination_port_code && <span className="route-code">{shipment.destination_port_code}</span>}
        <span className="route-date">
          {shipment.estimated_arrival ? `ETA ${shipment.estimated_arrival.slice(0, 10)}` : 'ETA pending'}
        </span>
      </div>
    </div>
  )
}
