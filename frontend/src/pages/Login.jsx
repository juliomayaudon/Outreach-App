import { useEffect, useState } from 'react'
import { api } from '../lib/api'

export default function Login({ onSignedIn }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [config, setConfig] = useState({ google_enabled: false, google_domain: '' })

  useEffect(() => {
    // The callback bounces back here with a reason when it refuses someone.
    const reported = new URLSearchParams(window.location.search).get('auth_error')
    if (reported) {
      setError(reported)
      window.history.replaceState({}, '', window.location.pathname)
    }
    api.authConfig().then(setConfig).catch(() => {})
  }, [])

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      onSignedIn(await api.login(email, password))
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <div className="card login-card">
        <h1>Outreach</h1>
        <div className="muted small">Sign in to send and track connection requests.</div>
        {error && <div className="alert alert-error">{error}</div>}

        {config.google_enabled && (
          <>
            {/* A full page navigation, not fetch: the whole point is the
                round trip through Google and back. */}
            <a className="btn-google" href="/api/auth/google/start">
              <GoogleMark />
              Continue with Google
            </a>
            {config.google_domain && (
              <div className="field-hint" style={{ textAlign: 'center', marginTop: 8 }}>
                Anyone with a @{config.google_domain} address can sign in.
              </div>
            )}
            <div className="or-rule">
              <span>or</span>
            </div>
          </>
        )}

        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>
          <button className="btn-primary" type="submit" disabled={busy} style={{ width: '100%' }}>
            {busy ? 'Signing in\u2026' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#4285F4" d="M45.1 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h11.8c-.5 2.7-2 5-4.4 6.6v5.5h7.1c4.1-3.8 6.6-9.4 6.6-16.1z" />
      <path fill="#34A853" d="M24 46c5.9 0 10.9-2 14.5-5.4l-7.1-5.5c-2 1.3-4.5 2.1-7.4 2.1-5.7 0-10.6-3.9-12.3-9.1H4.3v5.7C7.9 41 15.4 46 24 46z" />
      <path fill="#FBBC05" d="M11.7 28.1c-.4-1.3-.7-2.7-.7-4.1s.3-2.8.7-4.1v-5.7H4.3A22 22 0 0 0 2 24c0 3.6.9 6.9 2.3 9.8l7.4-5.7z" />
      <path fill="#EA4335" d="M24 10.8c3.2 0 6.1 1.1 8.4 3.3l6.3-6.3C34.9 4.1 29.9 2 24 2 15.4 2 7.9 7 4.3 14.2l7.4 5.7c1.7-5.2 6.6-9.1 12.3-9.1z" />
    </svg>
  )
}
