import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../App'
import Badge from '../components/Badge'
import { api } from '../lib/api'
import { dateTime, thousands } from '../lib/format'

export default function Campaigns() {
  const { user } = useAuth()
  const [scope, setScope] = useState('me')
  const [campaigns, setCampaigns] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.campaigns(scope).then(setCampaigns).catch((problem) => setError(problem.message))
  }, [scope])

  if (error) return <div className="alert alert-error">{error}</div>
  if (!campaigns) return <div className="spinner">Loading…</div>

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Campaigns</h1>
          <p>Each campaign is a list of profiles queued against one LinkedIn account.</p>
        </div>
        <div className="btn-row">
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
          <Link to="/campaigns/new">
            <button className="btn-primary">New campaign</button>
          </Link>
        </div>
      </div>

      {campaigns.length === 0 ? (
        <div className="card">
          <p className="muted">
            Nothing here yet. <Link to="/campaigns/new">Upload a CSV or point at a Google Sheet</Link> to
            queue your first list.
          </p>
        </div>
      ) : (
        <div className="card">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Campaign</th>
                  <th>Account</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th className="num">Sent</th>
                  <th className="num">Queued</th>
                  <th className="num">Failed</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((campaign) => {
                  const done = campaign.total - campaign.pending
                  const percent = campaign.total ? Math.round((done / campaign.total) * 100) : 0
                  return (
                    <tr key={campaign.id}>
                      <td>
                        <Link to={`/campaigns/${campaign.id}`}>{campaign.name}</Link>
                        <div className="small muted">
                          {campaign.source_type === 'sheet' ? 'Google Sheet' : campaign.source_name}
                        </div>
                      </td>
                      <td className="small">{campaign.account_label}</td>
                      <td>
                        <Badge status={campaign.status} />
                      </td>
                      <td style={{ minWidth: 120 }}>
                        <div className="progress">
                          <div style={{ width: `${percent}%` }} />
                        </div>
                        <div className="small muted">{percent}%</div>
                      </td>
                      <td className="num">{thousands(campaign.sent)}</td>
                      <td className="num">{thousands(campaign.pending)}</td>
                      <td className="num">{thousands(campaign.failed)}</td>
                      <td className="small muted">{dateTime(campaign.created_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}
