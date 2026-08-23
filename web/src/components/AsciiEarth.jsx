import React, { useEffect, useRef } from 'react'

const COLS = 76
const ROWS = 30

const OCEAN_RAMP = ' .·:~-='
const LAND_RAMP = '::;+*x#@'

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function buildFrame(t) {
  const rows = []
  for (let y = 0; y < ROWS; y++) {
    const ny = (y / (ROWS - 1)) * 2 - 1
    let row = ''
    for (let x = 0; x < COLS; x++) {
      const nx = ((x / (COLS - 1)) * 2 - 1) * 2.05
      const r2 = nx * nx + ny * ny

      if (r2 > 1) {
        const h = ((x * 73 + y * 151) % 211) / 211
        row += h < 0.008 ? '·' : ' '
        continue
      }

      const nz = Math.sqrt(1 - r2)
      const lon = Math.atan2(nx, nz) + t
      const lat = Math.asin(ny)

      // pseudo-noise continents from layered sinusoids
      const n =
        Math.sin(lat * 3.4 + Math.sin(lon * 2.2 + t * 0.15) * 1.4) *
        Math.cos(lon * 2.6 + Math.sin(lat * 5.1 - t * 0.1) * 0.9)

      // lighting from upper-left-front
      const light = Math.max(0, nx * -0.48 + ny * -0.52 + nz * 0.7)

      if (Math.abs(lat) > 1.22 && n < 0.55) {
        row += n > -0.35 ? '*' : '.'
        continue
      }

      if (n > 0.28) {
        const idx = Math.min(LAND_RAMP.length - 1, Math.floor(light * LAND_RAMP.length))
        row += LAND_RAMP[idx]
      } else {
        const idx = Math.min(OCEAN_RAMP.length - 1, Math.floor(light * OCEAN_RAMP.length))
        row += OCEAN_RAMP[idx]
      }
    }
    rows.push(row.replace(/\s+$/, ''))
  }
  return rows.join('\n')
}

export default function AsciiEarth({ dim = false }) {
  const ref = useRef(null)

  useEffect(() => {
    const reduced = prefersReducedMotion()
    if (!ref.current) return

    if (reduced) {
      ref.current.textContent = buildFrame(2.4)
      return
    }

    let t = 2.4
    ref.current.textContent = buildFrame(t)
    const id = setInterval(() => {
      if (document.hidden || !ref.current) return
      t += 0.32
      ref.current.textContent = buildFrame(t)
    }, 140)
    return () => clearInterval(id)
  }, [])

  return (
    <div className={`ascii-earth-wrap ${dim ? 'dim' : ''}`} aria-hidden="true">
      <div className="earth-halo" />
      <pre ref={ref} className="ascii-earth" />
    </div>
  )
}
