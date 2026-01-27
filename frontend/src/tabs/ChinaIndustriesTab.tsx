import React from 'react'
import { api, CnIndustry, CnSectorBreadth, CnSectorMatrix, CnSectorOverview } from '../api'
import { LineChartPanel } from '../components/LineChartPanel'

function fmtPct(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const p = v * 100
  const sign = p > 0 ? '+' : ''
  return `${sign}${p.toFixed(2)}%`
}

function fmtMoneyYi(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v / 1e8).toFixed(1)} 亿`
}

function arrowForRankChange(rc: number | null | undefined) {
  if (rc === null || rc === undefined) return '·'
  // tempA: rotation speed = today rank - yesterday rank
  // Negative => rank improves (stronger); Positive => rank worsens (weaker)
  if (rc <= -8) return '↑↑'
  if (rc <= -2) return '↑'
  if (rc >= 8) return '↓↓'
  if (rc >= 2) return '↓'
  return '→'
}

function heatColor(v: number) {
  // v is normalized in [-3, 3]
  const x = Math.max(-3, Math.min(3, v))
  const a = Math.min(0.85, 0.12 + (Math.abs(x) / 3) * 0.73)
  // CN A-share convention: red for up/positive, green for down/negative.
  if (x > 0.05) return `rgba(251, 113, 133, ${a})`
  if (x < -0.05) return `rgba(34, 197, 94, ${a})`
  return 'rgba(255,255,255,0.06)'
}

function computeState(flow5d: number | null, price5d: number | null): string {
  if (flow5d === null || price5d === null) return '未知'
  const flowPos = flow5d > 0
  const pricePos = price5d > 0
  if (flowPos && pricePos) return '主升'
  if (flowPos && !pricePos) return '吸筹'
  if (!flowPos && pricePos) return '派发'
  return '退潮'
}

export function ChinaIndustriesTab() {
  const [industries, setIndustries] = React.useState<CnIndustry[]>([])
  const [selected, setSelected] = React.useState<string>('')

  const [windowDays, setWindowDays] = React.useState<number>(365)
  const [matrixDays, setMatrixDays] = React.useState<number>(10)
  const [matrixDir, setMatrixDir] = React.useState<'in' | 'out'>('in')

  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const [overview, setOverview] = React.useState<CnSectorOverview | null>(null)
  const [matrix, setMatrix] = React.useState<CnSectorMatrix | null>(null)
  const [breadth, setBreadth] = React.useState<CnSectorBreadth | null>(null)

  const [detailFlow5d, setDetailFlow5d] = React.useState<number | null>(null)
  const [detailFlow10d, setDetailFlow10d] = React.useState<number | null>(null)
  const [detailPrice5d, setDetailPrice5d] = React.useState<number | null>(null)

  React.useEffect(() => {
    let alive = true
    setLoading(true)
    api.cnIndustries()
      .then((d) => {
        if (!alive) return
        setIndustries(d)
        setError(null)
        if (!selected && d.length > 0) setSelected(d[0].code)
      })
      .catch((e) => {
        if (!alive) return
        setError(String(e))
      })
      .finally(() => {
        if (!alive) return
        setLoading(false)
      })
    return () => { alive = false }
    // selected intentionally excluded (only set default once)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  React.useEffect(() => {
    let alive = true
    api.cnSectorOverview(10)
      .then((d) => { if (alive) setOverview(d) })
      .catch((e) => { if (alive) setError(String(e)) })
    return () => { alive = false }
  }, [])

  React.useEffect(() => {
    let alive = true
    api.cnSectorMatrix(matrixDays, 20, matrixDir)
      .then((d) => { if (alive) setMatrix(d) })
      .catch(() => { if (alive) setMatrix(null) })
    return () => { alive = false }
  }, [matrixDays, matrixDir])

  // Detail: compute simple stats from DB series + breadth from cached API.
  React.useEffect(() => {
    let alive = true
    if (!selected) return () => { alive = false }

    setBreadth(null)
    setDetailFlow5d(null)
    setDetailFlow10d(null)
    setDetailPrice5d(null)

    const flowKey = `cn_industry_flow_main_net:${selected}`
    const closeKey = `cn_industry_close:${selected}`

    Promise.all([
      api.series(flowKey, 80),
      api.series(closeKey, 80),
      api.cnSectorBreadth(selected).catch(() => null)
    ]).then(([flowPts, closePts, br]) => {
      if (!alive) return

      const flowVals = flowPts.map((p) => p.value)
      const closeVals = closePts.map((p) => p.value)

      const f5 = flowVals.length >= 5 ? flowVals.slice(-5).reduce((a, b) => a + b, 0) : (flowVals.length ? flowVals.reduce((a, b) => a + b, 0) : null)
      const f10 = flowVals.length >= 10 ? flowVals.slice(-10).reduce((a, b) => a + b, 0) : (flowVals.length ? flowVals.reduce((a, b) => a + b, 0) : null)
      let p5: number | null = null
      if (closeVals.length >= 6 && closeVals[closeVals.length - 6] !== 0) {
        p5 = closeVals[closeVals.length - 1] / closeVals[closeVals.length - 6] - 1
      }

      setDetailFlow5d(f5)
      setDetailFlow10d(f10)
      setDetailPrice5d(p5)
      setBreadth(br)
    }).catch(() => {
      if (!alive) return
      // ignore detail errors
    })

    return () => { alive = false }
  }, [selected])

  const name = industries.find((x) => x.code === selected)?.name
  const closeKey = selected ? `cn_industry_close:${selected}` : ''
  const amountKey = selected ? `cn_industry_amount:${selected}` : ''
  const flowKey = selected ? `cn_industry_flow_main_net:${selected}` : ''

  const state = computeState(detailFlow5d, detailPrice5d)

  return (
    <div className="container vstack">
      <div className="hstack" style={{ justifyContent: 'space-between' }}>
        <div className="vstack" style={{ gap: 6 }}>
          <div className="h1">A股板块（行业）</div>
          <div className="muted">数据日期（asof）：{overview?.asof ?? '—'}</div>
          <div className="muted">目标：3 秒内知道“今天钱往哪去”。状态机：吸筹/主升/派发/退潮。</div>
        </div>
        <div className="hstack" style={{ gap: 10, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <div className="hstack" style={{ gap: 8 }}>
            <div className="muted">窗口</div>
            <select
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
              style={{
                background: 'rgba(255,255,255,0.06)',
                border: '1px solid rgba(255,255,255,0.12)',
                color: '#e8eefc',
                padding: '8px 10px',
                borderRadius: 10
              }}
            >
              <option value={180}>近半年</option>
              <option value={365}>近一年</option>
            </select>
          </div>

          <div className="hstack" style={{ gap: 8 }}>
            <div className="muted">行业</div>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              disabled={loading || industries.length === 0}
              style={{
                background: 'rgba(255,255,255,0.06)',
                border: '1px solid rgba(255,255,255,0.12)',
                color: '#e8eefc',
                padding: '8px 10px',
                borderRadius: 10,
                minWidth: 210
              }}
            >
              {industries.map((x) => (
                <option key={x.code} value={x.code}>{x.name}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {error ? <pre>{error}</pre> : null}

      <div className="grid grid-3">
        <div className="card">
          <div className="muted">当前选择</div>
          <div style={{ fontSize: 18, fontWeight: 800, marginTop: 6 }}>{name ?? '—'}</div>
          <div className="muted" style={{ marginTop: 6 }}>{selected || '—'}</div>
          <div className="hstack" style={{ marginTop: 10, justifyContent: 'space-between' }}>
            <div className="muted">状态判断</div>
            <div style={{ fontWeight: 800 }}>{state}</div>
          </div>
          <div className="hstack" style={{ marginTop: 8, justifyContent: 'space-between' }}>
            <div className="muted">资金(5日)</div>
            <div style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtMoneyYi(detailFlow5d)}</div>
          </div>
          <div className="hstack" style={{ marginTop: 6, justifyContent: 'space-between' }}>
            <div className="muted">资金(10日)</div>
            <div style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtMoneyYi(detailFlow10d)}</div>
          </div>
          <div className="hstack" style={{ marginTop: 6, justifyContent: 'space-between' }}>
            <div className="muted">价格(5日)</div>
            <div style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtPct(detailPrice5d)}</div>
          </div>
          <div className="hstack" style={{ marginTop: 6, justifyContent: 'space-between' }}>
            <div className="muted">一致性(Breadth)</div>
            <div style={{ fontVariantNumeric: 'tabular-nums' }}>
              {breadth ? `${Math.round(breadth.breadth * 100)}% (${breadth.up}/${breadth.total})` : '—'}
            </div>
          </div>
        </div>

        <div className="card">
          <div
            className="muted"
            title={`口径：${overview?.asof ?? '最新'} 当日 主力净流入-净额（按该交易日各行业主力净额排序）`}
          >
            🔥 资金净流入 TOP（主力净额·当日）
          </div>
          <div className="vstack" style={{ marginTop: 10 }}>
            {overview?.top_inflow?.length ? overview.top_inflow.slice(0, 8).map((it) => (
              <button
                key={it.code}
                className="sector-row"
                type="button"
                onClick={() => setSelected(it.code)}
              >
                <div className="sector-name">{it.name}</div>
                <div className="sector-meta">
                  <span className="sector-state">{it.state}</span>
                  <span className="sector-arrow" title={`轮动速度(今日rank-昨日rank)=${it.rank_change ?? '—'}；越负越强`}>{arrowForRankChange(it.rank_change)}</span>
                  <span className="sector-mini" title="价-资背离分数：价涨资出=-1；价跌资入=+1；否则=0">
                    D{it.divergence_score ?? 0}
                  </span>
                </div>
                <div className="sector-value">{fmtMoneyYi(it.main_net)}</div>
              </button>
            )) : <div className="muted">—</div>}
          </div>
        </div>

        <div className="card">
          <div
            className="muted"
            title={`口径：${overview?.asof ?? '最新'} 当日 主力净流入-净额（负值为净流出；按该交易日各行业主力净额排序）`}
          >
            🧊 资金流出 TOP（主力净额·当日）
          </div>
          <div className="vstack" style={{ marginTop: 10 }}>
            {overview?.top_outflow?.length ? overview.top_outflow.slice(0, 8).map((it) => (
              <button
                key={it.code}
                className="sector-row"
                type="button"
                onClick={() => setSelected(it.code)}
              >
                <div className="sector-name">{it.name}</div>
                <div className="sector-meta">
                  <span className="sector-state">{it.state}</span>
                  <span className="sector-arrow" title={`轮动速度(今日rank-昨日rank)=${it.rank_change ?? '—'}；越负越强`}>{arrowForRankChange(it.rank_change)}</span>
                  <span className="sector-mini" title="价-资背离分数：价涨资出=-1；价跌资入=+1；否则=0">
                    D{it.divergence_score ?? 0}
                  </span>
                </div>
                <div className="sector-value">{fmtMoneyYi(it.main_net)}</div>
              </button>
            )) : <div className="muted">—</div>}
          </div>
        </div>
      </div>

      <div className="grid grid-2" style={{ marginTop: 10 }}>
        <div className="card">
          <div className="muted">🟢 今日新进入主升（新主线候选）</div>
          <div className="vstack" style={{ marginTop: 10 }}>
            {overview?.new_mainline?.length ? overview.new_mainline.map((it) => (
              <button
                key={it.code}
                className="sector-row"
                type="button"
                onClick={() => setSelected(it.code)}
              >
                <div className="sector-name">{it.name}</div>
                <div className="sector-meta">
                  <span className="sector-state">{it.prev_state ? `${it.prev_state}→${it.state}` : it.state}</span>
                  <span className="sector-arrow" title={`轮动速度(今日rank-昨日rank)=${it.rotation_speed ?? '—'}；越负越强`}>{arrowForRankChange(it.rotation_speed ?? null)}</span>
                  <span className="sector-mini" title="价-资背离分数：价涨资出=-1；价跌资入=+1；否则=0">
                    D{it.divergence_score ?? 0}
                  </span>
                </div>
                <div className="sector-value">{fmtMoneyYi(it.main_net)}</div>
              </button>
            )) : <div className="muted">—</div>}
          </div>
        </div>

        <div className="card">
          <div className="muted">🔻 今日退潮（谨慎/避险）</div>
          <div className="vstack" style={{ marginTop: 10 }}>
            {overview?.fading?.length ? overview.fading.map((it) => (
              <button
                key={it.code}
                className="sector-row"
                type="button"
                onClick={() => setSelected(it.code)}
              >
                <div className="sector-name">{it.name}</div>
                <div className="sector-meta">
                  <span className="sector-state">{it.prev_state ? `${it.prev_state}→${it.state}` : it.state}</span>
                  <span className="sector-arrow" title={`轮动速度(今日rank-昨日rank)=${it.rotation_speed ?? '—'}；越正越弱`}>{arrowForRankChange(it.rotation_speed ?? null)}</span>
                  <span className="sector-mini" title="价-资背离分数：价涨资出=-1；价跌资入=+1；否则=0">
                    D{it.divergence_score ?? 0}
                  </span>
                </div>
                <div className="sector-value">{fmtMoneyYi(it.main_net)}</div>
              </button>
            )) : <div className="muted">—</div>}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="hstack" style={{ justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
          <div className="muted">板块轮动矩阵（{matrixDir === 'in' ? '净流入' : '净流出'}；颜色=资金强度，近{matrixDays}个交易日）</div>
          <div className="hstack" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <div className="segmented" role="tablist" aria-label="轮动矩阵模式">
              <button
                type="button"
                className={matrixDir === 'in' ? 'segmented-btn segmented-btn--active' : 'segmented-btn'}
                aria-pressed={matrixDir === 'in'}
                onClick={() => setMatrixDir('in')}
              >
                流入
              </button>
              <button
                type="button"
                className={matrixDir === 'out' ? 'segmented-btn segmented-btn--active' : 'segmented-btn'}
                aria-pressed={matrixDir === 'out'}
                onClick={() => setMatrixDir('out')}
              >
                流出
              </button>
            </div>
            <select
              value={matrixDays}
              onChange={(e) => setMatrixDays(Number(e.target.value))}
              style={{
                background: 'rgba(255,255,255,0.06)',
                border: '1px solid rgba(255,255,255,0.12)',
                color: '#e8eefc',
                padding: '6px 10px',
                borderRadius: 10
              }}
            >
              <option value={10}>近10日</option>
              <option value={15}>近15日</option>
              <option value={20}>近20日</option>
            </select>
            <div className="muted">asof: {matrix?.asof ?? '—'}</div>
          </div>
        </div>

        {matrix?.rows?.length && matrix?.dates?.length ? (
          <div className="heatmap" style={{ marginTop: 10 }}>
            <div className="heatmap-header">
              <div className="heatmap-cell heatmap-name muted">板块</div>
              {matrix.dates.map((d) => (
                <div key={d} className="heatmap-cell heatmap-date muted">{d.slice(5)}</div>
              ))}
            </div>
            {matrix.rows.map((r) => (
              <div key={r.code} className={r.code === selected ? 'heatmap-row heatmap-row--active' : 'heatmap-row'}>
                <button
                  type="button"
                  className="heatmap-cell heatmap-name heatmap-name-btn"
                  onClick={() => setSelected(r.code)}
                >
                  {r.name}
                </button>
                {r.values.map((v, i) => (
                  <div
                    key={`${r.code}_${i}`}
                    className="heatmap-cell heatmap-val"
                    style={{ background: heatColor(v) }}
                    title={`${r.name} ${matrix.dates[i]} 强度=${v.toFixed(2)}`}
                  />
                ))}
              </div>
            ))}
          </div>
        ) : (
          <div className="muted" style={{ marginTop: 10 }}>—</div>
        )}
      </div>

      <div className="grid grid-2">
        {flowKey ? (
          <LineChartPanel
            title={`主力净流入（净额）：${name ?? ''}`}
            seriesKey={flowKey}
            days={windowDays}
            valueFactor={1e-8}
            valueUnit="亿"
            valueDigits={1}
          />
        ) : null}

        {closeKey ? (
          <LineChartPanel
            title={`行业指数收盘：${name ?? ''}`}
            seriesKey={closeKey}
            days={windowDays}
            valueUnit="index"
            valueDigits={2}
          />
        ) : null}
      </div>

      <div className="grid grid-2">
        {amountKey ? (
          <LineChartPanel
            title={`行业成交额：${name ?? ''}`}
            seriesKey={amountKey}
            days={windowDays}
            valueFactor={1e-8}
            valueUnit="亿"
            valueDigits={1}
          />
        ) : null}

        <div className="card">
          <div className="muted">信号定义（简版）</div>
          <div className="vstack" style={{ marginTop: 10, gap: 6 }}>
            <div className="muted">- 吸筹：资金(5日) {'>'} 0 且 价格(5日) {'≤'} 0</div>
            <div className="muted">- 主升：资金(5日) {'>'} 0 且 价格(5日) {'>'} 0</div>
            <div className="muted">- 派发：资金(5日) {'≤'} 0 且 价格(5日) {'>'} 0</div>
            <div className="muted">- 退潮：资金(5日) {'≤'} 0 且 价格(5日) {'≤'} 0</div>
          </div>
        </div>
      </div>
    </div>
  )
}
