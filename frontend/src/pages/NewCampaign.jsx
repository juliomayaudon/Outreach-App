import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { thousands } from '../lib/format'

const FIELDS = [
  { key: 'vmid', label: 'vmid (required)', required: true },
  { key: 'full_name', label: 'Full name' },
  { key: 'first_name', label: 'First name' },
  { key: 'company', label: 'Company' },
  { key: 'title', label: 'Job title' },
  { key: 'message', label: 'Note (per row)' },
]

export default function NewCampaign() {
  const navigate = useNavigate()
  const [accounts, setAccounts] = useState([])
  const [sheetConfig, setSheetConfig] = useState({ enabled: false, service_account_email: '', problem: null })
  const [source, setSource] = useState('csv')
  const [file, setFile] = useState(null)
  const [sheetUrl, setSheetUrl] = useState('')
  const [sheetTab, setSheetTab] = useState('')
  const [preview, setPreview] = useState(null)
  const [mapping, setMapping] = useState({})
  const [name, setName] = useState('')
  const [accountId, setAccountId] = useState('')
  const [noteTemplate, setNoteTemplate] = useState('')
  const [writeBack, setWriteBack] = useState(true)
  const [resultColumn, setResultColumn] = useState('Result')
  const [startNow, setStartNow] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    api.accounts().then((list) => {
      setAccounts(list)
      const usable = list.find((account) => account.status !== 'needs_reauth')
      if (usable) setAccountId(String(usable.id))
    })
    api.sheetConfig().then(setSheetConfig).catch(() => {})
  }, [])

  async function loadPreview(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const data = source === 'csv' ? await api.previewCsv(file) : await api.previewSheet(sheetUrl, sheetTab)
      setPreview(data)
      setMapping(data.suggested_mapping)
      if (!name) setName(source === 'csv' ? file.name.replace(/\.csv$/i, '') : sheetTab || 'Google Sheet')
      if (source === 'sheet' && !sheetTab && data.tabs.length) setSheetTab(data.tabs[0])
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const payload =
        source === 'csv'
          ? await api.createCsvCampaign({
              file,
              name,
              accountId: Number(accountId),
              mapping,
              noteTemplate,
              startNow,
            })
          : await api.createSheetCampaign({
              name,
              account_id: Number(accountId),
              url: sheetUrl,
              tab: sheetTab,
              mapping,
              note_template: noteTemplate,
              result_column: resultColumn,
              write_back: writeBack,
              start_now: startNow,
            })
      setResult(payload)
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    return (
      <>
        <div className="page-head">
          <div>
            <h1>{result.campaign.name}</h1>
            <p>
              {thousands(result.queued)} profiles queued
              {result.skipped > 0 && ` · ${thousands(result.skipped)} skipped`}
            </p>
          </div>
        </div>
        <div className="card">
          <p>
            The worker will start sending inside the account&apos;s window, respecting its daily cap.
            You can follow it from the campaign page.
          </p>
          {result.skipped_examples.length > 0 && (
            <>
              <h3 style={{ marginTop: 16, marginBottom: 8 }}>Rows that were skipped</h3>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Value</th>
                      <th>Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.skipped_examples.map((row, index) => (
                      <tr key={index}>
                        <td className="mono">{row.value || '(empty)'}</td>
                        <td className="small muted">{row.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <div className="btn-row" style={{ marginTop: 16 }}>
            <button className="btn-primary" onClick={() => navigate(`/campaigns/${result.campaign.id}`)}>
              Open campaign
            </button>
            <Link to="/campaigns/new" onClick={() => window.location.reload()}>
              <button>Queue another list</button>
            </Link>
          </div>
        </div>
      </>
    )
  }

  const usableAccounts = accounts.filter((account) => account.status !== 'needs_reauth')

  return (
    <>
      <div className="page-head">
        <div>
          <h1>New campaign</h1>
          <p>Upload a CSV or point at a Google Sheet, map the columns, and queue the list.</p>
        </div>
      </div>

      <div className="steps">
        <span className={`step${!preview ? ' active' : ''}`}>1. Source</span>
        <span className={`step${preview ? ' active' : ''}`}>2. Columns and schedule</span>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {accounts.length === 0 && (
        <div className="alert alert-warning">
          You need a LinkedIn account first. <Link to="/accounts">Add one here.</Link>
        </div>
      )}

      {!preview ? (
        <form className="card" onSubmit={loadPreview}>
          <div className="toggle-group" style={{ marginBottom: 16 }}>
            <button type="button" className={source === 'csv' ? 'active' : ''} onClick={() => setSource('csv')}>
              CSV file
            </button>
            <button type="button" className={source === 'sheet' ? 'active' : ''} onClick={() => setSource('sheet')}>
              Google Sheet
            </button>
          </div>

          {source === 'csv' ? (
            <div className="field">
              <label htmlFor="file">CSV file</label>
              <input
                id="file"
                type="file"
                accept=".csv,text/csv"
                onChange={(event) => setFile(event.target.files[0])}
                required
              />
              <div className="field-hint">
                One row per profile, with a header row. It needs at least a column of vmids.
              </div>
            </div>
          ) : (
            <>
              {!sheetConfig.enabled && (
                <div className="alert alert-warning">
                  Google Sheets is not configured on the server: set{' '}
                  <span className="mono">GOOGLE_SERVICE_ACCOUNT_JSON</span> to the service account
                  key. Every sheet you use then has to be shared as <strong>Editor</strong> with
                  that account, because the campaign writes a results column back into it.
                </div>
              )}
              {sheetConfig.problem && (
                <div className="alert alert-error">{sheetConfig.problem}</div>
              )}
              <div className="field">
                <label htmlFor="url">Spreadsheet URL</label>
                <input
                  id="url"
                  value={sheetUrl}
                  onChange={(event) => setSheetUrl(event.target.value)}
                  placeholder="https://docs.google.com/spreadsheets/d/…"
                  required
                />
                {sheetConfig.service_account_email && !sheetConfig.problem && (
                  <div className="alert alert-info" style={{ marginTop: 8, marginBottom: 0 }}>
                    Share the sheet as <strong>Editor</strong> with{' '}
                    <span className="mono">{sheetConfig.service_account_email}</span>. Without it
                    Google answers “spreadsheet not found”, and Editor rather than Viewer because
                    the results column is written back into the sheet.
                  </div>
                )}
              </div>
              <div className="field">
                <label htmlFor="tab">Tab</label>
                <input
                  id="tab"
                  value={sheetTab}
                  onChange={(event) => setSheetTab(event.target.value)}
                  placeholder="CR (leave empty for the first tab)"
                />
              </div>
            </>
          )}

          <button className="btn-primary" type="submit" disabled={busy}>
            {busy ? 'Reading…' : 'Read the list'}
          </button>
        </form>
      ) : (
        <form className="card" onSubmit={submit}>
          <div className="card-head">
            <div>
              <h2>{thousands(preview.total_rows)} rows found</h2>
              <p>Check the column mapping before queueing.</p>
            </div>
            <button type="button" className="btn-small" onClick={() => setPreview(null)}>
              Change source
            </button>
          </div>

          <div className="table-scroll" style={{ marginBottom: 18 }}>
            <table className="preview-table">
              <thead>
                <tr>
                  {preview.headers.map((header) => (
                    <th key={header}>{header}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.sample.map((row, index) => (
                  <tr key={index}>
                    {preview.headers.map((header) => (
                      <td key={header}>{row[header]}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3 style={{ marginBottom: 10 }}>Columns</h3>
          <div className="mapping-grid" style={{ marginBottom: 18 }}>
            {FIELDS.map((field) => (
              <div className="field" key={field.key}>
                <label htmlFor={field.key}>{field.label}</label>
                <select
                  id={field.key}
                  value={mapping[field.key] || ''}
                  required={field.required}
                  onChange={(event) => setMapping({ ...mapping, [field.key]: event.target.value })}
                >
                  <option value="">—</option>
                  {preview.headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>

          <div className="field-row">
            <div className="field">
              <label htmlFor="name">Campaign name</label>
              <input id="name" value={name} onChange={(event) => setName(event.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="account">Send from</label>
              <select
                id="account"
                value={accountId}
                onChange={(event) => setAccountId(event.target.value)}
                required
              >
                <option value="">Pick an account</option>
                {usableAccounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.label} ({account.daily_limit}/day)
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="field">
            <label htmlFor="note">Note (optional)</label>
            <textarea
              id="note"
              value={noteTemplate}
              onChange={(event) => setNoteTemplate(event.target.value)}
              placeholder="Hi {first_name}, saw you lead marketing at {company} — would love to connect."
            />
            <div className="field-hint">
              Up to 300 characters. Placeholders: {'{first_name}'}, {'{full_name}'}, {'{company}'},{' '}
              {'{title}'}. A per-row note column wins over this template. Leave empty to send without a note.
            </div>
          </div>

          {source === 'sheet' && (
            <div className="field-row">
              <div className="field">
                <label htmlFor="resultColumn">Write results into</label>
                <input
                  id="resultColumn"
                  value={resultColumn}
                  onChange={(event) => setResultColumn(event.target.value)}
                />
              </div>
              <div className="field" style={{ alignSelf: 'end' }}>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={writeBack}
                    onChange={(event) => setWriteBack(event.target.checked)}
                  />
                  Write each result back into the sheet
                </label>
              </div>
            </div>
          )}

          <div className="field">
            <label className="check">
              <input type="checkbox" checked={startNow} onChange={(event) => setStartNow(event.target.checked)} />
              Start sending right away (otherwise it stays paused)
            </label>
          </div>

          <button className="btn-primary" type="submit" disabled={busy || !accountId}>
            {busy ? 'Queueing…' : 'Queue the list'}
          </button>
        </form>
      )}
    </>
  )
}
