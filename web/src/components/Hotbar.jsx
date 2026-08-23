import React, { useEffect, useRef, useState } from 'react'

const PHRASES = ['ENTER CONTAINER NUMBER', 'E.G. MSCU1234566', 'TRACK OCEAN FREIGHT']

function useTypedPlaceholder({ enabled, paused }) {
  const [text, setText] = useState(enabled ? '' : PHRASES[0])

  useEffect(() => {
    if (!enabled || paused) {
      setText(PHRASES[0])
      return
    }

    let phrase = 0
    let i = 0
    let dir = 1
    let timer

    const tick = () => {
      const target = PHRASES[phrase]
      i += dir
      setText(target.slice(0, i))
      let delay = 55
      if (dir === 1 && i === target.length) {
        delay = 2100
        dir = -1
      } else if (dir === -1 && i === 0) {
        dir = 1
        phrase = (phrase + 1) % PHRASES.length
        delay = 400
      }
      timer = setTimeout(tick, dir === -1 ? 26 : delay)
    }

    timer = setTimeout(tick, 900)
    return () => clearTimeout(timer)
  }, [enabled, paused])

  return text
}

export default function Hotbar({ value, onChange, onSubmit, loading, reducedMotion }) {
  const [engaged, setEngaged] = useState(false)
  const inputRef = useRef(null)
  const placeholder = useTypedPlaceholder({
    enabled: !reducedMotion,
    paused: engaged || value.length > 0,
  })

  useEffect(() => {
    if (!reducedMotion && window.matchMedia('(pointer: fine)').matches) {
      const id = setTimeout(() => inputRef.current?.focus({ preventScroll: true }), 750)
      return () => clearTimeout(id)
    }
  }, [reducedMotion])

  return (
    <form className={`hotbar ${loading ? 'loading' : ''}`} onSubmit={onSubmit} role="search">
      <span className={`hotbar-caret ${engaged || value ? 'hidden' : ''}`} aria-hidden="true" />
      <input
        ref={inputRef}
        type="text"
        className="hotbar-input"
        placeholder={placeholder}
        value={value}
        onChange={(e) => {
          setEngaged(true)
          onChange(e)
        }}
        onFocus={() => setEngaged(true)}
        disabled={loading}
        aria-label="Container number"
        autoComplete="off"
        autoCapitalize="characters"
        spellCheck="false"
      />
      <button type="submit" className="hotbar-submit" disabled={loading || !value.trim()}>
        {loading ? <span className="hotbar-spinner" aria-label="Loading" /> : 'TRACE →'}
      </button>
    </form>
  )
}
