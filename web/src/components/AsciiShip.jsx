import React from 'react'

const SHIP_ART = `                                       ●
                                       │
                                      ▄▄▄
                                     ▐███▌
                                     ▐███▌
                                     ▐███▌
  ▛▀▀▜  ▛▀▀▜  ▛▀▀▜  ▛▀▀▜  ▛▀▀▜  ▛▀▀▜
  ▌  ▐  ▌  ▐  ▌  ▐  ▌  ▐  ▌  ▐  ▌  ▐
┌─┴─────┴─────┴─────┴─────┴─────┴──────┴─────┐
╞════════════════════════════════════════════╡
 ╲▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄╱`

const WAVES = [
  '~~~~ ~~~~ ~~~~~ ~~~ ~~~~~~ ~~ ~~~~~ ~~~ ~~~~',
  '~~ ~~~~~~ ~~~ ~~~~~ ~~~ ~~ ~~~~~~ ~~~~ ~~~~~',
]

function renderShipLine(line, i) {
  if (i >= 2 && i <= 5) {
    return (
      <span key={i}>
        <span className="ship-gray">{line.slice(0, 37)}</span>
        <span className="ship-orange">{line.slice(37)}</span>
      </span>
    )
  }
  return <span key={i} className="ship-gray">{line}</span>
}

export default function AsciiShip({ active = false }) {
  const lines = SHIP_ART.split('\n')
  return (
    <div className={`ascii-ship-wrap ${active ? 'active' : ''}`} aria-hidden="true">
      <pre className="ascii-ship">
        {lines.map((line, i) => renderShipLine(line, i))}
      </pre>
      <pre className="ascii-waves" key={WAVES[0]}>
        {WAVES.join('\n')}
      </pre>
    </div>
  )
}
