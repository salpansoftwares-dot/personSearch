import { useState, useCallback } from 'react'
import SearchPage from './pages/SearchPage'
import PersonPage from './pages/PersonPage'

// Minimal client-side router (no external dep needed)
function Router() {
  const [path, setPath] = useState(() => {
    // e.g. /persons/uuid or /
    return window.location.pathname
  })

  const navigate = useCallback((to) => {
    window.history.pushState({}, '', to)
    setPath(to)
  }, [])

  // Listen to browser back/forward
  useState(() => {
    const handler = () => setPath(window.location.pathname)
    window.addEventListener('popstate', handler)
    return () => window.removeEventListener('popstate', handler)
  })

  const personMatch = path.match(/^\/persons\/([0-9a-f-]+)$/i)

  return personMatch
    ? <PersonPage personId={personMatch[1]} navigate={navigate} />
    : <SearchPage navigate={navigate} />
}

export default function App() {
  return <Router />
}
