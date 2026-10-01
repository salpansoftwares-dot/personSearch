import { useState } from 'react'
import { CheckCircle, AlertTriangle } from './Icons'

const API = '/api/v1'

export default function DisputeModal({ personId, claimId, onClose }) {
  const [submitter, setSubmitter] = useState('')
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(null)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!submitter.trim()) {
      setError('Please enter your name or reference.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const body = {
        submitter: submitter.trim(),
        reason: reason.trim() || null,
      }
      if (personId) body.person_id = personId
      if (claimId) body.claim_id = claimId

      const res = await fetch(`${API}/disputes/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setSuccess(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Submit a dispute or removal request"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="modal">
        <div className="modal-title">Request correction or removal</div>
        <div className="modal-sub">
          You have the right to request correction or removal of inaccurate information.
          Your request will be reviewed and resolved within the defined SLA.
        </div>

        {success ? (
          <div className="success-msg">
            <CheckCircle size={20} style={{ flexShrink: 0 }} />
            <div>
              <strong>Request received</strong>
              <br />
              {success.message}
              <br />
              <span style={{ fontSize: 12, opacity: 0.7 }}>
                Reference: {success.dispute_id}
              </span>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="modal-fields">
              <div className="input-group">
                <label className="input-label" htmlFor="dispute-submitter">
                  Your name or reference *
                </label>
                <input
                  id="dispute-submitter"
                  className="input-field"
                  type="text"
                  placeholder="e.g. John Kamau or legal@example.com"
                  value={submitter}
                  onChange={e => setSubmitter(e.target.value)}
                  required
                  maxLength={512}
                  disabled={loading}
                />
              </div>
              <div className="input-group">
                <label className="input-label" htmlFor="dispute-reason">
                  Reason for the request
                </label>
                <textarea
                  id="dispute-reason"
                  className="input-field"
                  placeholder="Describe what is incorrect or why it should be removed…"
                  value={reason}
                  onChange={e => setReason(e.target.value)}
                  rows={4}
                  maxLength={2048}
                  disabled={loading}
                  style={{ resize: 'vertical' }}
                />
              </div>
              {error && (
                <div className="error-banner" style={{ margin: 0 }}>
                  <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
                  {error}
                </div>
              )}
            </div>
            <div className="modal-actions">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={onClose}
                disabled={loading}
                id="dispute-cancel-btn"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn btn-danger"
                disabled={loading}
                id="dispute-submit-btn"
              >
                {loading ? 'Submitting…' : 'Submit request'}
              </button>
            </div>
          </form>
        )}

        {success && (
          <div className="modal-actions" style={{ marginTop: 20 }}>
            <button className="btn btn-ghost" onClick={onClose} id="dispute-close-btn">
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
