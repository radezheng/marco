import React from 'react'
import { api, getOrCreateSessionId, IndicatorState, Snapshot } from './api'
import { LineChartPanel } from './components/LineChartPanel'
import { DriversPanel } from './components/DriversPanel.tsx'
import { IndicatorCard } from './components/IndicatorCard.tsx'
import { HoverHelp } from './components/HoverHelp'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type Telemetry = {
  pv: number
  visitors: number
  disabled?: boolean
  loading?: boolean
}

function stateLabel(s: string) {
  if (s === 'G') return '🟢'
  if (s === 'Y') return '🟡'
  if (s === 'R') return '🔴'
  return '⚪'
}

function normalizeMarkdownish(input: string): string {
  let s = input
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')

  // If the text is double-escaped (shows literal "\\n"), normalize it.
  if (s.includes('\\n')) {
    s = s.replace(/\\n/g, '\n')
  }

  // Some models wrap the entire response in a single fenced code block.
  // If so, strip the fence to render as regular Markdown.
  const trimmed = s.trim()
  const m = trimmed.match(/^```(?:markdown|md|text)?\s*\n([\s\S]*?)\n```\s*$/i)
  if (m?.[1] != null) {
    s = m[1]
  }

  // Common non-Markdown bullet styles.
  s = s.replace(/^\s*•\s+/gm, '- ')

  // Turn "1)" into Markdown ordered list "1.".
  s = s.replace(/^(\s*)(\d+)\)\s+/gm, '$1$2. ')

  return s
}

