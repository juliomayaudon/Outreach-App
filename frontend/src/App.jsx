import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { api } from './lib/api'
import Accounts from './pages/Accounts'
import CampaignDetail from './pages/CampaignDetail'
import Campaigns from './pages/Campaigns'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import NewCampaign from './pages/NewCampaign'
import Team from './pages/Team'

const AuthContext = createContext(null)
export const useAuth = () => useContext(AuthContext)

export default function App() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      setUser(await api.me())
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const logout = useCallback(async () => {
    await api.logout()
    setUser(null)
  }, [])

  if (loading) return <div className="spinner">Loading…</div>

  if (!user) {
    return (
      <AuthContext.Provider value={{ user, setUser, refresh, logout }}>
        <Login onSignedIn={setUser} />
      </AuthContext.Provider>
    )
  }

  return (
    <AuthContext.Provider value={{ user, setUser, refresh, logout }}>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/campaigns" element={<Campaigns />} />
          <Route path="/campaigns/new" element={<NewCampaign />} />
          <Route path="/campaigns/:id" element={<CampaignDetail />} />
          <Route path="/accounts" element={<Accounts />} />
          {user.role === 'admin' && <Route path="/team" element={<Team />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </AuthContext.Provider>
  )
}
