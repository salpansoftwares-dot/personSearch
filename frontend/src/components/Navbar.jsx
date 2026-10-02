import { SearchIcon, Bookmark } from './Icons'

export default function Navbar({ navigate, onOpenSavedSearches }) {
  return (
    <nav className="navbar">
      <button
        id="navbar-logo-btn"
        className="navbar-logo"
        style={{ background: 'none', border: 'none', cursor: 'pointer' }}
        onClick={() => navigate('/')}
        aria-label="Go to home"
      >
        <SearchIcon size={20} />
        PersonSearch
      </button>
      <span className="navbar-tagline">Evidence-first profile discovery</span>
      <div className="navbar-spacer" />
      {onOpenSavedSearches && (
        <button
          type="button"
          id="navbar-saved-searches-btn"
          className="btn-secondary"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '5px 12px',
            fontSize: 12,
            marginRight: 12,
          }}
          onClick={onOpenSavedSearches}
        >
          <Bookmark size={14} />
          <span>Saved Searches</span>
        </button>
      )}
      <span style={{ fontSize: 11, color: 'var(--text-dim)', letterSpacing: '0.05em' }}>
        v2.0 · possible match only
      </span>
    </nav>
  )
}