export function App() {
  const [snapshot, setSnapshot] = React.useState<Snapshot | null>(null)
  const [asofFilter, setAsofFilter] = React.useState<string>('')
  const [snapshotLoading, setSnapshotLoading] = React.useState(false)
  const [ingestLoading, setIngestLoading] = React.useState(false)
  const [explainLoading, setExplainLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [explainText, setExplainText] = React.useState<string | null>(null)
  const [explainError, setExplainError] = React.useState<string | null>(null)
  const [telemetry, setTelemetry] = React.useState<Telemetry>({ pv: 0, visitors: 0, loading: true })
  const explainStreamRef = React.useRef<{ close: () => void } | null>(null)
  const refreshReqRef = React.useRef(0)

  React.useEffect(() => {
    // Fire-and-forget telemetry (can be disabled server-side).
    const sid = getOrCreateSessionId()
    api.telemetryPageView({ session_id: sid, path: window.location.pathname, asof: asofFilter || undefined })
      .catch(() => {})
    // only once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  React.useEffect(() => {
    let alive = true
    async function loadStats() {
      try {
        const s = await api.telemetryStats(0)
        if (!alive) return
        if (s.disabled || s.ok === false) {
          setTelemetry({ pv: 0, visitors: 0, disabled: true, loading: false })
          return
        }
        setTelemetry({ pv: Number(s.pv ?? 0), visitors: Number(s.visitors ?? 0), loading: false })
      } catch {
        if (!alive) return
        // Keep it visible even if stats call fails.
        setTelemetry((prev) => ({ ...prev, loading: false }))
      }
    }

    loadStats()
    const t = window.setInterval(loadStats, 60_000)
    return () => {
      alive = false
      window.clearInterval(t)
    }
  }, [])

  async function refresh(nextAsof?: string) {
    const reqId = ++refreshReqRef.current
    setSnapshotLoading(true)
    setError(null)
    try {
      const s = await api.snapshot(nextAsof)
      if (reqId !== refreshReqRef.current) return
      setSnapshot(s)
    } catch (e) {
      if (reqId !== refreshReqRef.current) return
      setError(String(e))
    } finally {
      if (reqId === refreshReqRef.current) setSnapshotLoading(false)
    }
  }

  React.useEffect(() => {
    refresh(asofFilter)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asofFilter])

  React.useEffect(() => {
    let alive = true
    async function loadExplainCache() {
      if (!snapshot?.asof) return
      if (explainLoading) return
      try {
        const r = await api.explainCached(asofFilter || undefined)
        if (!alive) return
        if (r.cached && r.text) {
          setExplainText(r.text)
          setExplainError(null)
        }
      } catch {
        // Cache is optional; ignore errors.
      }
    }

    loadExplainCache()
    return () => {
      alive = false
    }
  }, [snapshot?.asof, asofFilter, explainLoading])

  async function runIngest() {
    setIngestLoading(true)
    setError(null)
    setExplainText(null)
    setExplainError(null)
    try {
      await api.ingestRun()
      setAsofFilter('')
      await refresh('')
    } catch (e) {
      setError(String(e))
    } finally {
      setIngestLoading(false)
    }
  }

  async function explain() {
    setExplainLoading(true)
    setExplainError(null)

    if (explainStreamRef.current) {
      explainStreamRef.current.close()
      explainStreamRef.current = null
    }

    try {
      setExplainText('')
      explainStreamRef.current = api.explainStream(
        {
        onDelta: (d) => setExplainText((prev) => (prev ?? '') + d),
        onDone: () => {
          explainStreamRef.current = null
          setExplainLoading(false)
          // best-effort refresh cached version (in case server cached the final text)
          api.explainCached(asofFilter || undefined)
            .then((r) => {
              if (r.cached && r.text) setExplainText(r.text)
            })
            .catch(() => {})
        },
        onError: (err) => {
          explainStreamRef.current = null
          setExplainLoading(false)
          setExplainError(String(err))
        }
        },
        asofFilter,
        true
      )
    } catch (e) {
      // Fallback to non-stream if SSE creation fails
      try {
        const r = await api.explain(asofFilter, true)
        setExplainText(r.text)
      } catch (e2) {
        setExplainError(String(e2))
      }
      setExplainLoading(false)
    }
  }

  function stopExplain() {
    if (explainStreamRef.current) {
      explainStreamRef.current.close()
      explainStreamRef.current = null
    }
    setExplainLoading(false)
  }

  const indicators = snapshot?.indicators ?? []
  const regime = snapshot?.regime
  const allocation = snapshot?.allocation

  const indicatorOrder = [
    'synthetic_liquidity',
    'credit_spread',
    'usd_strength',
    'funding_stress',
    'treasury_vol',
    'vix_structure',
    'vix_level'
  ]

  const indicatorMap = new Map<string, IndicatorState>(indicators.map((i: IndicatorState) => [i.indicator_key, i]))

  return (
    <div className="container vstack">
      {snapshotLoading ? (
        <div className="page-overlay" role="status" aria-live="polite">
          <div className="page-overlay-card">
            <div className="spinner" />
            <div>
              <div style={{ fontWeight: 800, fontSize: 13 }}>加载中…</div>
              <div className="muted" style={{ marginTop: 2 }}>正在切换到 {asofFilter || '最新'} 数据</div>
            </div>
          </div>
        </div>
      ) : null}

      <div className="hstack" style={{ justifyContent: 'space-between' }}>
        <div className="vstack" style={{ gap: 6 }}>
          <div className="h1">Marco Regime Monitor</div>
          <div className="muted">Asof: {snapshot?.asof ?? '—'} · 数据源：免费官方（FRED/NYFed 等公开序列）</div>
        </div>
        <div className="hstack">
          <div className="hstack" style={{ gap: 8 }}>
            <div className="muted">回看日期</div>
            <input
              type="date"
              value={asofFilter}
              onChange={(e) => {
                setExplainText(null)
                setExplainError(null)
                setAsofFilter(e.target.value)
              }}
              style={{
                background: 'rgba(255,255,255,0.06)',
                border: '1px solid rgba(255,255,255,0.12)',
                color: '#e8eefc',
                padding: '8px 10px',
                borderRadius: 10
              }}
            />
            <button
              className="button"
              onClick={() => {
                setExplainText(null)
                setExplainError(null)
                setAsofFilter('')
              }}
              disabled={!asofFilter || ingestLoading || explainLoading}
            >
              最新
            </button>
          </div>
          <button className="button" onClick={runIngest} disabled={ingestLoading || explainLoading}>运行采集/计算</button>
          <button className="button" onClick={explain} disabled={explainLoading || ingestLoading}>
            {explainText ? '重新生成 LLM 解释' : 'LLM 解释（可选）'}
          </button>
          {explainLoading ? (
            <button className="button" onClick={stopExplain}>停止</button>
          ) : null}
        </div>
      </div>

      {error && <pre>{error}</pre>}

      <div className="card">
        <div className="hstack" style={{ justifyContent: 'space-between' }}>
          <div className="h1">LLM 解释</div>
          <div className="muted">{explainLoading ? 'streaming…' : 'markdown'}</div>
        </div>
        {explainError ? <pre style={{ marginTop: 10 }}>{explainError}</pre> : null}
        {explainText ? (
          <div className="md" style={{ marginTop: 10 }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{normalizeMarkdownish(explainText)}</ReactMarkdown>
          </div>
        ) : (
          <div className="muted" style={{ marginTop: 10 }}>点击“LLM 解释（可选）”生成解释（流式输出）。</div>
        )}
      </div>

      <div className="grid grid-3">
        <div className="card">
          <div className="muted">系统状态</div>
          <div style={{ fontSize: 18, fontWeight: 700, marginTop: 6 }}>
            {regime ? `状态 ${regime.regime} · ${regime.template_name}` : '—'}
          </div>
          <div className="muted" style={{ marginTop: 6 }}>
            risk_score: {regime ? regime.risk_score.toFixed(1) : '—'}
          </div>
        </div>
        <DriversPanel regime={regime} />
        <div className="card">
          <HoverHelp
            title="仓位模板（大类）含义"
            body={
              '这些是策略层面的“风险敞口大类”权重（合计≈100%），用于表达当前 Regime 下的偏好：\n\n'
              + '• Equity：股票/权益风险资产（含主要行业篮子）\n'
              + '• Rates：利率类（以国债/久期暴露为主，用于防御/对冲）\n'
              + '• Credit：信用类（公司债/高收益等信用利差风险）\n'
              + '• Cash：现金/货币基金等低波动仓位\n'
              + '• Gold&Commodities：黄金与大宗商品（通胀/风险事件对冲）\n\n'
              + '注：Overlays（如 FX_HEDGE）是叠加层，不一定计入大类权重。'
            }
            delayMs={2000}
          >
            <div className="muted">仓位模板（大类）</div>
          </HoverHelp>
          {allocation ? (
            <div className="vstack" style={{ marginTop: 10 }}>
              {Object.entries(allocation.asset_class_weights).map(([k, v]) => (
                <div key={k} className="hstack" style={{ justifyContent: 'space-between' }}>
                  <div className="muted">{k}</div>
                  <div style={{ width: 180, background: 'rgba(255,255,255,0.10)', borderRadius: 999, overflow: 'hidden' }}>
                    <div style={{ width: `${Math.round(v * 100)}%`, height: 10, background: 'rgba(45,212,191,0.8)' }} />
                  </div>
                  <div style={{ fontVariantNumeric: 'tabular-nums' }}>{Math.round(v * 100)}%</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="muted" style={{ marginTop: 10 }}>—</div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="hstack" style={{ justifyContent: 'space-between' }}>
          <div className="h1">指标状态（🟢🟡🔴）</div>
          <div className="muted">以滚动历史分位数判定（默认 3 年窗口）</div>
        </div>
        <div className="grid grid-3" style={{ marginTop: 12 }}>
          {indicatorOrder.map((k) => {
            const it = indicatorMap.get(k)
            if (!it) return null
            return (
              <IndicatorCard key={k} item={it} />
            )
          })}
        </div>
      </div>

      <div className="grid grid-2">
        <LineChartPanel
          title="合成流动性（周变化）"
          seriesKey="synthetic_liquidity_delta_w"
          asof={asofFilter || undefined}
          valueFactor={0.001}
          valueUnit="bn USD"
          valueDigits={1}
        />
        <LineChartPanel
          title="信用压力（HY OAS）"
          seriesKey="hy_oas"
          asof={asofFilter || undefined}
          valueFactor={100}
          valueUnit="bp"
          valueDigits={0}
        />
        <LineChartPanel
          title="资金压力（SOFR - IORB/EFFR）"
          seriesKey="funding_spread"
          asof={asofFilter || undefined}
          valueFactor={100}
          valueUnit="bp"
          valueDigits={1}
        />
        <LineChartPanel
          title="美债实现波动（20D）"
          seriesKey="treasury_realized_vol_20d"
          asof={asofFilter || undefined}
          valueUnit="% (ann.)"
          valueDigits={2}
        />
        <LineChartPanel
          title="VIX 结构（VIX - VXV）"
          seriesKey="vix_slope"
          asof={asofFilter || undefined}
          valueUnit="pts"
          valueDigits={2}
        />
        <LineChartPanel
          title="美元强弱（Fed TWI Broad）"
          seriesKey="usd_twi_broad"
          asof={asofFilter || undefined}
          valueUnit="index"
          valueDigits={2}
        />
      </div>

      <div className="muted" style={{ fontSize: 12, opacity: 0.75 }}>
        {telemetry.disabled
          ? '访问统计：已关闭'
          : telemetry.loading
            ? '访问统计：加载中…'
            : `访问统计：总访问次数(PV) ${telemetry.pv} · 近似人数(UV) ${telemetry.visitors}`}
      </div>
    </div>
  )
}
