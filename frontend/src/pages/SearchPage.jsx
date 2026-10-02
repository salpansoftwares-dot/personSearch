import { useState, useEffect } from 'react'
import Navbar from '../components/Navbar'
import PersonCard from '../components/PersonCard'
import PersonCompareView from '../components/PersonCompareView'
import SavedSearchesModal from '../components/SavedSearchesModal'
import SaveSearchDialog from '../components/SaveSearchDialog'
import { SearchIcon, Sliders, AlertTriangle, Users, Columns, Layers, Bookmark, Check } from '../components/Icons'

const API = '/api/v1'

const SEARCH_STAGES = [
  {
    label: 'Discovery',
    title: 'Querying Registries & Feeds',
    desc: 'Federating PubMed, ORCID, Semantic Scholar & public engines',
  },
  {
    label: 'Collection',
    title: 'Ingesting Sources',
    desc: 'Fetching verified pages, checking robots.txt, and sanitizing',
  },
  {
    label: 'Extraction',
    title: 'Extracting Verified Claims',
    desc: 'Grounding claims with verbatim evidence quotes via AI',
  },
  {
    label: 'Resolution',
    title: 'Entity Disambiguation',
    desc: 'Clustering records, detecting conflicts & compiling dossiers',
  },
]

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

  const [isSavedSearchesOpen, setIsSavedSearchesOpen] = useState(false)
  const [isSaveDialogOpen, setIsSaveDialogOpen] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  useEffect(() => {
    let interval = null
    if (loading) {
      setElapsedSeconds(0)
      interval = setInterval(() => {
        setElapsedSeconds(s => s + 1)
      }, 1000)
    } else {
      setElapsedSeconds(0)
    }
    return () => {
      if (interval) clearInterval(interval)
    }
  }, [loading])

  const currentStageIndex = elapsedSeconds < 4 ? 0 : elapsedSeconds < 9 ? 1 : elapsedSeconds < 18 ? 2 : 3
  const progressPercent = Math.min(95, Math.max(12, Math.round((elapsedSeconds / 24) * 90) + 10))

  function updateHint(key, val) {
    setHints(h => ({ ...h, [key]: val }))
  }

  async function triggerSearch(searchName, searchHints, searchPurpose) {
    if (!searchName?.trim()) return

    setLoading(true)
    setError(null)
    setResults(null)
    setMeta(null)

    try {
      const body = {
        name: searchName.trim(),
        hints: {
          organization: searchHints?.organization?.trim() || undefined,
          sector: searchHints?.sector?.trim() || undefined,
          country: searchHints?.country?.trim() || undefined,
          role: searchHints?.role?.trim() || undefined,
        },
        purpose: searchPurpose?.trim() || undefined,
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

  async function handleSearch(e) {
    if (e) e.preventDefault()
    await triggerSearch(name, hints, purpose)
  }

  function handleSelectSavedSearch(item) {
    const q = item.query_json || {}
    const newName = q.name || ''
    const newPurpose = q.purpose || ''
    const newHints = {
      organization: q.hints?.organization || '',
      sector: q.hints?.sector || '',
      country: q.hints?.country || '',
      role: q.hints?.role || '',
    }
    setName(newName)
    setPurpose(newPurpose)
    setHints(newHints)
    if (newHints.organization || newHints.sector || newHints.country || newHints.role) {
      setShowHints(true)
    }
    triggerSearch(newName, newHints, newPurpose)
  }


  return (
    <>
      <Navbar navigate={navigate} onOpenSavedSearches={() => setIsSavedSearchesOpen(true)} />

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
              <div style={{ display: 'flex', gap: 8 }}>
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
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={loading || !name.trim()}
                  onClick={() => setIsSaveDialogOpen(true)}
                  id="search-save-btn"
                  style={{ marginTop: 24, display: 'inline-flex', alignItems: 'center', gap: 6 }}
                  title="Save this search query"
                >
                  <Bookmark size={15} />
                  <span>Save</span>
                </button>
              </div>
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

        {/* Status / Staged Progress */}
        {loading && (
          <div className="search-progress-card container">
            <div className="search-progress-header">
              <div className="search-progress-title-wrap">
                <div className="spinner" style={{ width: 18, height: 18, borderWidth: 2 }} />
                <span className="search-progress-title">
                  Searching public records & extracting claims…
                </span>
              </div>
              <div className="search-progress-timer">
                {elapsedSeconds}s elapsed
              </div>
            </div>

            <div className="search-progress-bar-track" role="progressbar" aria-valuenow={progressPercent} aria-valuemin="0" aria-valuemax="100">
              <div className="search-progress-bar-fill" style={{ width: `${progressPercent}%` }} />
            </div>

            <div className="search-progress-steps">
              {SEARCH_STAGES.map((stage, idx) => {
                const isCompleted = idx < currentStageIndex
                const isActive = idx === currentStageIndex
                const stateClass = isCompleted ? 'completed' : isActive ? 'active' : 'pending'

                return (
                  <div key={stage.label} className={`search-progress-step ${stateClass}`}>
                    <div className="search-step-header">
                      <span>{stage.label}</span>
                      {isCompleted ? (
                        <Check size={12} color="var(--success)" />
                      ) : isActive ? (
                        <span className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5 }} />
                      ) : (
                        <span style={{ opacity: 0.4 }}>•</span>
                      )}
                    </div>
                    <div className="search-step-name">{stage.title}</div>
                    <div className="search-step-desc">{stage.desc}</div>
                  </div>
                )
              })}
            </div>
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

                <button
                  type="button"
                  className="btn-secondary"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '5px 10px' }}
                  onClick={() => setIsSaveDialogOpen(true)}
                  title="Save this search query"
                  id="results-save-query-btn"
                >
                  <Bookmark size={13} />
                  <span>Save Query</span>
                </button>

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

      <SavedSearchesModal
        isOpen={isSavedSearchesOpen}
        onClose={() => setIsSavedSearchesOpen(false)}
        onSelectSearch={handleSelectSavedSearch}
      />
      <SaveSearchDialog
        isOpen={isSaveDialogOpen}
        onClose={() => setIsSaveDialogOpen(false)}
        name={name}
        hints={hints}
        purpose={purpose}
      />
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
