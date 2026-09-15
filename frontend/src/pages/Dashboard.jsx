import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../App'
import Badge from '../components/Badge'
import BarChart from '../components/BarChart'
import StatTile from '../components/StatTile'
import { api } from '../lib/api'
import { dateTime, thousands } from '../lib/format'

const RANGES = [
  { key: 'daily', label: 'Last 30 days' },
  { key: 'weekly', label: 'Last 12 weeks' },
  { key: 'monthly', label: 'Last 12 months' },
]

export default function Dashboard() {
  const { user } = useAuth()
  const [scope, setScope] = useState('me')
  const [range, setRange] = useState('weekly')
  const [view, setView] = useState('chart')
  const [stats, setStats] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    api
      .stats(scope)
      .then((data) => !cancelled && setStats(data))
      .catch((problem) => !cancelled && setError(problem.message))
    return () => {
      cancelled = true
    }
  }, [scope])

  const series = useMemo(() => {
    if (!stats) return []
    if (range === 'daily') {
      return stats.daily.map((point) => ({
        key: point.date,
        label: point.label,
        value: point.sent,
        tooltip: point.label,
      }))
    }
    const source = range === 'weekly' ? stats.weekly : stats.monthly
    return source.map((point) => ({
      key: point.period,
      label: point.label,
      value: point.sent,
      tooltip: range === 'weekly' ? `Week of ${point.label}` : point.label,
    }))
  }, [stats, range])

  if (error) return <div className="alert alert-error">{error}</div>
  if (!stats) return <div className="spinner">Loading…</div>

  const { totals, by_status: byStatus } = stats
  const rangeLabel = RANGES.find((option) => option.key === range).label.toLowerCase()

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p>Connection requests sent from your LinkedIn accounts, in {stats.timezone}.</p>
        </div>
        {user.role === 'admin' && (
          <div className="toggle-group">
            <button className={scope === 'me' ? 'active' : ''} onClick={() => setScope('me')}>
              Mine
            </button>
            <button className={scope === 'team' ? 'active' : ''} onClick={() => setScope('team')}>
              Whole team
            </button>
          </div>
        )}
      </div>

      <div className="tiles" style={{ marginBottom: 16 }}>
        <StatTile
          hero
          label="Sent this month"
          value={totals.this_month}
          note={`${thousands(totals.today)} today · ${thousands(totals.this_week)} this week`}
        />
        <StatTile label="Last 7 days" value={totals.last_7_days} />
        <StatTile label="Last 30 days" value={totals.last_30_days} />
        <StatTile label="All time" value={totals.all_time} />
        <StatTile
          label="Still queued"
          value={totals.pending}
          note={byStatus.failed ? `${thousands(byStatus.failed)} failed` : 'nothing failed'}
        />
        <StatTile
          label="Accepted by LinkedIn"
          value={stats.success_rate === null ? '–' : `${stats.success_rate}%`}
          note="of attempts that got an answer"
        />
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <h2>Connection requests sent</h2>
            <p>{RANGES.find((option) => option.key === range).label}</p>
          </div>
          <div className="btn-row">
            <div className="toggle-group">
              {RANGES.map((option) => (
                <button
                  key={option.key}
                  className={range === option.key ? 'active' : ''}
                  onClick={() => setRange(option.key)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <div className="toggle-group">
              <button className={view === 'chart' ? 'active' : ''} onClick={() => setView('chart')}>
                Chart
              </button>
              <button className={view === 'table' ? 'active' : ''} onClick={() => setView('table')}>
                Table
              </button>
            </div>
          </div>
        </div>

        {view === 'chart' ? (
          <BarChart data={series} unitLabel="sent" />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Period</th>
                  <th className="num">Sent</th>
                </tr>
              </thead>
              <tbody>
                {series.map((point) => (
                  <tr key={point.key}>
                    <td>{point.tooltip}</td>
                    <td className="num">{thousands(point.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="small muted" style={{ marginTop: 10 }}>
          Counts every request the worker managed to send in the {rangeLabel}.
        </div>
      </div>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <div className="card">
          <div className="card-head">
            <h2>By LinkedIn account</h2>
            <Link to="/accounts" className="small">
              Manage
            </Link>
          </div>
          {stats.by_account.length === 0 ? (
            <p className="muted small">
              No LinkedIn account connected yet. <Link to="/accounts">Add one</Link> to start sending.
            </p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Account</th>
                    <th>Status</th>
                    <th className="num">7 days</th>
                    <th className="num">Total</th>
                    <th className="num">Queued</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.by_account.map((account) => (
                    <tr key={account.account_id}>
                      <td>{account.label}</td>
                      <td>
                        <Badge status={account.status} />
                      </td>
                      <td className="num">{thousands(account.sent_7d)}</td>
                      <td className="num">{thousands(account.sent)}</td>
                      <td className="num">{thousands(account.pending)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Latest sends</h2>
            <Link to="/campaigns" className="small">
              All campaigns
            </Link>
          </div>
          {stats.recent.length === 0 ? (
            <p className="muted small">Nothing sent yet.</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Contact</th>
                    <th>Campaign</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.recent.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.full_name}
                        {row.company && <div className="small muted">{row.company}</div>}
                      </td>
                      <td className="small">{row.campaign}</td>
                      <td className="small muted">{dateTime(row.sent_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
