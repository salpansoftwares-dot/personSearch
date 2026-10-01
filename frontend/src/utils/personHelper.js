/**
 * Utility helpers to parse, categorize, and structure claims and identity
 * details for rich persona presentations.
 */

export function parsePersonClaims(claims = []) {
  const orgs = []
  const roles = []
  const occupations = []
  const profileUrls = []
  const publications = []
  const talks = []
  const educations = []
  const projects = []
  const otherClaims = []

  const seenUrls = new Set()
  const allSources = new Set()

  claims.forEach(c => {
    (c.evidence || []).forEach(ev => {
      if (ev.source_url) allSources.add(ev.source_url)
    })

    const val = (c.value || '').trim()
    if (!val) return

    switch (c.type) {
      case 'organization':
        if (!orgs.find(o => o.value.toLowerCase() === val.toLowerCase())) {
          orgs.push(c)
        }
        break
      case 'role':
        if (!roles.find(r => r.value.toLowerCase() === val.toLowerCase())) {
          roles.push(c)
        }
        break
      case 'occupation':
        if (!occupations.find(o => o.value.toLowerCase() === val.toLowerCase())) {
          occupations.push(c)
        }
        break
      case 'profile_url':
        if (!seenUrls.has(val.toLowerCase())) {
          seenUrls.add(val.toLowerCase())
          profileUrls.push(c)
        }
        break
      case 'publication':
        publications.push(c)
        break
      case 'talk':
        talks.push(c)
        break
      case 'education':
        educations.push(c)
        break
      case 'project':
        projects.push(c)
        break
      default:
        otherClaims.push(c)
        break
    }
  })

  // Sort organizations by confidence (descending)
  const sortedOrgs = [...orgs].sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
  const primaryOrg = sortedOrgs[0] || null
  const otherOrgs = sortedOrgs.slice(1)

  // Primary headline: occupation or role
  const primaryOccupation = occupations[0]?.value || roles[0]?.value || 'Professional'

  return {
    primaryOrg,
    otherOrgs,
    allOrgs: sortedOrgs,
    occupations,
    roles,
    profileUrls,
    publications,
    talks,
    educations,
    projects,
    otherClaims,
    primaryOccupation,
    totalSourcesCount: allSources.size,
  }
}

/**
 * Detect social / developer platform from URL to render brand icons and clean handles.
 */
export function detectPlatform(url = '') {
  const lower = url.toLowerCase()

  if (lower.includes('github.com')) {
    const parts = url.replace(/https?:\/\/(www\.)?github\.com\//, '').split('/')
    const handle = parts[0] ? `@${parts[0]}` : 'GitHub'
    return { name: 'GitHub', handle, iconType: 'github', color: '#e8ecf8', bg: 'rgba(232,236,248,0.08)' }
  }

  if (lower.includes('linkedin.com')) {
    const parts = url.replace(/https?:\/\/([a-z]{2}\.)?linkedin\.com\/in\//, '').split(/[/?]/)
    const handle = parts[0] ? `@${parts[0]}` : 'LinkedIn'
    return { name: 'LinkedIn', handle, iconType: 'linkedin', color: '#60a5fa', bg: 'rgba(96,165,250,0.1)' }
  }

  if (lower.includes('twitter.com') || lower.includes('x.com')) {
    const parts = url.replace(/https?:\/\/(www\.)?(twitter|x)\.com\//, '').split(/[/?]/)
    const handle = parts[0] ? `@${parts[0]}` : 'X (Twitter)'
    return { name: 'X / Twitter', handle, iconType: 'twitter', color: '#38bdf8', bg: 'rgba(56,189,248,0.1)' }
  }

  if (lower.includes('scholar.google')) {
    return { name: 'Google Scholar', handle: 'Scholar Profile', iconType: 'book', color: '#818cf8', bg: 'rgba(129,140,248,0.1)' }
  }

  if (lower.includes('orcid.org')) {
    const orcidId = url.replace(/https?:\/\/orcid\.org\//, '').replace(/\/$/, '')
    return { name: 'ORCID', handle: orcidId || 'ORCID', iconType: 'globe', color: '#a3e635', bg: 'rgba(163,230,53,0.1)' }
  }

  if (lower.includes('researchgate.net')) {
    return { name: 'ResearchGate', handle: 'ResearchGate', iconType: 'book', color: '#2dd4bf', bg: 'rgba(45,212,191,0.1)' }
  }

  // Generic website / company link
  try {
    const domain = new URL(url).hostname.replace(/^www\./, '')
    return { name: domain, handle: domain, iconType: 'globe', color: 'var(--accent)', bg: 'var(--accent-glow)' }
  } catch {
    return { name: 'Website', handle: 'Web Profile', iconType: 'globe', color: 'var(--accent)', bg: 'var(--accent-glow)' }
  }
}
