import React from 'react'
import type { IndicatorState } from '../api'
import { HoverHelp } from './HoverHelp'
import { chartHelp } from '../helpText'

const keyName: Record<string, string> = {
  synthetic_liquidity: '合成流动性（方向）',
  credit_spread: '信用压力（HY OAS 代理）',
  funding_stress: '资金压力（SOFR差值 代理）',
  treasury_vol: '美债波动（实现波动 代理）',
  vix_structure: 'VIX 结构（VIX-VXV）',
  vix_level: 'VIX 水平',
  usd_strength: '美元强弱（Fed TWI）'
}

function stateEmoji(s: string) {
  if (s === 'G') return '🟢'
  if (s === 'Y') return '🟡'
  if (s === 'R') return '🔴'
  return '⚪'
}

function num(x: unknown): number | null {
  if (typeof x === 'number' && Number.isFinite(x)) return x
  return null
}

function fmt(x: number | null, digits = 2) {
  if (x === null) return '—'
  return x.toFixed(digits)
}

function ProgressBar(props: { value: number; min: number; max: number; color: string }) {
  const clamped = Math.max(props.min, Math.min(props.max, props.value))
  const pct = ((clamped - props.min) / (props.max - props.min)) * 100
  return (
    <div style={{ width: '100%', background: 'rgba(255,255,255,0.10)', borderRadius: 999, overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: 10, background: props.color }} />
    </div>
  )
}

export function IndicatorCard(props: { item: IndicatorState }) {
  const it = props.item
  const d = it.details ?? {}

  // Common quantile format: {q1,q2,value}
  const q1 = num((d as any).q1)
  const q2 = num((d as any).q2)
  const value = num((d as any).value)

  // Liquidity direction format: {q_lo,q_hi,value,label}
  const qLo = num((d as any).q_lo)
  const qHi = num((d as any).q_hi)
  const label = typeof (d as any).label === 'string' ? ((d as any).label as string) : null

  // VIX structure: {slope,structure}
  const slope = num((d as any).slope)
  const structure = typeof (d as any).structure === 'string' ? ((d as any).structure as string) : null

  const title = keyName[it.indicator_key] ?? it.indicator_key
  const help = chartHelp[it.indicator_key]

  return (
    <div className="card">
      {help ? (
        <HoverHelp title={help.title} body={help.body} delayMs={2000}>
          <div className="hstack" style={{ justifyContent: 'space-between' }}>
            <div className="badge">
              <span className={`dot ${it.state}`} />
              <span>{title}</span>
            </div>
            <div style={{ fontSize: 16 }}>{stateEmoji(it.state)}</div>
          </div>
        </HoverHelp>
      ) : (
        <div className="hstack" style={{ justifyContent: 'space-between' }}>
          <div className="badge">
            <span className={`dot ${it.state}`} />
            <span>{title}</span>
          </div>
          <div style={{ fontSize: 16 }}>{stateEmoji(it.state)}</div>
        </div>
      )}

      <div className="vstack" style={{ marginTop: 10, gap: 8 }}>
        {structure && slope !== null ? (
          <>
            <div className="muted">结构：{structure}</div>
            <div style={{ fontVariantNumeric: 'tabular-nums' }}>slope(VIX-VXV): {fmt(slope, 2)}</div>
          </>
        ) : null}

        {label && qLo !== null && qHi !== null && value !== null ? (
          <>
            <div className="muted">状态解释：{label}</div>
            <div className="muted">区间（33%/66% 分位）：{fmt(qLo, 2)} / {fmt(qHi, 2)}</div>
            <div style={{ fontVariantNumeric: 'tabular-nums' }}>本期变化：{fmt(value, 2)}</div>
            <ProgressBar value={value} min={qLo} max={qHi} color="rgba(148,163,184,0.85)" />
          </>
        ) : null}

        {q1 !== null && q2 !== null && value !== null ? (
          <>
            <div className="muted">阈值（90%/95% 分位）：{fmt(q1, 2)} / {fmt(q2, 2)}</div>
            <div style={{ fontVariantNumeric: 'tabular-nums' }}>当前值：{fmt(value, 2)}</div>
            <ProgressBar value={value} min={Math.min(q1, value)} max={Math.max(q2, value)} color="rgba(45,212,191,0.85)" />
          </>
        ) : null}

        {/* Fallback */}
        {!structure && !(label && qLo !== null && qHi !== null && value !== null) && !(q1 !== null && q2 !== null && value !== null) ? (
          <div className="muted">（无结构化字段，见 Raw）</div>
        ) : null}

        <details>
          <summary className="muted">查看 Raw details JSON</summary>
          <pre style={{ marginTop: 8 }}>{JSON.stringify(it.details, null, 2)}</pre>
        </details>
      </div>
    </div>
  )
}
