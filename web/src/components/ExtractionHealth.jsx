import React, { useState } from 'react'

const STATE_META = {
  healed: {
    icon: '⚡',
    label: 'Self-Healed',
    tone: 'healed',
    hint: 'Extraction self-recovered after a source structure change',
  },
  failed: {
    icon: '⚠',
    label: 'Recovery Failed',
    tone: 'failed',
    hint: 'Recovery could not be safely performed',
  },
  normal: {
    icon: '✓',
    label: 'Normal Extraction',
    tone: 'normal',
    hint: 'Standard extraction succeeded',
  },
}

export default function ExtractionHealth({ shipment }) {
  const [open, setOpen] = useState(false)

  let details = null
  try {
    details = shipment.healing_details ? JSON.parse(shipment.healing_details) : null
  } catch {
    details = null
  }

  const state =
    STATE_META[shipment.healing_status] || STATE_META.normal

  return (
    <div className={`extraction extraction-${state.tone}`}>
      <button
        type="button"
        className="extraction-toggle"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        title={state.hint}
      >
        <span className="extraction-label">Extraction Health</span>
        <span className={`extraction-badge badge-${state.tone}`}>
          <span aria-hidden="true">{state.icon}</span> {state.label}
        </span>
        {details && details.confidence != null && (
          <span className="extraction-confidence">
            {Math.round(details.confidence * 100)}% confidence
          </span>
        )}
        <svg
          className={`chevron ${open ? 'up' : ''}`}
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="extraction-details">
          {details ? (
            <>
              <div className="extraction-row">
                <span>Original extraction</span>
                <strong className={details.original_strategy_status === 'passed' ? 'ok' : 'bad'}>
                  {details.original_strategy_status === 'passed' ? 'Passed' : 'Failed'}
                </strong>
              </div>
              <div className="extraction-row">
                <span>Recovery</span>
                <strong className={details.extraction_status === 'healed' ? 'ok' : details.extraction_status === 'normal' ? '' : 'bad'}>
                  {details.extraction_status === 'normal'
                    ? 'Not required'
                    : details.extraction_status === 'healed'
                      ? 'Successful'
                      : 'Rejected'}
                </strong>
              </div>
              {details.failed_fields?.length > 0 && (
                <div className="extraction-row">
                  <span>Fields needing recovery</span>
                  <strong>{details.failed_fields.join(', ')}</strong>
                </div>
              )}
              {details.recovered_fields?.length > 0 && (
                <div className="extraction-row">
                  <span>Fields recovered</span>
                  <strong className="ok">{details.recovered_fields.join(', ')}</strong>
                </div>
              )}
              <div className="extraction-row">
                <span>Validation</span>
                <strong className={details.validation_result === 'passed' ? 'ok' : 'bad'}>
                  {details.validation_result === 'passed'
                    ? 'Passed'
                    : details.validation_result === 'rejected_ambiguous'
                      ? 'Rejected (ambiguous)'
                      : 'Failed'}
                </strong>
              </div>
              <div className="extraction-row">
                <span>Confidence</span>
                <strong>{(details.confidence * 100).toFixed(0)}%</strong>
              </div>
              {details.recovery_strategy !== 'none' && details.extraction_status === 'healed' && (
                <p className="extraction-note">
                  Website structure change detected. Semantic recovery strategy applied:{' '}
                  <code>{details.recovery_strategy}</code>
                </p>
              )}
            </>
          ) : (
            <p className="extraction-note">
              {shipment.healing_status === 'failed'
                ? 'Recovery was rejected due to ambiguous or conflicting source evidence.'
                : 'No structural anomalies detected during extraction.'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
