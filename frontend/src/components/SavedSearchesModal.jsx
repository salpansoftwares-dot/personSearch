import { useState, useEffect } from 'react'
import { Bookmark, Play, Trash2, AlertTriangle, Users } from './Icons'

const API = '/api/v1'

export default function SavedSearchesModal({ isOpen, onClose, onSelectSearch }) {
  const [savedSearches, setSavedSearches] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [deletingId, setDeletingId] = useState(null)

  useEffect(() => {
    if (isOpen) {
      loadSavedSearches()
    }
  }, [isOpen])

  async function loadSavedSearches() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API}/saved-searches`)
      if (!res.ok) throw new Error('Failed to load saved searches')
      const data = await res.json()
      setSavedSearches(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleDelete(id, e) {
    e.stopPropagation()
    if (!window.confirm('Delete this saved search?')) return
    setDeletingId(id)
    try {
      const res = await fetch(`${API}/saved-searches/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Failed to delete search')
      setSavedSearches(prev => prev.filter(s => s.id !== id))
    } catch (err) {
      alert(err.message)
    } finally {
      setDeletingId(null)
    }
  }

  if (!isOpen) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" style={{ maxWidth: 620 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Bookmark size={18} style={{ color: 'var(--accent)' }} />
            <h2 className="modal-title">Saved Searches</h2>
            <span className="badge" style={{ fontSize: 11, background: 'var(--bg-subtle)' }}>
              {savedSearches.length}
            </span>
          </div>
          <button
            type="button"
            className="btn-secondary"
            style={{ padding: '4px 8px', fontSize: 12 }}
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <p className="modal-sub" style={{ marginBottom: 16 }}>
          Saved queries re-run candidate discovery on fresh sources without caching stale personal data.
        </p>

        {loading ? (
          <div style={{ padding: '32px 0', textAlign: 'center', color: 'var(--text-dim)' }}>
            <div className="spinner" style={{ margin: '0 auto 8px' }} />
            Loading saved searches…
          </div>
        ) : error ? (
          <div className="error-banner" style={{ margin: '12px 0' }}>
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
        ) : savedSearches.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '36px 16px', color: 'var(--text-dim)' }}>
            <Bookmark size={32} style={{ opacity: 0.35, marginBottom: 8 }} />
            <div style={{ fontWeight: 600, color: 'var(--text)' }}>No saved searches yet</div>
            <div style={{ fontSize: 13, marginTop: 4 }}>
              Click <strong>"Save Search"</strong> on any query to quickly re-run it later.
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 420, overflowY: 'auto' }}>
            {savedSearches.map(item => {
              const query = item.query_json || {}
              const hints = query.hints || {}
              const hintList = [
                hints.organization && `Org: ${hints.organization}`,
                hints.role && `Role: ${hints.role}`,
                hints.country && `Country: ${hints.country}`,
                hints.sector && `Sector: ${hints.sector}`,
              ].filter(Boolean)

              return (
                <div
                  key={item.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px 14px',
                    borderRadius: 'var(--radius)',
                    background: 'var(--bg-subtle)',
                    border: '1px solid var(--border)',
                    transition: 'border-color 0.15s ease',
                  }}
                  className="saved-search-item"
                >
                  <div style={{ flex: 1, minWidth: 0, paddingRight: 12 }}>
                    <div style={{ fontWeight: 600, color: 'var(--text)', fontSize: 14 }}>
                      {item.label}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                      <span className="badge" style={{ background: 'var(--accent-glow)', color: 'var(--accent)', fontSize: 11 }}>
                        {query.name}
                      </span>
                      {hintList.map((h, i) => (
                        <span key={i} className="badge" style={{ fontSize: 11 }}>
                          {h}
                        </span>
                      ))}
                      {query.purpose && (
                        <span style={{ fontSize: 11, color: 'var(--text-dim)', fontStyle: 'italic' }}>
                          ({query.purpose})
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
                      Saved {new Date(item.created_at).toLocaleDateString()}
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <button
                      type="button"
                      className="btn-primary"
                      style={{ padding: '6px 12px', fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}
                      onClick={() => {
                        onSelectSearch(item)
                        onClose()
                      }}
                      title="Load & run this search"
                    >
                      <Play size={12} />
                      Run
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      style={{ padding: '6px 8px', color: 'var(--danger)' }}
                      onClick={(e) => handleDelete(item.id, e)}
                      disabled={deletingId === item.id}
                      title="Delete saved search"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
