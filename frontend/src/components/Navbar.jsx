import { SearchIcon } from './Icons'

export default function Navbar({ navigate }) {
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
      <span style={{ fontSize: 11, color: 'var(--text-dim)', letterSpacing: '0.05em' }}>
        v1.0 · possible match only
      </span>
    </nav>
  )
}
