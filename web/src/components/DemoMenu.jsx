import React, { useState } from 'react'

const EXAMPLES = [
  { id: 'MSCU1234566', line: 'MSC' },
  { id: 'MAEU6284920', line: 'MAERSK' },
  { id: 'CMAU0600020', line: 'CMA CGM' },
]

export default function DemoMenu({ onPick }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="demo-menu">
      <button type="button" className="link-dim" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? '▾ hide examples' : '▸ try example shipments'}
      </button>

      {open && (
        <div className="demo-pop">
          <p className="demo-note">
            <span className="chip-demo">TEST</span>
            Example container numbers supported by StayTrace's carrier adapters. Tracking
            queries the real carrier sources — this is not simulated shipment data.
          </p>
          <div className="demo-list">
            {EXAMPLES.map((ex) => (
              <button key={ex.id} type="button" className="demo-item" onClick={() => onPick(ex.id)}>
                <code>{ex.id}</code>
                <span>{ex.line}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
