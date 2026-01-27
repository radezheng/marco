export type IndicatorState = {
  indicator_key: string
  date: string
  state: 'G' | 'Y' | 'R' | 'U'
  score: number | null
  details: Record<string, unknown>
}

export type Allocation = {
  template_name: string
  asset_class_weights: Record<string, number>
  equity_bucket_weights: Record<string, number>
  overlays: Record<string, number>
}

export type Snapshot = {
  asof: string
  indicators: IndicatorState[]
  regime: {
    date: string
    regime: 'A' | 'B' | 'C'
    risk_score: number
    template_name: string
    drivers: Record<string, unknown>
  } | null
  allocation: Allocation | null
}

export type SeriesPoint = { date: string; value: number }

export type CnIndustry = { code: string; name: string }

export type CnTopItem = { code: string; name: string; value: number }

export type CnTopResponse = {
  asof: string
  metric: 'return' | 'amount' | string
  window_days: number
  items: CnTopItem[]
}

export type CnSectorOverviewItem = {
  code: string
  name: string
  main_net: number
  flow_strength?: number | null
  flow_5d?: number | null
  flow_10d?: number | null
  price_return_5d?: number | null
  divergence_score?: number | null
  state: string
  rank: number
  rank_change?: number | null
}

export type CnSectorOverview = {
  asof: string
  top_inflow: CnSectorOverviewItem[]
  top_outflow: CnSectorOverviewItem[]
  new_mainline?: Array<{
    code: string
    name: string
    main_net: number
    state: string
    prev_state?: string | null
    rotation_speed?: number | null
    rank?: number | null
    divergence_score?: number | null
  }>
  fading?: Array<{
    code: string
    name: string
    main_net: number
    state: string
    prev_state?: string | null
    rotation_speed?: number | null
    rank?: number | null
    divergence_score?: number | null
  }>
}

export type CnSectorMatrixRow = { code: string; name: string; values: number[] }

export type CnSectorMatrix = {
  asof: string
  dates: string[]
  rows: CnSectorMatrixRow[]
}

export type CnSectorBreadth = {
  asof: string
  code: string
  name: string
  breadth: number
  up: number
  total: number
}

export type IngestRunResult = {
  inserted_or_updated: number
  base_series_fetched: string[]
  errors: Record<string, string>
  cn_industries: {
    inserted_or_updated: number
    errors: Record<string, string>
  }
  asof: string | null
  regime: string | null
  risk_score: number | null
  core_states: Record<string, string>
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init)
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(text || resp.statusText)
  }
  return (await resp.json()) as T
}

export type ExplainCached = {
  asof: string
  cached: boolean
  text: string | null
  snapshot_hash?: string
  updated_at?: string | null
}

export type ExplainStream = {
  close: () => void
}

export type TelemetryStats = {
  ok: boolean
  disabled?: boolean
  window_days?: number
  pv?: number
  sessions?: number
  visitors?: number
  pv_by_day?: Array<{ date: string; pv: number }>
}

function withQuery(path: string, q: Record<string, string | number | undefined | null>) {
  const u = new URL(path, window.location.origin)
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined || v === null || v === '') continue
    u.searchParams.set(k, String(v))
  }
  return u.pathname + u.search
}

export const api = {
  snapshot: (asof?: string) => http<Snapshot>(withQuery('/api/snapshot', { asof })),
  series: (key: string, days = 365, asof?: string) =>
    http<SeriesPoint[]>(withQuery(`/api/observations/${encodeURIComponent(key)}`, { days, asof })),
  ingestRun: () => http<IngestRunResult>('/api/ingest/run', { method: 'POST' }),
  explainCached: (asof?: string) => http<ExplainCached>(withQuery('/api/chat/explain/cached', { asof })),
  explain: (asof?: string, force?: boolean) =>
    http<{ asof: string; text: string; cached?: boolean }>(
      withQuery('/api/chat/explain', { asof, force: force ? 1 : undefined }),
      { method: 'POST' }
    ),
  explainStream: (handlers: {
    onDelta: (delta: string) => void
    onDone: () => void
    onError: (err: Error) => void
  }, asof?: string, force?: boolean): ExplainStream => {
    const es = new EventSource(withQuery('/api/chat/explain/stream', { asof, force: force ? 1 : undefined }))
    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data)
        if (payload?.delta) handlers.onDelta(String(payload.delta))
        if (payload?.error) {
          handlers.onError(new Error(String(payload.error)))
          es.close()
        }
        if (payload?.done) {
          handlers.onDone()
          es.close()
        }
      } catch (e) {
        handlers.onError(new Error(String(e)))
        es.close()
      }
    }
    es.onerror = () => {
      handlers.onError(new Error('SSE stream error'))
      es.close()
    }
    return { close: () => es.close() }
  },

  telemetryPageView: (payload: { session_id: string; path?: string; asof?: string; event?: string }) =>
    http<{ ok: boolean; disabled?: boolean }>(
      '/api/telemetry/pageview',
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload)
      }
    ),

  telemetryStats: (days = 0) => http<TelemetryStats>(withQuery('/api/telemetry/stats', { days })),

  cnIndustries: () => http<CnIndustry[]>('/api/cn/industries'),
  cnIndustriesTop: (metric: string, days = 20, n = 10, asof?: string) =>
    http<CnTopResponse>(withQuery('/api/cn/industries/top', { metric, days, n, asof })),

  cnSectorOverview: (n = 10, asof?: string) =>
    http<CnSectorOverview>(withQuery('/api/cn/sector/overview', { n, asof })),
  cnSectorMatrix: (days = 10, n = 20, direction: 'abs' | 'in' | 'out' = 'abs', asof?: string) =>
    http<CnSectorMatrix>(withQuery('/api/cn/sector/matrix', { days, n, direction, asof })),
  cnSectorBreadth: (code: string, asof?: string) =>
    http<CnSectorBreadth>(withQuery('/api/cn/sector/breadth', { code, asof }))
}

export function getOrCreateSessionId(): string {
  const key = 'marco_session_id'
  try {
    const existing = window.localStorage.getItem(key)
    if (existing && existing.length >= 8) return existing
  } catch {
    // ignore
  }

  const sid = (typeof crypto !== 'undefined' && 'randomUUID' in crypto)
    ? crypto.randomUUID()
    : `sid_${Math.random().toString(16).slice(2)}_${Date.now()}`

  try {
    window.localStorage.setItem(key, sid)
  } catch {
    // ignore
  }
  return sid
}
