import { useEffect, useState } from 'react'
import Badge from '../components/Badge'
import { api } from '../lib/api'
import { dateTime, thousands } from '../lib/format'

const TIMEZONES = [
  'America/Guayaquil',
  'America/Caracas',
  'America/Bogota',
  'America/Mexico_City',
  'America/New_York',
  'America/Los_Angeles',
  'Europe/Madrid',
  'Europe/Amsterdam',
  'UTC',
]

const TOKENS_PLACEHOLDER =
  "{'li_at': '...', 'JSESSIONID': '\"ajax:...\"', 'csrf-token': 'ajax:...', 'user-agent': '...'}"

const EMPTY = {
  label: '',
  tokens: '',
  timezone: 'America/Guayaquil',
  daily_limit: 20,
  weekly_limit: 100,
  window_start_hour: 9,
  window_end_hour: 18,
  skip_weekends: true,
  min_delay_seconds: 90,
  max_delay_seconds: 300,
}

export default function Accounts() {
  const [accounts, setAccounts] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    try {
      setAccounts(await api.accounts())
    } catch (problem) {
      setError(problem.message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }))
  }

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (editing) {
        const payload = { ...form }
        if (!payload.tokens) delete payload.tokens
        await api.updateAccount(editing, payload)
      } else {
        await api.createAccount(form)
      }
      setForm(EMPTY)
      setShowForm(false)
      setEditing(null)
      await load()
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  async function act(id, action) {
    setError('')
    try {
      if (action === 'test') await api.testAccount(id)
      if (action === 'pause') await api.updateAccount(id, { status: 'paused' })
      if (action === 'resume') await api.updateAccount(id, { status: 'active' })
      if (action === 'delete') {
        if (!window.confirm('Delete this LinkedIn account from the app?')) return
        await api.deleteAccount(id)
      }
      await load()
    } catch (problem) {
      setError(problem.message)
    }
  }

  function startEdit(account) {
    setEditing(account.id)
    setShowForm(true)
    setForm({
      label: account.label,
      tokens: '',
      timezone: account.timezone,
      daily_limit: account.daily_limit,
      weekly_limit: account.weekly_limit,
      window_start_hour: account.window_start_hour,
      window_end_hour: account.window_end_hour,
      skip_weekends: account.skip_weekends,
      min_delay_seconds: account.min_delay_seconds,
      max_delay_seconds: account.max_delay_seconds,
    })
  }

  if (!accounts) return <div className="spinner">Loading…</div>

  return (
    <>
      <div className="page-head">
        <div>
          <h1>LinkedIn accounts</h1>
          <p>Every account sends on its own schedule and against its own daily cap.</p>
        </div>
        <button
          className="btn-primary"
          onClick={() => {
            setEditing(null)
            setForm(EMPTY)
            setShowForm((value) => !value)
          }}
        >
          {showForm && !editing ? 'Cancel' : 'Add account'}
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {showForm && (
        <form className="card" onSubmit={submit} style={{ marginBottom: 16 }}>
          <div className="card-head">
            <h2>{editing ? 'Edit account' : 'New account'}</h2>
          </div>
          <div className="field">
            <label htmlFor="label">Name</label>
            <input
              id="label"
              value={form.label}
              onChange={(event) => update('label', event.target.value)}
              placeholder="Julio – Kalungi"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="tokens">
              LinkedIn tokens {editing && <span className="muted">(leave empty to keep the current ones)</span>}
            </label>
            <textarea
              id="tokens"
              value={form.tokens}
              onChange={(event) => update('tokens', event.target.value)}
              placeholder={TOKENS_PLACEHOLDER}
              required={!editing}
            />
            <div className="field-hint">
              The same dictionary the Colab notebook uses. They are encrypted before being stored, and
              the session is checked right away.
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="daily">Requests per day</label>
              <input
                id="daily"
                type="number"
                min="1"
                max="80"
                value={form.daily_limit}
                onChange={(event) => update('daily_limit', Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="weekly">Requests per week</label>
              <input
                id="weekly"
                type="number"
                min="1"
                max="200"
                value={form.weekly_limit}
                onChange={(event) => update('weekly_limit', Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="tz">Time zone</label>
              <select id="tz" value={form.timezone} onChange={(event) => update('timezone', event.target.value)}>
                {TIMEZONES.map((zone) => (
                  <option key={zone} value={zone}>
                    {zone}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="from">Send from (hour)</label>
              <input
                id="from"
                type="number"
                min="0"
                max="23"
                value={form.window_start_hour}
                onChange={(event) => update('window_start_hour', Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="to">Send until (hour)</label>
              <input
                id="to"
                type="number"
                min="0"
                max="23"
                value={form.window_end_hour}
                onChange={(event) => update('window_end_hour', Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="min">Min gap (seconds)</label>
              <input
                id="min"
                type="number"
                min="10"
                value={form.min_delay_seconds}
                onChange={(event) => update('min_delay_seconds', Number(event.target.value))}
              />
            </div>
            <div className="field">
              <label htmlFor="max">Max gap (seconds)</label>
              <input
                id="max"
                type="number"
                min="10"
                value={form.max_delay_seconds}
                onChange={(event) => update('max_delay_seconds', Number(event.target.value))}
              />
            </div>
          </div>
          <div className="field">
            <label className="check">
              <input
                type="checkbox"
                checked={form.skip_weekends}
                onChange={(event) => update('skip_weekends', event.target.checked)}
              />
              Don&apos;t send on weekends
            </label>
          </div>
          <div className="btn-row">
            <button className="btn-primary" type="submit" disabled={busy}>
              {busy ? 'Saving…' : editing ? 'Save changes' : 'Add account'}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowForm(false)
                setEditing(null)
                setForm(EMPTY)
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {accounts.length === 0 && !showForm && (
        <div className="card">
          <p className="muted">
            No account yet. Add one with the tokens you already use in the notebook and the worker will
            start sending within its window.
          </p>
        </div>
      )}

      {accounts.map((account) => (
        <div className="card" key={account.id}>
          <div className="card-head">
            <div>
              <h2>{account.label}</h2>
              <p>
                {account.linkedin_name || 'LinkedIn account'} · {account.owner_name} · {account.timezone}
              </p>
            </div>
            <Badge status={account.status} />
          </div>

          {account.status === 'needs_reauth' && (
            <div className="alert alert-error">
              {account.status_detail || 'LinkedIn rejected the session.'} Paste fresh tokens to resume.
            </div>
          )}
          {account.status === 'cooldown' && (
            <div className="alert alert-warning">
              Cooling down after a rate limit. Resumes {dateTime(account.next_send_at)}.
            </div>
          )}

          <div className="tiles" style={{ marginBottom: 14 }}>
            <div className="tile">
              <div className="tile-label">Today</div>
              <div className="tile-value">
                {thousands(account.sent_today)}
                <span className="muted" style={{ fontSize: 14, fontWeight: 400 }}>
                  {' '}
                  / {account.daily_limit}
                </span>
              </div>
              <div className="progress" style={{ marginTop: 6 }}>
                <div style={{ width: `${Math.min(100, (account.sent_today / account.daily_limit) * 100)}%` }} />
              </div>
            </div>
            <div className="tile">
              <div className="tile-label">This week</div>
              <div className="tile-value">
                {thousands(account.sent_this_week)}
                <span className="muted" style={{ fontSize: 14, fontWeight: 400 }}>
                  {' '}
                  / {account.weekly_limit}
                </span>
              </div>
              <div className="progress" style={{ marginTop: 6 }}>
                <div style={{ width: `${Math.min(100, (account.sent_this_week / account.weekly_limit) * 100)}%` }} />
              </div>
            </div>
            <div className="tile">
              <div className="tile-label">Queued</div>
              <div className="tile-value">{thousands(account.pending)}</div>
              <div className="tile-note">
                {account.in_window ? 'inside the send window' : 'outside the window right now'}
              </div>
            </div>
            <div className="tile">
              <div className="tile-label">Next request</div>
              <div className="tile-value" style={{ fontSize: 16, marginTop: 6 }}>
                {account.pending === 0
                  ? 'nothing queued'
                  : account.next_send_at
                    ? dateTime(account.next_send_at)
                    : account.in_window
                      ? 'within a minute'
                      : 'when the window opens'}
              </div>
              <div className="tile-note">
                {account.window_start_hour}:00–{account.window_end_hour}:00
                {account.skip_weekends ? ', weekdays' : ', every day'}
              </div>
            </div>
          </div>

          <div className="btn-row">
            <button className="btn-small" onClick={() => act(account.id, 'test')}>
              Test session
            </button>
            {account.status === 'paused' ? (
              <button className="btn-small" onClick={() => act(account.id, 'resume')}>
                Resume
              </button>
            ) : (
              <button className="btn-small" onClick={() => act(account.id, 'pause')}>
                Pause
              </button>
            )}
            <button className="btn-small" onClick={() => startEdit(account)}>
              Edit
            </button>
            <button className="btn-small btn-danger" onClick={() => act(account.id, 'delete')}>
              Delete
            </button>
            <span className="small muted">
              {account.last_checked_at ? `Checked ${dateTime(account.last_checked_at)}` : 'Never checked'}
            </span>
          </div>
        </div>
      ))}
    </>
  )
}
