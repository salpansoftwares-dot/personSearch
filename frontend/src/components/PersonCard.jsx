import { useState } from 'react'
import { parsePersonClaims, detectPlatform } from '../utils/personHelper'
import {
  ChevronRight,
  ExternalLink,
  Calendar,
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
  FileText,
  Printer,
} from './Icons'


function renderPlatformIcon(iconType, size = 13) {
  switch (iconType) {
    case 'github': return <Github size={size} />
    case 'linkedin': return <Linkedin size={size} />
    case 'twitter': return <Twitter size={size} />
    case 'book': return <BookOpen size={size} />
    default: return <Globe size={size} />
  }
}

/** Convert confidence 0–1 to a badge class */
function confBadgeClass(conf) {
  if (conf >= 0.75) return 'badge-confidence'
  return 'badge-low'
}

function confLabel(conf) {
  return `${Math.round((conf || 0) * 100)}%`
}

/** Single evidence drawer for one claim */
function EvidenceDrawer({ evidence }) {
  return (
    <div className="evidence-drawer">
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

/** Single claim row with expandable evidence drawer */
function ClaimRow({ claim }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="claim-row">
      <div
        className="claim-header"
        onClick={() => setOpen(o => !o)}
        role="button"
        tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && setOpen(o => !o)}
        aria-expanded={open}
        id={`claim-${claim.claim_id}`}
      >
        <span className="claim-type-badge">{claim.type}</span>
        <span className="claim-value" title={claim.value}>{claim.value}</span>
        <span
          className={`claim-conf ${confBadgeClass(claim.confidence)}`}
          style={{ background: 'transparent', border: 'none', padding: 0, borderRadius: 0 }}
        >
          {confLabel(claim.confidence)}
        </span>
        <ChevronRight
          size={15}
          className={`claim-chevron${open ? ' open' : ''}`}
        />
      </div>
      {open && claim.evidence?.length > 0 && (
        <EvidenceDrawer evidence={claim.evidence} />
      )}
    </div>
  )
}

/** Rich 2-column persona card */
export default function PersonCard({ person, navigate }) {
  const [showAllClaims, setShowAllClaims] = useState(false)
  const [copied, setCopied] = useState(false)

  const parsed = parsePersonClaims(person.claims)

  const initials = person.canonical_name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join('') || '?'

  function handleCopyId(e) {
    e.stopPropagation()
    navigator.clipboard?.writeText(person.person_id)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  // Preview up to 5 claims by default or all if expanded
  const displayedClaims = showAllClaims ? person.claims : person.claims.slice(0, 5)

  return (
    <article className="person-card-split" aria-label={`Profile: ${person.canonical_name}`}>
      {/* ─── LEFT COLUMN: Identity, Avatar, Org & Details ───────────────── */}
      <aside className="person-rail-left">
        {/* Avatar & Core Identity */}
        <div className="person-id-header">
          <div className="person-avatar-large">
            <span>{initials}</span>
            <div className="avatar-status-ring" />
          </div>

          <div className="person-id-titles">
            <h2 className="person-name-headline">{person.canonical_name}</h2>
            <div className="person-badges-row">
              <span className="badge badge-label">{person.label}</span>
              <span className={`badge ${confBadgeClass(person.confidence)}`}>
                {confLabel(person.confidence)} match
              </span>
            </div>
          </div>
        </div>

        {/* Primary Headline & Primary Organization */}
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

        {/* Details & Metadata */}
        <div className="person-meta-summary">
          <div className="meta-stat-pill">
            <span className="stat-number">{person.claims.length}</span>
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

        {/* Person ID snippet */}
        <div className="person-id-chip">
          <span className="id-label">ID:</span>
          <code className="id-code">{person.person_id.slice(0, 13)}…</code>
          <button
            className="id-copy-btn"
            onClick={handleCopyId}
            title="Copy full cluster ID"
            aria-label="Copy Person ID"
          >
            {copied ? <Check size={12} style={{ color: 'var(--success)' }} /> : <Copy size={12} />}
          </button>
        </div>

        {/* CTA Buttons */}
        <div style={{ display: 'flex', gap: 6, width: '100%', marginTop: 8 }}>
          <button
            className="btn btn-primary full-profile-btn"
            style={{ flex: 1, margin: 0 }}
            onClick={() => navigate(`/persons/${person.person_id}`)}
            id={`view-profile-${person.person_id}`}
          >
            View Full Dossier →
          </button>
          <a
            href={`/api/v1/persons/${person.person_id}/report?format=html`}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-secondary"
            style={{
              padding: '6px 10px',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              textDecoration: 'none',
              fontSize: 12,
            }}
            title="Export Evidence Report (Printable/PDF)"
            id={`export-report-btn-${person.person_id}`}
          >
            <Printer size={13} />
            <span>Report</span>
          </a>
        </div>


        {person.alternatives?.length > 0 && (
          <div className="alternatives-note">
            <span>{person.alternatives.length} separate profile{person.alternatives.length !== 1 ? 's' : ''} found with this name</span>
          </div>
        )}
      </aside>

      {/* ─── RIGHT COLUMN: Organizations, Roles, Claims & Evidence ─────── */}
      <section className="person-rail-right">
        {/* Organizations Section */}
        <div className="right-section-box">
          <div className="right-section-header">
            <div className="header-left">
              <Building size={15} style={{ color: 'var(--accent)' }} />
              <h3 className="right-section-title">Organizations & Affiliations</h3>
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
              <h3 className="right-section-title">Roles & Occupations</h3>
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

        {/* Education, Publications & Projects summary if available */}
        {(parsed.publications.length > 0 || parsed.talks.length > 0 || parsed.educations.length > 0 || parsed.projects.length > 0) && (
          <div className="right-section-box credentials-box">
            <div className="right-section-header">
              <div className="header-left">
                <BookOpen size={15} style={{ color: 'var(--success)' }} />
                <h3 className="right-section-title">Credentials & Public Work</h3>
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

        {/* Sourced Claims with Expandable Evidence */}
        <div className="right-section-box claims-box">
          <div className="right-section-header">
            <div className="header-left">
              <FileText size={15} style={{ color: 'var(--accent)' }} />
              <h3 className="right-section-title">Sourced Claims & Evidence</h3>
            </div>
            <span className="section-count-tag">{person.claims.length} claims</span>
          </div>

          <div className="claims-list">
            {displayedClaims.map(claim => (
              <ClaimRow key={claim.claim_id} claim={claim} />
            ))}
          </div>

          {person.claims.length > 5 && (
            <div className="claims-expand-bar">
              <button
                type="button"
                className="btn-toggle-claims"
                onClick={() => setShowAllClaims(prev => !prev)}
              >
                {showAllClaims
                  ? 'Show fewer claims'
                  : `Show all ${person.claims.length} claims (+${person.claims.length - 5} more)`}
              </button>
            </div>
          )}
        </div>
      </section>
    </article>
  )
}
