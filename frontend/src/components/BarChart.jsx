import { useState } from 'react'
import { thousands } from '../lib/format'

/**
 * Single-series column chart drawn by hand so the marks follow the spec:
 * <=24px bars, 4px rounded cap squared at the baseline, a 2px surface gap
 * between neighbours, hairline recessive gridlines, hover tooltip, and one
 * selective direct label on the tallest column. A single series carries no
 * legend - the card title says what is plotted.
 */
export default function BarChart({ data, unitLabel = 'sent', height = 220 }) {
  const [hovered, setHovered] = useState(null)

  if (!data || data.length === 0) {
    return <div className="empty-chart">Nothing to plot yet.</div>
  }

  const width = 760
  const padding = { top: 16, right: 12, bottom: 28, left: 40 }
  const innerWidth = width - padding.left - padding.right
  const innerHeight = height - padding.top - padding.bottom

  const rawMax = Math.max(...data.map((d) => d.value), 0)
  const niceMax = niceCeiling(rawMax)
  const ticks = tickValues(niceMax)
  const scaleY = (value) => innerHeight - (niceMax === 0 ? 0 : (value / niceMax) * innerHeight)

  const band = innerWidth / data.length
  const barWidth = Math.max(2, Math.min(24, band - 2)) // the 2px surface gap
  const maxIndex = data.reduce((best, d, i) => (d.value > data[best].value ? i : best), 0)
  const labelEvery = Math.ceil(data.length / 12)

  return (
    <div className="chart-wrap">
      <div className="chart">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Connection requests ${unitLabel} per period`}>
          <g className="chart-grid" transform={`translate(${padding.left}, ${padding.top})`}>
            {ticks.map((tick) => (
              <line key={tick} x1={0} x2={innerWidth} y1={scaleY(tick)} y2={scaleY(tick)} />
            ))}
          </g>
          <g className="chart-axis" transform={`translate(${padding.left}, ${padding.top})`}>
            {ticks.map((tick) => (
              <text key={tick} x={-8} y={scaleY(tick) + 4} textAnchor="end">
                {thousands(tick)}
              </text>
            ))}
          </g>

          <g transform={`translate(${padding.left}, ${padding.top})`}>
            {data.map((item, index) => {
              const barHeight = innerHeight - scaleY(item.value)
              const x = index * band + (band - barWidth) / 2
              const y = scaleY(item.value)
              const isActive = hovered === index
              return (
                <g
                  key={item.key || item.label}
                  className={`chart-band${isActive ? ' is-active' : ''}`}
                  onMouseEnter={() => setHovered(index)}
                  onMouseLeave={() => setHovered(null)}
                >
                  <rect
                    className="chart-hit"
                    x={index * band}
                    y={-padding.top}
                    width={band}
                    height={innerHeight + padding.top}
                    rx={4}
                  />
                  {item.value > 0 && (
                    <path
                      className={`chart-bar${isActive ? ' is-active' : ''}`}
                      d={columnPath(x, y, barWidth, barHeight)}
                    />
                  )}
                  {index === maxIndex && item.value > 0 && (
                    <text className="chart-label" x={x + barWidth / 2} y={y - 6} textAnchor="middle">
                      {thousands(item.value)}
                    </text>
                  )}
                </g>
              )
            })}
          </g>

          <g className="chart-axis" transform={`translate(${padding.left}, ${padding.top + innerHeight + 16})`}>
            {data.map((item, index) =>
              index % labelEvery === 0 || index === data.length - 1 ? (
                <text key={item.key || item.label} x={index * band + band / 2} y={0} textAnchor="middle">
                  {item.label}
                </text>
              ) : null,
            )}
          </g>
        </svg>
      </div>

      {hovered !== null && (
        <div
          className="tooltip"
          style={{
            left: `${((padding.left + hovered * band + band / 2) / width) * 100}%`,
            top: `${(padding.top + scaleY(data[hovered].value) - 10) / height * 100}%`,
          }}
        >
          <div className="tooltip-title">{data[hovered].tooltip || data[hovered].label}</div>
          <div className="tooltip-value">
            <span className="swatch" />
            {thousands(data[hovered].value)} {unitLabel}
          </div>
        </div>
      )}
    </div>
  )
}

function columnPath(x, y, width, height) {
  const radius = Math.min(4, width / 2, height)
  if (height <= radius) return `M${x},${y + height} h${width} v${-height} h${-width} Z`
  return [
    `M${x},${y + height}`,
    `V${y + radius}`,
    `Q${x},${y} ${x + radius},${y}`,
    `H${x + width - radius}`,
    `Q${x + width},${y} ${x + width},${y + radius}`,
    `V${y + height}`,
    'Z',
  ].join(' ')
}

function niceCeiling(value) {
  if (value <= 0) return 4
  const magnitude = 10 ** Math.floor(Math.log10(value))
  for (const step of [1, 2, 2.5, 5, 10]) {
    const candidate = step * magnitude
    if (candidate >= value) return Math.max(candidate, 4)
  }
  return magnitude * 10
}

function tickValues(max) {
  const count = 4
  return Array.from({ length: count + 1 }, (_, index) => Math.round((max / count) * index))
    .filter((value, index, all) => all.indexOf(value) === index)
}
