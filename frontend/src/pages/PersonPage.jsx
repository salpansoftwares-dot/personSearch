import { useState, useEffect } from 'react'
import Navbar from '../components/Navbar'
import DisputeModal from '../components/DisputeModal'
import { parsePersonClaims, detectPlatform } from '../utils/personHelper'
import {
  ArrowLeft,
  ExternalLink,
  Calendar,
  AlertTriangle,
  FileText,
  Building,
  Briefcase,
  Github,
  Linkedin,
  Twitter,
  Globe,
  BookOpen,
  Mic,
  GraduationCap,
  FolderGit2,
  Copy,
  Check,
  Users,
} from '../components/Icons'

const API = '/api/v1'

function renderPlatformIcon(iconType, size = 13) {
  switch (iconType) {
    case 'github': return <Github size={size} />
    case 'linkedin': return <Linkedin size={size} />
    case 'twitter': return <Twitter size={size} />
    case 'book': return <BookOpen size={size} />
    default: return <Globe size={size} />
  }
}

function confLabel(conf) {
  return `${Math.round((conf ?? 0) * 100)}%`
}

function confBadgeClass(conf) {
  if (conf >= 0.75) return 'badge-confidence'
  return 'badge-low'
}

/** Single evidence item inside the profile */
function EvidenceBlock({ evidence }) {
  if (!evidence?.length) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
      {evidence.map((ev, i) => (
        <div key={i} className="evidence-item">
          <div className="evidence-url">
            <ExternalLink size={12} />
            <a href={ev.source_url} target="_blank" rel="noopener noreferrer">
              {ev.source_url}
            </a>
          </div>
          {ev.excerpt && (
            <div className="evidence-excerpt">"{ev.excerpt}"</div>
          )}
          <div className="evidence-meta">
            {ev.source_type && (
              <span className="evidence-tag">
                <span style={{ color: 'var(--accent)' }}>◆</span>
                {ev.source_type}
              </span>
            )}
            {ev.retrieved_at && (
              <span className="evidence-tag">
                <Calendar size={12} />
                {new Date(ev.retrieved_at).toLocaleDateString('en-GB', {
                  year: 'numeric', month: 'short', day: 'numeric'
                })}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

/** Full claim card on the profile page — always shows evidence */
function ProfileClaim({ claim, onDispute }) {
  return (
    <div className="claim-row" style={{ marginBottom: 0 }}>
      <div className="claim-header" style={{ cursor: 'default' }}>
        <span className="claim-type-badge">{claim.type}</span>
        <span className="claim-value" title={claim.value} style={{ whiteSpace: 'normal', overflow: 'visible' }}>
          {claim.value}
        </span>
        <span className={`badge ${confBadgeClass(claim.confidence)}`} style={{ flexShrink: 0 }}>
          {confLabel(claim.confidence)}
        </span>
        <button
          className="btn btn-ghost"
          style={{ fontSize: 11, padding: '4px 10px', flexShrink: 0 }}
          onClick={() => onDispute(claim.claim_id)}
          id={`dispute-claim-${claim.claim_id}`}
          title="Dispute this claim"
        >
          Dispute
        </button>
      </div>
      <EvidenceBlock evidence={claim.evidence} />
    </div>
  )
}

export default function PersonPage({ personId, navigate }) {
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [disputeTarget, setDisputeTarget] = useState(null) // { personId?, claimId? }
  const [copied, setCopied]   = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setProfile(null)

    fetch(`${API}/persons/${personId}`)
      .then(res => {
        if (!res.ok) return res.json().then(e => { throw new Error(e.detail || `HTTP ${res.status}`) })
        return res.json()
      })
      .then(data => { if (!cancelled) setProfile(data) })
      .catch(err => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [personId])

  function handleCopyId() {
    navigator.clipboard?.writeText(personId)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  const initials = profile?.canonical_name
    ?.split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join('') ?? '?'

  const parsed = profile ? parsePersonClaims(profile.claims) : null

  return (
    <>
      <Navbar navigate={navigate} />

      <main className="page" id="main-content">
        {/* Back navigation */}
        <div className="container" style={{ marginTop: 24 }}>
          <button
            className="back-link"
            style={{ background: 'none', border: 'none', textAlign: 'left', margin: 0, padding: 0 }}
            onClick={() => navigate('/')}
            id="back-to-search-btn"
          >
            <ArrowLeft size={14} />
            Back to search
          </button>
        </div>

        {loading && (
          <div className="status-bar container" style={{ marginTop: 40 }}>
            <div className="spinner" />
            <span>Loading professional dossier…</span>
          </div>
        )}

        {error && (
          <div className="error-banner container" style={{ marginTop: 24 }}>
            <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
            <div>
              <strong>Could not load profile</strong>
              <br />
              {error}
            </div>
          </div>
        )}

        {profile && !loading && (
          <div className="container" style={{ marginTop: 24 }}>
            <div className="person-card-split profile-dossier-layout">
              {/* ─── LEFT COLUMN: Identity, Avatar, Org & Details ─────────── */}
              <aside className="person-rail-left">
                {/* Avatar & Core Identity */}
                <div className="person-id-header">
                  <div className="person-avatar-large profile-page-avatar">
                    <span>{initials}</span>
                    <div className="avatar-status-ring" />
                  </div>

                  <div className="person-id-titles">
                    <h1 className="person-name-headline" style={{ fontSize: 'clamp(20px, 3vw, 26px)' }}>
                      {profile.canonical_name}
                    </h1>
                    <div className="person-badges-row">
                      <span className="badge badge-label">possible match</span>
                      <span className={`badge ${profile.status === 'active' ? 'badge-confidence' : 'badge-low'}`}>
                        {profile.status}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Primary Occupation & Organization */}
                <div className="person-primary-block">
                  <div className="person-primary-occupation">
                    <Briefcase size={14} style={{ color: 'var(--accent)' }} />
                    <span>{parsed.primaryOccupation}</span>
                  </div>

                  {parsed.primaryOrg && (
                    <div className="person-primary-org">
                      <Building size={14} style={{ color: 'var(--accent-2)' }} />
                      <div className="org-text-group">
                        <span className="org-label">Primary Organization</span>
                        <span className="org-name">{parsed.primaryOrg.value}</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* Public Social & Professional Profiles */}
                {parsed.profileUrls.length > 0 && (
                  <div className="person-social-links-block">
                    <div className="rail-subtitle">Public Profiles & Links</div>
                    <div className="social-chips-grid">
                      {parsed.profileUrls.map((p, idx) => {
                        const plat = detectPlatform(p.value)
                        return (
                          <a
                            key={idx}
                            href={p.value}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="social-chip"
                            style={{ borderColor: plat.bg }}
                            title={`Open ${plat.name} (${p.value})`}
                          >
                            <span style={{ color: plat.color, display: 'inline-flex' }}>
                              {renderPlatformIcon(plat.iconType, 13)}
                            </span>
                            <span className="social-chip-text">{plat.handle}</span>
                            <ExternalLink size={10} style={{ opacity: 0.6 }} />
                          </a>
                        )
                      })}
                    </div>
                  </div>
                )}

                {/* Stats & Metadata */}
                <div className="person-meta-summary">
                  <div className="meta-stat-pill">
                    <span className="stat-number">{profile.claims.length}</span>
                    <span className="stat-desc">claims</span>
                  </div>
                  <div className="meta-stat-pill">
                    <span className="stat-number">{parsed.totalSourcesCount}</span>
                    <span className="stat-desc">sources</span>
                  </div>
                  {parsed.allOrgs.length > 1 && (
                    <div className="meta-stat-pill">
                      <span className="stat-number">{parsed.allOrgs.length}</span>
                      <span className="stat-desc">orgs</span>
                    </div>
                  )}
                </div>

                {/* Cluster ID */}
                <div className="person-id-chip">
                  <span className="id-label">ID:</span>
                  <code className="id-code">{profile.person_id.slice(0, 13)}…</code>
                  <button
                    className="id-copy-btn"
                    onClick={handleCopyId}
                    title="Copy full cluster ID"
                  >
                    {copied ? <Check size={12} style={{ color: 'var(--success)' }} /> : <Copy size={12} />}
                  </button>
                </div>

                <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
                  Updated {new Date(profile.updated_at).toLocaleDateString('en-GB', {
                    year: 'numeric', month: 'short', day: 'numeric'
                  })}
                </div>

                {/* Dispute / Removal Request */}
                <div style={{ marginTop: 20, width: '100%' }}>
                  <button
                    className="btn btn-danger"
                    style={{ width: '100%', justifyContent: 'center' }}
                    onClick={() => setDisputeTarget({ personId: profile.person_id })}
                    id="dispute-profile-btn"
                  >
                    <FileText size={14} />
                    Request correction / removal
                  </button>
                </div>

                {/* Separate / Alternative Profiles with Same Name */}
                {profile.alternatives?.length > 0 && (
                  <div className="alternatives-box" style={{ marginTop: 24 }}>
                    <div className="rail-subtitle" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Users size={13} style={{ color: 'var(--warning)' }} />
                      <span>{profile.alternatives.length} Alternative Profile{profile.alternatives.length !== 1 ? 's' : ''}</span>
                    </div>
                    <p style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 10, lineHeight: 1.5 }}>
                      Other clusters with this name kept separate to prevent false merges:
                    </p>
                    <div className="alt-list">
                      {profile.alternatives.map(altId => (
                        <div
                          key={altId}
                          className="alt-item"
                          role="button"
                          tabIndex={0}
                          onClick={() => navigate(`/persons/${altId}`)}
                          onKeyDown={e => e.key === 'Enter' && navigate(`/persons/${altId}`)}
                          id={`alt-person-${altId}`}
                        >
                          <div className="alt-id">{altId}</div>
                          <ArrowLeft size={13} style={{ transform: 'rotate(180deg)', color: 'var(--text-dim)', flexShrink: 0 }} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </aside>

              {/* ─── RIGHT COLUMN: Organizations, Roles, Claims & Evidence ─ */}
              <section className="person-rail-right">
                {/* Organizations Section */}
                <div className="right-section-box">
                  <div className="right-section-header">
                    <div className="header-left">
                      <Building size={15} style={{ color: 'var(--accent)' }} />
                      <h2 className="right-section-title">Organizations & Affiliations</h2>
                    </div>
                    <span className="section-count-tag">{parsed.allOrgs.length}</span>
                  </div>

                  {parsed.allOrgs.length > 0 ? (
                    <div className="orgs-flow-wrap">
                      {parsed.allOrgs.map((org, i) => (
                        <div
                          key={i}
                          className={`org-flow-chip ${i === 0 ? 'primary-org-chip' : ''}`}
                        >
                          <Building size={12} />
                          <span className="org-chip-title">{org.value}</span>
                          {i === 0 && <span className="primary-pill">Primary</span>}
                          <span className="chip-conf">{confLabel(org.confidence)}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-sub-inline">No organizations explicitly recorded in evidence.</div>
                  )}
                </div>

                {/* Roles & Positions Section */}
                <div className="right-section-box">
                  <div className="right-section-header">
                    <div className="header-left">
                      <Briefcase size={15} style={{ color: 'var(--accent-2)' }} />
                      <h2 className="right-section-title">Roles & Occupations</h2>
                    </div>
                    <span className="section-count-tag">{parsed.roles.length + parsed.occupations.length}</span>
                  </div>

                  {(parsed.roles.length > 0 || parsed.occupations.length > 0) ? (
                    <div className="roles-flow-wrap">
                      {parsed.occupations.map((occ, i) => (
                        <div key={`occ-${i}`} className="role-flow-chip occupation-tag">
                          <span className="role-chip-title">{occ.value}</span>
                          <span className="tag-type">Occupation</span>
                          <span className="chip-conf">{confLabel(occ.confidence)}</span>
                        </div>
                      ))}
                      {parsed.roles.map((r, i) => (
                        <div key={`role-${i}`} className="role-flow-chip">
                          <span className="role-chip-title">{r.value}</span>
                          <span className="tag-type">Role</span>
                          <span className="chip-conf">{confLabel(r.confidence)}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-sub-inline">No specific roles or occupations recorded.</div>
                  )}
                </div>

                {/* Credentials & Works if present */}
                {(parsed.publications.length > 0 || parsed.talks.length > 0 || parsed.educations.length > 0 || parsed.projects.length > 0) && (
                  <div className="right-section-box credentials-box">
                    <div className="right-section-header">
                      <div className="header-left">
                        <BookOpen size={15} style={{ color: 'var(--success)' }} />
                        <h2 className="right-section-title">Credentials & Public Work</h2>
                      </div>
                    </div>

                    <div className="credentials-pills-row">
                      {parsed.educations.map((ed, i) => (
                        <div key={`ed-${i}`} className="credential-pill">
                          <GraduationCap size={13} style={{ color: 'var(--accent)' }} />
                          <span>{ed.value}</span>
                        </div>
                      ))}
                      {parsed.publications.map((pub, i) => (
                        <div key={`pub-${i}`} className="credential-pill">
                          <BookOpen size={13} style={{ color: 'var(--accent-2)' }} />
                          <span>{pub.value}</span>
                        </div>
                      ))}
                      {parsed.talks.map((talk, i) => (
                        <div key={`talk-${i}`} className="credential-pill">
                          <Mic size={13} style={{ color: 'var(--warning)' }} />
                          <span>{talk.value}</span>
                        </div>
                      ))}
                      {parsed.projects.map((proj, i) => (
                        <div key={`proj-${i}`} className="credential-pill">
                          <FolderGit2 size={13} style={{ color: 'var(--success)' }} />
                          <span>{proj.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* All Extracted Claims & Evidence Spans */}
                <div className="right-section-box claims-box">
                  <div className="right-section-header">
                    <div className="header-left">
                      <FileText size={15} style={{ color: 'var(--accent)' }} />
                      <h2 className="right-section-title">All Extracted Claims & Source Spans</h2>
                    </div>
                    <span className="section-count-tag">{profile.claims.length} claims</span>
                  </div>

                  {profile.claims.length === 0 ? (
                    <div className="empty-state" style={{ padding: '30px 0' }}>
                      <div className="empty-title">No claims on record</div>
                      <p className="empty-sub">No sourced claims were persisted for this profile.</p>
                    </div>
                  ) : (
                    <div className="claims-list">
                      {profile.claims.map(claim => (
                        <ProfileClaim
                          key={claim.claim_id}
                          claim={claim}
                          onDispute={claimId => setDisputeTarget({ claimId })}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </section>
            </div>

            {/* Disclaimer */}
            <div className="disclaimer">
              This profile is assembled from public professional sources only. All outputs are labelled
              "possible match" — not a definitive identity. Every claim above links to its source.
              <br />
              Person ID: <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{profile.person_id}</code>
            </div>
          </div>
        )}
      </main>

      {/* Dispute modal */}
      {disputeTarget && (
        <DisputeModal
          personId={disputeTarget.personId ?? null}
          claimId={disputeTarget.claimId ?? null}
          onClose={() => setDisputeTarget(null)}
        />
      )}
    </>
  )
}
