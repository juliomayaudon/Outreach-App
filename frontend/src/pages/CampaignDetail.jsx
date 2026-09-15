import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import Badge from '../components/Badge'
import StatTile from '../components/StatTile'
import { api } from '../lib/api'
import { dateTime, thousands } from '../lib/format'

const FILTERS = [
  { key: '', label: 'All' },
  { key: 'pending', label: 'Queued' },
  { key: 'sent', label: 'Sent' },
  { key: 'failed', label: 'Failed' },
  { key: 'skipped', label: 'Skipped' },
]

export default function CampaignDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [campaign, setCampaign] = useState(null)
  const [rows, setRows] = useState([])
  const [filter, setFilter] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const [detail, list] = await Promise.all([api.campaign(id), api.campaignRows(id, { status: filter })])
      setCampaign(detail)
      setRows(list)
    } catch (problem) {
      setError(problem.message)
    }
  }, [id, filter])

  useEffect(() => {
    load()
    const timer = setInterval(load, 20000) // the worker keeps moving while you watch
    return () => clearInterval(timer)
  }, [load])

  async function act(action) {
    setError('')
    try {
      if (action === 'delete') {
        if (!window.confirm('Delete this campaign and everything queued in it?')) return
        await api.deleteCampaign(id)
        navigate('/campaigns')
        return
      }
      if (action === 'retry') await api.retryFailed(id)
      else await api.campaignAction(id, action)
      await load()
    } catch (problem) {
      setError(problem.message)
    }
  }

  if (error) return <div className="alert alert-error">{error}</div>
  if (!campaign) return <div className="spinner">Loading…</div>

  const done = campaign.total - campaign.pending
  const percent = campaign.total ? Math.round((done / campaign.total) * 100) : 0

  return (
    <>
      <div className="page-head">
        <div>
          <div className="small muted">
            <Link to="/campaigns">Campaigns</Link>
          </div>
          <h1>{campaign.name}</h1>
          <p>
            {campaign.account_label} · {campaign.source_type === 'sheet' ? 'Google Sheet' : campaign.source_name} ·
            created {dateTime(campaign.created_at)}
          </p>
        </div>
        <Badge status={campaign.status} />
      </div>

      <div className="tiles" style={{ marginBottom: 16 }}>
        <StatTile label="Sent" value={campaign.sent} />
        <StatTile label="Queued" value={campaign.pending} />
        <StatTile label="Failed" value={campaign.failed} />
        <StatTile label="Skipped" value={campaign.skipped} />
        <StatTile label="Progress" value={`${percent}%`} note={`${thousands(done)} of ${thousands(campaign.total)}`} />
      </div>

      <div className="card">
        <div className="card-head">
          <div className="btn-row">
            {campaign.status === 'running' ? (
              <button className="btn-small" onClick={() => act('pause')}>
                Pause
              </button>
            ) : (
              campaign.status !== 'completed' && (
                <button className="btn-small btn-primary" onClick={() => act('resume')}>
                  Resume
                </button>
              )
            )}
            {campaign.failed > 0 && (
              <button className="btn-small" onClick={() => act('retry')}>
                Retry {campaign.failed} failed
              </button>
            )}
            <a href={api.exportUrl(campaign.id)}>
              <button className="btn-small">Export CSV</button>
            </a>
            <button className="btn-small btn-danger" onClick={() => act('delete')}>
              Delete
            </button>
          </div>
          <div className="toggle-group">
            {FILTERS.map((option) => (
              <button
                key={option.key}
                className={filter === option.key ? 'active' : ''}
                onClick={() => setFilter(option.key)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Contact</th>
                <th>vmid</th>
                <th>Status</th>
                <th>Detail</th>
                <th>Sent</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan="5" className="muted small">
                    No rows with this filter.
                  </td>
                </tr>
              )}
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    {row.full_name || <span className="muted">—</span>}
                    {row.company && <div className="small muted">{row.company}</div>}
                  </td>
                  <td className="mono">{row.profile_id || row.raw_value}</td>
                  <td>
                    <Badge status={row.status} />
                  </td>
                  <td className="small muted">
                    {row.error_code && <strong>{row.error_code}</strong>} {row.error_message}
                    {row.attempts > 1 && <div>{row.attempts} attempts</div>}
                  </td>
                  <td className="small muted">{row.sent_at ? dateTime(row.sent_at) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length >= 100 && (
          <div className="small muted" style={{ marginTop: 10 }}>
            Showing the first 100 rows — export the CSV for the full list.
          </div>
        )}
      </div>
    </>
  )
}
