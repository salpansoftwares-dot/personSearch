import { useState } from 'react'
import Navbar from '../components/Navbar'
import PersonCard from '../components/PersonCard'
import PersonCompareView from '../components/PersonCompareView'
import { SearchIcon, Sliders, AlertTriangle, Users, Columns, Layers } from '../components/Icons'

const API = '/api/v1'

const PURPOSES = [
  'Journalism / research',
  'Professional due diligence',
  'Academic research',
  'Personal background check',
  'Other',
]

export default function SearchPage({ navigate }) {
  const [name, setName]       = useState('')
  const [purpose, setPurpose] = useState('')
  const [hints, setHints]     = useState({ organization: '', sector: '', country: '', role: '' })
  const [showHints, setShowHints] = useState(false)

  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [results, setResults] = useState(null)
  const [meta, setMeta]       = useState(null)
  const [viewMode, setViewMode] = useState('dossier') // 'dossier' | 'compare'

  function updateHint(key, val) {
    setHints(h => ({ ...h, [key]: val }))
  }

  async function handleSearch(e) {
    e.preventDefault()
    if (!name.trim()) return

    setLoading(true)
    setError(null)
    setResults(null)
    setMeta(null)

    try {
      const body = {
        name: name.trim(),
        hints: {
          organization: hints.organization.trim() || undefined,
          sector: hints.sector.trim() || undefined,
          country: hints.country.trim() || undefined,
          role: hints.role.trim() || undefined,
        },
        purpose: purpose.trim() || undefined,
      }

      const res = await fetch(`${API}/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Search failed (HTTP ${res.status})`)
      }

      const data = await res.json()
      setResults(data.results || [])
      setMeta({ queryId: data.query_id, parsedHints: data.parsed_hints })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Navbar navigate={navigate} />

      <main className="page" id="main-content">
        {/* Hero */}
        <div className="hero container">
          <div className="hero-eyebrow">
            <ShieldDot />
            Evidence-first · Sourced · Transparent
          </div>
          <h1 className="hero-title">
            Discover professional<br />
            <span>profiles with evidence</span>
          </h1>
          <p className="hero-sub">
            Every claim is tied to a source, evidence excerpt, and retrieval date.
            Results are always labelled <em>"possible match"</em> — never a definitive identity.
          </p>
        </div>

        {/* Search card */}
        <div className="container">
          <form className="search-card" onSubmit={handleSearch} id="search-form" noValidate>
            <div className="search-row">
              <div className="input-group">
                <label className="input-label" htmlFor="search-name-input">
                  Full name to search
                </label>
                <input
                  id="search-name-input"
                  className="input-field"
                  type="text"
                  placeholder="e.g. John Kamau"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  autoComplete="off"
                  autoFocus
                  required
                  maxLength={256}
                  disabled={loading}
                />
              </div>
              <button
                type="submit"
                className="btn-search"
                disabled={loading || !name.trim()}
                id="search-submit-btn"
                style={{ marginTop: 24 }}
              >
                {loading
                  ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />Searching…</>
                  : <><SearchIcon size={16} />Search</>
                }
              </button>
            </div>

            {/* Purpose */}
            <div className="purpose-row">
              <div className="input-group">
                <label className="input-label" htmlFor="search-purpose-input">
                  Stated purpose <span style={{ color: 'var(--text-dim)', fontWeight: 400 }}>(recommended for accountable use)</span>
                </label>
                <select
                  id="search-purpose-input"
                  className="input-field"
                  value={purpose}
                  onChange={e => setPurpose(e.target.value)}
                  disabled={loading}
                  style={{ background: 'var(--bg-raised)' }}
                >
                  <option value="">Select a purpose…</option>
                  {PURPOSES.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
            </div>

            {/* Hints toggle */}
            <button
              type="button"
              className="hints-toggle"
              onClick={() => setShowHints(h => !h)}
              id="search-hints-toggle"
            >
              <Sliders size={14} />
              {showHints ? 'Hide hints' : 'Add context hints (optional)'}
            </button>

            {showHints && (
              <div className="hints-grid">
                {[
                  { key: 'organization', label: 'Organization', placeholder: 'e.g. Safaricom' },
                  { key: 'sector',       label: 'Sector',       placeholder: 'e.g. technology' },
                  { key: 'country',      label: 'Country code', placeholder: 'e.g. KE' },
                  { key: 'role',         label: 'Role',         placeholder: 'e.g. Software Engineer' },
                ].map(({ key, label, placeholder }) => (
                  <div className="input-group" key={key}>
                    <label className="input-label" htmlFor={`hint-${key}`}>{label}</label>
                    <input
                      id={`hint-${key}`}
                      className="input-field"
                      type="text"
                      placeholder={placeholder}
                      value={hints[key]}
                      onChange={e => updateHint(key, e.target.value)}
                      maxLength={256}
                      disabled={loading}
                    />
                  </div>
                ))}
              </div>
            )}
          </form>
        </div>

        {/* Status */}
        {loading && (
          <div className="status-bar container">
            <div className="spinner" />
            <span>Searching public sources and extracting claims…</span>
          </div>
        )}

        {error && (
          <div className="error-banner container">
            <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
            <div>
              <strong>Search failed</strong>
              <br />
              {error}
            </div>
          </div>
        )}

        {/* Results */}
        {results !== null && !loading && (
          <>
            <div className="results-header container">
              <div>
                <div className="results-title">
                  {results.length === 0
                    ? 'No results found'
                    : `${results.length} possible match${results.length !== 1 ? 'es' : ''}`
                  }
                </div>
                {results.length >= 2 && (
                  <div className="results-disambiguation-hint">
                    Default to unmerged · Kept separate by entity resolution to prevent false attribution
                  </div>
                )}
              </div>

              <div className="results-controls">
                {results.length >= 2 && (
                  <div className="view-mode-toggle" role="group" aria-label="Result View Mode">
                    <button
                      type="button"
                      className={`btn-toggle-view ${viewMode === 'dossier' ? 'active' : ''}`}
                      onClick={() => setViewMode('dossier')}
                      title="Split Profile Dossiers"
                    >
                      <Layers size={14} />
                      <span>Dossier View</span>
                    </button>
                    <button
                      type="button"
                      className={`btn-toggle-view ${viewMode === 'compare' ? 'active' : ''}`}
                      onClick={() => setViewMode('compare')}
                      title="Side-by-side Multi-Profile Comparison"
                    >
                      <Columns size={14} />
                      <span>Compare ({results.length})</span>
                    </button>
                  </div>
                )}

                {meta?.queryId && (
                  <div className="results-meta">
                    Query ID: <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{meta.queryId}</code>
                  </div>
                )}
              </div>
            </div>

            {results.length === 0 ? (
              <div className="empty-state container">
                <div className="empty-icon">
                  <Users size={28} />
                </div>
                <div className="empty-title">No public records found</div>
                <p className="empty-sub">
                  No public professional information was found for this name.
                  Try adding context hints to narrow the search.
                </p>
              </div>
            ) : viewMode === 'compare' && results.length >= 2 ? (
              <div className="container">
                <PersonCompareView persons={results} navigate={navigate} />
              </div>
            ) : (
              <div className="results-list container">
                {results.map(person => (
                  <PersonCard
                    key={person.person_id}
                    person={person}
                    navigate={navigate}
                  />
                ))}
              </div>
            )}
          </>
        )}

        {/* Disclaimer */}
        <div className="disclaimer container">
          <strong>Privacy notice:</strong> This platform reports what public professional sources say about
          named individuals. All outputs are labelled "possible match". Every claim links to its source.
          To request correction or removal, use the dispute form on any profile.
        </div>
      </main>
    </>
  )
}

/* Inline micro-icon */
function ShieldDot() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      <circle cx="12" cy="12" r="2" fill="currentColor"/>
    </svg>
  )
}
