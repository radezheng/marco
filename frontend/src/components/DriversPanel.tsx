import React from 'react'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { HoverHelp } from './HoverHelp'
import { chartHelp } from '../helpText'

type Regime = {
  date: string
  regime: 'A' | 'B' | 'C'
  risk_score: number
  template_name: string
  drivers: Record<string, unknown>
}

const keyName: Record<string, string> = {
  synthetic_liquidity: '合成流动性',
  credit_spread: '信用利差(代理)',
  funding_stress: '资金压力(代理)',
  treasury_vol: '美债波动(代理)',
  vix_structure: 'VIX结构',
  vix_level: 'VIX水平',
  usd_strength: '美元强弱(官方TWI)'
}

function dotClass(state: string) {
  if (state === 'G' || state === 'Y' || state === 'R' || state === 'U') return state
  return 'U'
}

export function DriversPanel(props: { regime: Regime | null | undefined }) {
  const core = (props.regime?.drivers as any)?.core as Record<string, string> | undefined

  const entries = core ? Object.entries(core) : []
  const greens = entries.filter(([, s]) => s === 'G').length
  const yellows = entries.filter(([, s]) => s === 'Y').length
  const reds = entries.filter(([, s]) => s === 'R').length

  const chartData = [
    { name: '🟢', v: greens },
    { name: '🟡', v: yellows },
    { name: '🔴', v: reds }
  ]

  const help = chartHelp.drivers_core

  return (
    <div className="card">
      <div className="hstack" style={{ justifyContent: 'space-between' }}>
        <HoverHelp title={help.title} body={help.body} delayMs={2000}>
          <div className="muted" style={{ cursor: 'help' }}>Drivers（核心信号）</div>
        </HoverHelp>
        <div className="muted">{props.regime ? `core=${entries.length}` : '—'}</div>
      </div>

      {props.regime && entries.length > 0 ? (
        <>
          <div className="grid" style={{ marginTop: 10, gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 }}>
            {entries.map(([k, s]) => (
              <div key={k} className="badge" style={{ justifyContent: 'space-between' }}>
                <span className="hstack" style={{ gap: 8 }}>
                  <span className={`dot ${dotClass(s)}`} />
                  <span>{keyName[k] ?? k}</span>
                </span>
                <span style={{ fontVariantNumeric: 'tabular-nums' }}>{s}</span>
              </div>
            ))}
          </div>

          <div style={{ width: '100%', height: 130, marginTop: 10 }}>
            <ResponsiveContainer>
              <BarChart data={chartData} margin={{ left: 6, right: 6, top: 8, bottom: 0 }}>
                <XAxis dataKey="name" tick={{ fill: 'rgba(232,238,252,0.72)', fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fill: 'rgba(232,238,252,0.72)', fontSize: 11 }} width={30} />
                <Tooltip
                  contentStyle={{
                    background: 'rgba(11,18,32,0.95)',
                    border: '1px solid rgba(255,255,255,0.12)',
                    borderRadius: 10,
                    color: '#e8eefc'
                  }}
                />
                <Bar dataKey="v" fill="rgba(148,163,184,0.85)" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <details style={{ marginTop: 10 }}>
            <summary className="muted">查看 Raw drivers JSON</summary>
            <pre style={{ marginTop: 8 }}>{JSON.stringify(props.regime.drivers, null, 2)}</pre>
          </details>
        </>
      ) : (
        <div className="muted" style={{ marginTop: 10 }}>—</div>
      )}
    </div>
  )
}
