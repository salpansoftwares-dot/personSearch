import { useState } from 'react'
import { parsePersonClaims, detectPlatform } from '../utils/personHelper'
import {
  ExternalLink,
  Building,
  Briefcase,
  Github,
  Linkedin,
  Twitter,
  Globe,
  BookOpen,
  Copy,
  Check,
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

function confBadgeClass(conf) {
  if (conf >= 0.75) return 'badge-confidence'
  return 'badge-low'
}

function confLabel(conf) {
  return `${Math.round((conf || 0) * 100)}%`
}

export default function PersonCompareView({ persons, navigate }) {
  const [copiedId, setCopiedId] = useState(null)

  function handleCopy(id) {
    navigator.clipboard?.writeText(id)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 1800)
  }

  return (
    <div className="compare-container">
      <div className="compare-header">
        <div className="compare-badge">
          <span style={{ color: 'var(--accent)' }}>●</span> Multi-Profile Comparison
        </div>
        <p className="compare-hint">
          Side-by-side view to disambiguate between profiles sharing the same name without false merging.
        </p>
      </div>

      <div
        className="compare-grid"
        style={{
          gridTemplateColumns: `repeat(${Math.min(persons.length, 3)}, 1fr)`,
        }}
      >
        {persons.map((person, idx) => {
          const parsed = parsePersonClaims(person.claims)
          const initials = person.canonical_name
            .split(' ')
            .filter(Boolean)
            .slice(0, 2)
            .map(w => w[0].toUpperCase())
            .join('') || '?'

          return (
            <div key={person.person_id} className="compare-card">
              {/* Card top banner */}
              <div className="compare-profile-hero">
                <div className="compare-avatar-wrapper">
                  <div className="person-avatar compare-avatar">{initials}</div>
                  <span className="compare-index-pill">Profile #{idx + 1}</span>
                </div>

                <div className="compare-hero-info">
                  <div className="compare-name">{person.canonical_name}</div>
                  <div className="compare-badges">
                    <span className="badge badge-label">{person.label}</span>
                    <span className={`badge ${confBadgeClass(person.confidence)}`}>
                      {confLabel(person.confidence)} match
                    </span>
                  </div>
                </div>
              </div>

              {/* Primary headline */}
              <div className="compare-section compare-headline-box">
                <div className="compare-section-label">Primary Identity</div>
                <div className="compare-primary-role">{parsed.primaryOccupation}</div>
                {parsed.primaryOrg ? (
                  <div className="compare-primary-org">
                    <Building size={14} style={{ color: 'var(--accent)', flexShrink: 0 }} />
                    <span>{parsed.primaryOrg.value}</span>
                  </div>
                ) : (
                  <div className="compare-dim-text">No primary organization confirmed</div>
                )}
              </div>

              {/* Other Orgs */}
              <div className="compare-section">
                <div className="compare-section-label">
                  Other Organizations ({parsed.otherOrgs.length})
                </div>
                {parsed.otherOrgs.length > 0 ? (
                  <div className="compare-tags-wrap">
                    {parsed.otherOrgs.map((org, i) => (
                      <span key={i} className="compare-tag-chip org-chip">
                        <Building size={12} />
                        {org.value}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="compare-dim-text">No other organizations found</div>
                )}
              </div>

              {/* Roles */}
              <div className="compare-section">
                <div className="compare-section-label">
                  Identified Roles ({parsed.roles.length})
                </div>
                {parsed.roles.length > 0 ? (
                  <div className="compare-tags-wrap">
                    {parsed.roles.map((r, i) => (
                      <span key={i} className="compare-tag-chip role-chip">
                        <Briefcase size={12} />
                        {r.value}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="compare-dim-text">No distinct roles recorded</div>
                )}
              </div>

              {/* Social / Web Profiles */}
              <div className="compare-section">
                <div className="compare-section-label">
                  Public Profiles ({parsed.profileUrls.length})
                </div>
                {parsed.profileUrls.length > 0 ? (
                  <div className="compare-links-list">
                    {parsed.profileUrls.map((p, i) => {
                      const plat = detectPlatform(p.value)
                      return (
                        <a
                          key={i}
                          href={p.value}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="compare-profile-link"
                          style={{ borderColor: plat.bg }}
                        >
                          <span style={{ color: plat.color, display: 'inline-flex' }}>
                            {renderPlatformIcon(plat.iconType, 13)}
                          </span>
                          <span className="compare-link-text">{plat.name}: {plat.handle}</span>
                          <ExternalLink size={11} style={{ opacity: 0.6 }} />
                        </a>
                      )
                    })}
                  </div>
                ) : (
                  <div className="compare-dim-text">No public profile URLs found</div>
                )}
              </div>

              {/* Publications & Education count */}
              <div className="compare-stats-row">
                <div className="compare-stat-item">
                  <span className="compare-stat-val">{parsed.totalSourcesCount}</span>
                  <span className="compare-stat-lbl">Sources</span>
                </div>
                <div className="compare-stat-item">
                  <span className="compare-stat-val">{person.claims.length}</span>
                  <span className="compare-stat-lbl">Claims</span>
                </div>
                <div className="compare-stat-item">
                  <span className="compare-stat-val">{parsed.publications.length}</span>
                  <span className="compare-stat-lbl">Pubs</span>
                </div>
              </div>

              {/* Card Footer Actions */}
              <div className="compare-footer">
                <button
                  className="compare-copy-btn"
                  onClick={() => handleCopy(person.person_id)}
                  title="Copy Person ID"
                >
                  {copiedId === person.person_id ? <Check size={13} style={{ color: 'var(--success)' }} /> : <Copy size={13} />}
                  <span>{copiedId === person.person_id ? 'Copied' : `${person.person_id.slice(0, 8)}…`}</span>
                </button>

                <button
                  className="btn btn-primary"
                  style={{ fontSize: 12, padding: '7px 14px', width: '100%', justifyContent: 'center' }}
                  onClick={() => navigate(`/persons/${person.person_id}`)}
                  id={`compare-view-${person.person_id}`}
                >
                  View full dossier →
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
