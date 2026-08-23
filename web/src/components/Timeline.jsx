import React from 'react'

function formatTimestamp(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return (
    d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) +
    ' · ' +
    d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  )
}

export default function Timeline({ events, emptyMessage = 'No checkpoint events recorded yet.' }) {
  if (!events || events.length === 0) {
    return <p className="empty-state">{emptyMessage}</p>
  }

  return (
    <ol className="timeline">
      {events.map((ev, idx) => (
        <li
          key={idx}
          className="timeline-item"
          style={{ animationDelay: `${Math.min(idx * 70, 560)}ms` }}
        >
          <span className={`timeline-dot ${idx === 0 ? 'latest' : ''}`} aria-hidden="true" />
          <div className="timeline-body">
            <time className="timeline-time">[{formatTimestamp(ev.timestamp)}]</time>
            <p className="timeline-desc">{ev.description || ev.status || 'Checkpoint'}</p>
            {(ev.vessel || ev.voyage) && (
              <span className="timeline-meta">
                &gt; {ev.vessel || ''}
                {ev.voyage ? ` · VOY ${ev.voyage}` : ''}
              </span>
            )}
            {ev.location && (
              <span className="timeline-meta">
                &gt; {ev.location}
                {ev.location_code ? ` (${ev.location_code})` : ''}
              </span>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}
