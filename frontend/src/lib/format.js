export function compact(value) {
  if (value === null || value === undefined) return '–'
  if (value < 1000) return String(value)
  if (value < 1000000) return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}K`
  return `${(value / 1000000).toFixed(1)}M`
}

export function thousands(value) {
  if (value === null || value === undefined) return '–'
  return value.toLocaleString('en-US')
}

export function dateTime(value) {
  if (!value) return '–'
  return new Date(value).toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function relative(value) {
  if (!value) return '–'
  const diff = (new Date(value) - Date.now()) / 1000
  const units = [
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
  ]
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  for (const [unit, seconds] of units) {
    if (Math.abs(diff) >= seconds) return formatter.format(Math.round(diff / seconds), unit)
  }
  return formatter.format(Math.round(diff), 'second')
}

export const STATUS_TONE = {
  active: 'good',
  running: 'info',
  sent: 'good',
  completed: 'good',
  paused: 'warning',
  pending: 'info',
  cooldown: 'warning',
  skipped: 'warning',
  needs_reauth: 'critical',
  failed: 'critical',
  cancelled: 'critical',
}

export const STATUS_LABEL = {
  active: 'Active',
  running: 'Running',
  paused: 'Paused',
  completed: 'Completed',
  cancelled: 'Cancelled',
  cooldown: 'Cooling down',
  needs_reauth: 'Needs new tokens',
  pending: 'Queued',
  sent: 'Sent',
  failed: 'Failed',
  skipped: 'Skipped',
}
