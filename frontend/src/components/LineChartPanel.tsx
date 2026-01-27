import React from 'react'
import { api, SeriesPoint } from '../api'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { HoverHelp } from './HoverHelp'
import { chartHelp } from '../helpText'

export function LineChartPanel(props: {
  title: string
  seriesKey: string
  helpKey?: string
  asof?: string
  days?: number
  valueFactor?: number
  valueUnit?: string
  valueDigits?: number
}) {
  const [data, setData] = React.useState<SeriesPoint[]>([])
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let alive = true
    api
      .series(props.seriesKey, props.days ?? 365 * 5, props.asof)
      .then((d) => {
        if (!alive) return
        setData(d)
        setError(null)
      })
      .catch((e) => {
        if (!alive) return
        setError(String(e))
      })
    return () => {
      alive = false
    }
  }, [props.seriesKey, props.asof, props.days])

  const help = chartHelp[props.helpKey ?? props.seriesKey]
  const factor = props.valueFactor ?? 1
  const unit = props.valueUnit ? ` ${props.valueUnit}` : ''
  const digits = props.valueDigits ?? 2

  function fmtDate(d: unknown) {
    const s = typeof d === 'string' ? d : String(d)
    // Expect YYYY-MM-DD; show YYYY-MM for long series
    if (s.length >= 7) return s.slice(0, 7)
    return s
  }

  function fmt(v: unknown) {
    if (typeof v === 'number' && Number.isFinite(v)) {
      return `${(v * factor).toFixed(digits)}${unit}`
    }
    return String(v)
  }

  return (
    <div className="card">
      <div className="hstack" style={{ justifyContent: 'space-between' }}>
        {help ? (
          <HoverHelp title={help.title} body={help.body} delayMs={2000}>
            <div className="h1" style={{ cursor: 'help' }}>{props.title}</div>
          </HoverHelp>
        ) : (
          <div className="h1">{props.title}</div>
        )}
        <div className="muted">{props.seriesKey}{unit ? ` · ${props.valueUnit}` : ''}</div>
      </div>
      {error ? (
        <pre style={{ marginTop: 10 }}>{error}</pre>
      ) : (
        <div style={{ width: '100%', height: 270, marginTop: 10 }}>
          <ResponsiveContainer>
            <LineChart data={data} margin={{ left: 8, right: 8, top: 10, bottom: 18 }}>
              <XAxis
                dataKey="date"
                tick={{ fill: 'rgba(232,238,252,0.72)', fontSize: 11 }}
                tickFormatter={(v) => fmtDate(v)}
                interval="preserveStartEnd"
                minTickGap={18}
              />
              <YAxis
                tick={{ fill: 'rgba(232,238,252,0.72)', fontSize: 11 }}
                width={66}
                tickFormatter={(v) => fmt(v)}
              />
              <Tooltip
                contentStyle={{
                  background: 'rgba(11,18,32,0.95)',
                  border: '1px solid rgba(255,255,255,0.12)',
                  borderRadius: 10,
                  color: '#e8eefc'
                }}
                labelStyle={{ color: 'rgba(232,238,252,0.72)' }}
                labelFormatter={(l) => `date: ${String(l)}`}
                formatter={(v) => fmt(v)}
              />
              <Line type="monotone" dataKey="value" stroke="rgba(45,212,191,0.9)" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
