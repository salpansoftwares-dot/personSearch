import { useState } from 'react'
import { Bookmark, Check, AlertTriangle } from './Icons'

const API = '/api/v1'

export default function SaveSearchDialog({ isOpen, onClose, name, hints, purpose, onSaved }) {
  const defaultLabel = [
    name,
    hints?.role || hints?.organization || hints?.country || '',
  ].filter(Boolean).join(' · ')

  const [label, setLabel] = useState(defaultLabel)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [savedSuccess, setSavedSuccess] = useState(false)

  if (!isOpen) return null

  async function handleSave(e) {
    e.preventDefault()
    if (!label.trim()) return

    setSaving(true)
    setError(null)

    try {
      const payload = {
        label: label.trim(),
        query: {
          name: name.trim(),
          hints: {
            organization: hints?.organization?.trim() || undefined,
            sector: hints?.sector?.trim() || undefined,
            country: hints?.country?.trim() || undefined,
            role: hints?.role?.trim() || undefined,
          },
          purpose: purpose?.trim() || undefined,
        },
      }

      const res = await fetch(`${API}/saved-searches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Failed to save search (HTTP ${res.status})`)
      }

      const created = await res.json()
      setSavedSuccess(true)
      if (onSaved) onSaved(created)
      setTimeout(() => {
        setSavedSuccess(false)
        onClose()
      }, 900)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" style={{ maxWidth: 480 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Bookmark size={18} style={{ color: 'var(--accent)' }} />
            <h2 className="modal-title">Save Search Query</h2>
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
          Save this query to re-execute discovery anytime. No personal data is stored with this query.
        </p>

        {error && (
          <div className="error-banner" style={{ marginBottom: 12 }}>
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSave}>
          <div className="input-group" style={{ marginBottom: 14 }}>
            <label className="input-label" htmlFor="save-search-label">
              Search Label
            </label>
            <input
              id="save-search-label"
              className="input-field"
              type="text"
              value={label}
              onChange={e => setLabel(e.target.value)}
              placeholder="e.g. AI Researchers at Google"
              autoFocus
              required
              disabled={saving || savedSuccess}
            />
          </div>

          <div
            style={{
              padding: '10px 12px',
              borderRadius: 'var(--radius)',
              background: 'var(--bg-subtle)',
              fontSize: 12,
              marginBottom: 18,
              border: '1px solid var(--border)',
            }}
          >
            <div style={{ color: 'var(--text-dim)', marginBottom: 4 }}>Saved Query Criteria:</div>
            <div><strong>Name:</strong> {name}</div>
            {(hints?.organization || hints?.role || hints?.country || hints?.sector) && (
              <div style={{ marginTop: 2 }}>
                <strong>Hints:</strong> {[hints.role, hints.organization, hints.country, hints.sector].filter(Boolean).join(', ')}
              </div>
            )}
            {purpose && (
              <div style={{ marginTop: 2 }}>
                <strong>Purpose:</strong> {purpose}
              </div>
            )}
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <button
              type="button"
              className="btn-secondary"
              onClick={onClose}
              disabled={saving}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={saving || !label.trim() || savedSuccess}
              style={{ minWidth: 100 }}
            >
              {savedSuccess ? (
                <><Check size={14} /> Saved!</>
              ) : saving ? (
                'Saving…'
              ) : (
                <><Bookmark size={14} /> Save</>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
