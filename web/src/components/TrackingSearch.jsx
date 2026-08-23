import React from 'react'

export default function TrackingSearch({
  value,
  onChange,
  onSubmit,
  loading = false,
  placeholder = 'Enter container number',
  options = [],
  selectValue,
  onSelectChange,
  buttonLabel = 'Track',
  size = 'lg',
}) {
  return (
    <form className={`search-shell search-shell-${size}`} onSubmit={onSubmit} role="search">
      <div className="search-field">
        <svg
          className="search-icon"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <input
          type="text"
          className="search-input"
          placeholder={placeholder}
          value={value}
          onChange={onChange}
          disabled={loading}
          aria-label={placeholder}
          autoComplete="off"
          spellCheck="false"
        />
      </div>

      {options.length > 0 && (
        <div className="search-divider" aria-hidden="true" />
      )}

      {options.length > 0 && (
        <select
          className="search-select"
          value={selectValue}
          onChange={onSelectChange}
          disabled={loading}
          aria-label="Carrier selection"
        >
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      )}

      <button type="submit" className="search-submit" disabled={loading}>
        {loading ? (
          <span className="spinner" aria-label="Tracking" />
        ) : (
          <>
            {buttonLabel}
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M5 12h14" />
              <path d="m13 6 6 6-6 6" />
            </svg>
          </>
        )}
      </button>
    </form>
  )
}
