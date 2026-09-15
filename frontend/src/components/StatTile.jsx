import { thousands } from '../lib/format'

export default function StatTile({ label, value, note, hero = false }) {
  return (
    <div className={`tile${hero ? ' hero' : ''}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{typeof value === 'number' ? thousands(value) : value}</div>
      {note && <div className="tile-note">{note}</div>}
    </div>
  )
}
