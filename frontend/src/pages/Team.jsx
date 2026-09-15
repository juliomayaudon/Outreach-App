import { useEffect, useState } from 'react'
import { api } from '../lib/api'

export default function Team() {
  const [users, setUsers] = useState(null)
  const [form, setForm] = useState({ email: '', name: '', password: '', role: 'member' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    try {
      setUsers(await api.users())
    } catch (problem) {
      setError(problem.message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.createUser(form)
      setForm({ email: '', name: '', password: '', role: 'member' })
      await load()
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  async function toggle(user) {
    setError('')
    try {
      await api.updateUser(user.id, { is_active: !user.is_active })
      await load()
    } catch (problem) {
      setError(problem.message)
    }
  }

  if (!users) return <div className="spinner">Loading…</div>

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Team</h1>
          <p>Members only see their own accounts and campaigns. Admins see everyone&apos;s.</p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="card">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>{user.name || '—'}</td>
                  <td className="small">{user.email}</td>
                  <td className="small">{user.role === 'admin' ? 'Admin' : 'Member'}</td>
                  <td className="small">{user.is_active ? 'Active' : 'Disabled'}</td>
                  <td>
                    <button className="btn-small" onClick={() => toggle(user)}>
                      {user.is_active ? 'Disable' : 'Enable'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <form className="card" onSubmit={submit}>
        <div className="card-head">
          <h2>Add someone</h2>
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="name">Name</label>
            <input
              id="name"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={form.email}
              onChange={(event) => setForm({ ...form, email: event.target.value })}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Temporary password</label>
            <input
              id="password"
              value={form.password}
              minLength={8}
              onChange={(event) => setForm({ ...form, password: event.target.value })}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="role">Role</label>
            <select
              id="role"
              value={form.role}
              onChange={(event) => setForm({ ...form, role: event.target.value })}
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
          </div>
        </div>
        <button className="btn-primary" type="submit" disabled={busy}>
          {busy ? 'Adding…' : 'Add member'}
        </button>
      </form>
    </>
  )
}
