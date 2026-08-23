import React, { useState } from 'react'

const META = {
  healed: { icon: '⚡', label: 'SELF-HEALED', tone: 'healed' },
  failed: { icon: '⚠', label: 'RECOVERY FAILED', tone: 'failed' },
}

export default function SelfHealing({ shipment }) {
  const [open, setOpen] = useState(false)

  let details = null
  try {
    details = shipment.healing_details ? JSON.parse(shipment.healing_details) : null
  } catch {
    details = null
  }

  const meta = META[shipment.healing_status] || { icon: '✓', label: 'NORMAL EXTRACTION', tone: 'normal' }
  const confidence =
    details && details.confidence != null ? Math.round(details.confidence * 100) : null

  return (
    <div className={`heal heal-${meta.tone}`}>
      <button type="button" className="heal-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="heal-icon" aria-hidden="true">{meta.icon}</span>
        <span className="heal-label">{meta.label}</span>
        {confidence != null && <span className="heal-conf">CONF {confidence}%</span>}
        <svg
          className={`chevron ${open ? 'up' : ''}`}
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="heal-flow">
          <div className="heal-step">
            <span className="heal-kicker">Original extraction</span>
            <span className={`heal-verdict ${details && details.original_strategy_status === 'passed' ? 'ok' : 'bad'}`}>
              {details ? (details.original_strategy_status === 'passed' ? 'PASSED' : 'FAILED') : '—'}
            </span>
          </div>
          <span className="heal-arrow" aria-hidden="true">↓</span>
          <div className="heal-step">
            <span className="heal-kicker">Recovery</span>
            <span className={`heal-verdict ${
              !details
                ? ''
                : details.extraction_status === 'healed'
                  ? 'ok'
                  : details.extraction_status === 'normal'
                    ? 'idle'
                    : 'bad'
            }`}>
              {!details
                ? '—'
                : details.extraction_status === 'normal'
                  ? 'NOT REQUIRED'
                  : details.extraction_status === 'healed'
                    ? `SUCCESSFUL · ${details.recovery_strategy || ''}`
                    : 'REJECTED'}
            </span>
          </div>
          <span className="heal-arrow" aria-hidden="true">↓</span>
          <div className="heal-step">
            <span className="heal-kicker">Validation</span>
            <span className={`heal-verdict ${details && details.validation_result === 'passed' ? 'ok' : 'bad'}`}>
              {details
                ? details.validation_result === 'passed'
                  ? 'PASSED'
                  : details.validation_result === 'rejected_ambiguous'
                    ? 'REJECTED · AMBIGUOUS'
                    : 'FAILED'
                : '—'}
            </span>
          </div>
          <span className="heal-arrow" aria-hidden="true">↓</span>
          <div className="heal-step final">
            <span className="heal-kicker">Outcome</span>
            <span className={`heal-verdict ${meta.tone === 'failed' ? 'bad' : 'ok'}`}>
              {meta.tone === 'failed' ? 'NOT ACCEPTED' : 'ACCEPTED'}
              {confidence != null && <em className="heal-conf-em"> · CONFIDENCE {(confidence / 100).toFixed(2)}</em>}
            </span>
          </div>

          {details && details.recovered_fields?.length > 0 && (
            <p className="heal-note">Recovered fields: {details.recovered_fields.join(', ')}</p>
          )}
          {details && details.failed_fields?.length > 0 && (
            <p className="heal-note">Fields needing recovery: {details.failed_fields.join(', ')}</p>
          )}
          {!details && (
            <p className="heal-note">
              {meta.tone === 'failed'
                ? 'Recovery was rejected due to ambiguous or conflicting source evidence.'
                : 'No structural anomalies detected during extraction.'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
