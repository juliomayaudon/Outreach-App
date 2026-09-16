const BASE = import.meta.env.VITE_API_BASE || ''

async function request(path, { method = 'GET', body, form, signal } = {}) {
  const options = { method, credentials: 'include', headers: {}, signal }
  if (form) {
    options.body = form
  } else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }

  const response = await fetch(BASE + path, options)
  if (response.status === 204) return null
  const text = await response.text()
  let payload = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }
  if (!response.ok) {
    const detail =
      (payload && payload.detail) ||
      (typeof payload === 'string' && payload) ||
      `Request failed (${response.status})`
    const error = new Error(Array.isArray(detail) ? detail.map((d) => d.msg).join(', ') : detail)
    error.status = response.status
    throw error
  }
  return payload
}

export const api = {
  me: () => request('/api/auth/me'),
  authConfig: () => request('/api/auth/config'),
  login: (email, password) => request('/api/auth/login', { method: 'POST', body: { email, password } }),
  logout: () => request('/api/auth/logout', { method: 'POST' }),

  users: () => request('/api/users'),
  createUser: (body) => request('/api/users', { method: 'POST', body }),
  updateUser: (id, body) => request(`/api/users/${id}`, { method: 'PATCH', body }),

  accounts: () => request('/api/accounts'),
  createAccount: (body) => request('/api/accounts', { method: 'POST', body }),
  updateAccount: (id, body) => request(`/api/accounts/${id}`, { method: 'PATCH', body }),
  testAccount: (id) => request(`/api/accounts/${id}/test`, { method: 'POST' }),
  deleteAccount: (id) => request(`/api/accounts/${id}`, { method: 'DELETE' }),

  campaigns: (scope = 'me') => request(`/api/campaigns?scope=${scope}`),
  campaign: (id) => request(`/api/campaigns/${id}`),
  campaignRows: (id, { status = '', limit = 100, offset = 0 } = {}) =>
    request(`/api/campaigns/${id}/rows?status=${status}&limit=${limit}&offset=${offset}`),
  campaignAction: (id, action) => request(`/api/campaigns/${id}/status?action=${action}`, { method: 'POST' }),
  retryFailed: (id) => request(`/api/campaigns/${id}/retry-failed`, { method: 'POST' }),
  deleteCampaign: (id) => request(`/api/campaigns/${id}`, { method: 'DELETE' }),
  exportUrl: (id) => `${BASE}/api/campaigns/${id}/export`,

  sheetConfig: () => request('/api/sources/sheet/config'),
  previewCsv: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/api/sources/csv/preview', { method: 'POST', form })
  },
  previewSheet: (url, tab) => request('/api/sources/sheet/preview', { method: 'POST', body: { url, tab } }),
  createCsvCampaign: ({ file, name, accountId, mapping, noteTemplate, startNow }) => {
    const form = new FormData()
    form.append('file', file)
    form.append('name', name)
    form.append('account_id', String(accountId))
    form.append('mapping', JSON.stringify(mapping))
    form.append('note_template', noteTemplate || '')
    form.append('start_now', startNow ? 'true' : 'false')
    return request('/api/campaigns/csv', { method: 'POST', form })
  },
  createSheetCampaign: (body) => request('/api/campaigns/sheet', { method: 'POST', body }),

  stats: (scope = 'me') => request(`/api/stats/overview?scope=${scope}`),
}
