import { STATUS_LABEL, STATUS_TONE } from '../lib/format'

export default function Badge({ status, children }) {
  const tone = STATUS_TONE[status] || 'info'
  return <span className={`badge badge-${tone}`}>{children || STATUS_LABEL[status] || status}</span>
}
