import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import MetricCard from '../components/MetricCard'
import StatusBadge from '../components/StatusBadge'
import { LoadingSpinner, ErrorState } from '../components/LoadingState'
import { usePipelineStats, usePipelineRuns, useModelInfo } from '../lib/api'

// ── Pipeline Architecture ────────────────────────────────────────────────────

const PIPELINE_STEPS = [
  {
    num: 1, name: 'Ingest', table: 'raw_inputs', color: '#2E7D32',
    desc: 'Scrapes daily price reports from Agmarknet and eNAM government databases for all 15 monitored mandis across Tamil Nadu',
    options: [
      { label: 'Agmarknet Scraper', note: 'Government agricultural market prices, updated daily', active: true },
      { label: 'eNAM Scraper', note: 'Electronic National Agriculture Market, online trading platform', active: true },
      { label: 'Mandi Metadata', note: 'Market coordinates, trading hours, commodity lists', active: true },
    ],
  },
  {
    num: 2, name: 'Extract', table: 'extracted_data', color: '#7B1FA2',
    desc: 'Parses raw HTML and PDF reports into structured price records: commodity, quantity, min/max/modal prices per mandi',
    options: [
      { label: 'AI-Powered', note: 'Handles inconsistent formats, missing fields, Hindi/Tamil text', active: true },
      { label: 'Regex Fallback', note: 'Pattern matching for standard Agmarknet tabular format', active: false },
    ],
  },
  {
    num: 3, name: 'Reconcile', table: 'reconciled_data', color: '#1565C0',
    desc: 'When Agmarknet and eNAM report different prices for the same mandi on the same day, the AI investigates and produces a single reconciled price with reasoning',
    options: [
      { label: 'AI Reconciliation', note: 'Compares sources, checks historical patterns, explains decisions', active: true },
      { label: 'Weighted Average', note: 'Fallback: weight by source reliability score', active: false },
    ],
  },
  {
    num: 4, name: 'Forecast', table: 'price_forecasts', color: '#E65100',
    desc: 'Predicts price movements for 7, 14, and 30 days using 15 features: seasonality, weather, arrival volumes, transport costs, and historical patterns',
    options: [
      { label: 'XGBoost Model', note: 'Gradient-boosted trees trained on 3 years of Tamil Nadu price data', active: true },
      { label: 'Seasonal Patterns', note: 'Harvest cycles, festival demand, monsoon effects', active: true },
      { label: 'Confidence Intervals', note: 'Probabilistic bounds on price predictions', active: true },
    ],
  },
  {
    num: 5, name: 'Optimize', table: 'sell_options', color: '#C62828',
    desc: 'For each farmer, computes all (mandi, timing) combinations, accounting for transport costs, storage losses, mandi fees, and distance',
    options: [
      { label: 'Route Optimization', note: 'Haversine + drive time estimation', active: true },
      { label: 'Cost Model', note: 'Transport, storage decay, commission fees per mandi', active: true },
    ],
  },
  {
    num: 6, name: 'Recommend', table: 'recommendations', color: '#d4a019',
    desc: 'Generates personalized sell advice for each farmer in English and Tamil, explaining which mandi, when to sell, and why \u2014 backed by a full cost breakdown',
    options: [
      { label: 'AI-Generated Advice', note: 'Natural language recommendations with reasoning', active: true },
      { label: 'Tamil Translation', note: 'Bilingual output for farmer accessibility', active: true },
    ],
  },
]

// ── Architecture Diagram Component ───────────────────────────────────────────

function ArchitectureDiagram() {
  return (
    <div className="flex flex-col gap-0 pl-5">
      {PIPELINE_STEPS.map((s, i) => (
        <div key={s.num}>
          <div className="flex items-start gap-3.5">
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center text-white font-bold text-sm shrink-0 mt-0.5"
              style={{ background: s.color }}
            >
              {s.num}
            </div>
            <div className="flex-1 bg-white border border-warm-border rounded-lg p-3.5">
              <div className="flex items-center gap-2.5 flex-wrap mb-1">
                <span className="font-bold text-sm" style={{ color: s.color }}>{s.name}</span>
                <code className="bg-warm-header-bg px-2 py-0.5 rounded text-[0.72rem] text-warm-body">
                  {s.table}
                </code>
              </div>
              <p className="text-xs text-warm-muted m-0 mb-2">{s.desc}</p>
              <div className="flex flex-wrap gap-1.5">
                {s.options.map((opt) => (
                  <span
                    key={opt.label}
                    className="text-[0.7rem] px-2 py-0.5 rounded-md border"
                    style={{
                      background: opt.active ? `${s.color}12` : '#f8f7f4',
                      color: opt.active ? s.color : '#999',
                      borderColor: opt.active ? `${s.color}44` : '#e0dcd5',
                      fontWeight: opt.active ? 600 : 400,
                    }}
                    title={opt.note}
                  >
                    {opt.label}
                    {opt.active && ' \u25CF'}
                  </span>
                ))}
              </div>
            </div>
          </div>
          {i < PIPELINE_STEPS.length - 1 && (
            <div className="flex items-center pl-[18px] py-0">
              <div className="w-[2px] h-5 bg-warm-border ml-[0px]" />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Cost Breakdown Component ─────────────────────────────────────────────────

function CostBreakdown() {
  const costs = [
    { component: 'Agmarknet scraping', cost: 0, note: 'Free government data' },
    { component: 'eNAM scraping', cost: 0, note: 'Free government data' },
    { component: 'AI: Data extraction', cost: 0.04, note: 'Parsing 15 mandi reports' },
    { component: 'AI: Price reconciliation', cost: 0.06, note: 'Resolving conflicts across sources' },
    { component: 'AI: Sell recommendations', cost: 0.05, note: 'Generating personalized advice' },
    { component: 'XGBoost forecasting', cost: 0, note: 'Local model inference' },
    { component: 'Haversine + drive time estimation', cost: 0, note: 'Distance and route calculations' },
    { component: 'Backend server', cost: 0, note: 'Cloud hosting (free tier)' },
  ]
  const total = costs.reduce((s, c) => s + c.cost, 0)

  return (
    <div className="bg-white border border-warm-border rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-warm-header-bg">
            <th className="text-left px-4 py-2 text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider">Component</th>
            <th className="text-right px-4 py-2 text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider">Cost/Run</th>
            <th className="text-left px-4 py-2 text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider">Note</th>
          </tr>
        </thead>
        <tbody>
          {costs.map((c) => (
            <tr key={c.component} className="border-t border-warm-border/50">
              <td className="px-4 py-2 font-medium text-[#1a1a1a]">{c.component}</td>
              <td className="px-4 py-2 text-right font-mono text-xs">
                {c.cost === 0 ? (
                  <span className="text-success font-semibold">Free</span>
                ) : (
                  `$${c.cost.toFixed(2)}`
                )}
              </td>
              <td className="px-4 py-2 text-warm-muted text-xs">{c.note}</td>
            </tr>
          ))}
          <tr className="border-t-2 border-warm-border bg-warm-header-bg">
            <td className="px-4 py-2 font-bold text-[#1a1a1a]">Total per pipeline run</td>
            <td className="px-4 py-2 text-right font-mono font-bold text-[#1a1a1a]">${total.toFixed(2)}</td>
            <td className="px-4 py-2 text-warm-muted text-xs font-semibold">~$5/month at daily runs</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

// ── Main Pipeline Page ───────────────────────────────────────────────────────

export default function Pipeline() {
  const stats = usePipelineStats()
  const runs = usePipelineRuns()
  const modelInfo = useModelInfo()
  const [expandedRun, setExpandedRun] = useState<string | null>(null)
  const [tab, setTab] = useState<'architecture' | 'runs' | 'stats'>('architecture')
  const [triggering, setTriggering] = useState(false)

  if (stats.isLoading) return <LoadingSpinner />
  if (stats.isError) return <ErrorState onRetry={() => stats.refetch()} />

  const s = stats.data

  async function handleTrigger() {
    setTriggering(true)
    try {
      const baseUrl = import.meta.env.VITE_API_URL ?? ''
      await fetch(`${baseUrl}/api/pipeline/trigger`, { method: 'POST' })
      runs.refetch()
      stats.refetch()
    } finally {
      setTriggering(false)
    }
  }

  return (
    <div className="animate-slide-up">
      <div className="pt-2 pb-6">
        <h1 className="page-title">How It Works</h1>
        <p className="page-caption">
          A look inside the system: what it does, how often it runs, and what it costs
        </p>
      </div>

      {/* Metrics */}
      <div className="mb-8">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-stagger">
          <MetricCard
            label="Pipeline Runs"
            value={s?.total_runs}
            subtitle={`${Math.round((s?.success_rate ?? 0) * 100)}% success`}
          />
          <MetricCard label="Mandis" value={s?.mandis_monitored} subtitle="monitored" />
          <MetricCard label="Commodities" value={s?.commodities_tracked} subtitle="tracked" />
          <MetricCard
            label="Running Cost"
            value={`$${s?.total_cost_usd?.toFixed(2) ?? '0'}`}
            subtitle="total spend"
          />
        </div>
      </div>

      {/* Tabs */}
      <div className="tab-list mb-6">
        {(['architecture', 'runs', 'stats'] as const).map((t) => (
          <button
            key={t}
            className={`tab-item ${tab === t ? 'active' : ''}`}
            onClick={() => setTab(t)}
          >
            {t === 'architecture' ? 'System Design' : t === 'runs' ? 'Run History' : 'Cost & Model'}
          </button>
        ))}
      </div>

      {/* Architecture Tab */}
      {tab === 'architecture' && (
        <div className="animate-tab-enter space-y-6">
          <div className="section-header">From Scraping to Sell Advice in 6 Steps</div>
          <ArchitectureDiagram />

          <div className="mt-8">
            <div className="section-header">Data Sources & AI Capabilities</div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">Price Data</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">2 Government Sources</p>
                <p className="text-xs text-warm-body m-0 mt-1">Agmarknet (national) and eNAM (electronic trading) \u2014 often conflicting.</p>
              </div>
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">Markets</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">15 Tamil Nadu Mandis</p>
                <p className="text-xs text-warm-body m-0 mt-1">Regulated agricultural markets across the state with daily price reporting.</p>
              </div>
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">Forecasting</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">XGBoost + 15 Features</p>
                <p className="text-xs text-warm-body m-0 mt-1">Gradient-boosted trees trained on 3 years of price data with seasonal and weather features.</p>
              </div>
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">AI Agents</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">3 Specialized Agents</p>
                <p className="text-xs text-warm-body m-0 mt-1">Data extraction, price reconciliation, and sell recommendation generation.</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Runs Tab */}
      {tab === 'runs' && (
        <div className="animate-tab-enter space-y-6">
          {/* Scheduler + trigger */}
          <div className="card card-body">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-sans text-warm-body m-0">
                  <span className="font-semibold text-[#1a1a1a]">Last run: </span>
                  {s?.last_run ? new Date(s.last_run).toLocaleString() : 'Never'}
                </p>
                <p className="text-xs text-warm-muted m-0 mt-1">
                  Scheduled daily at 06:00 IST. Scrapes both sources and regenerates all forecasts.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <StatusBadge status={s?.last_run ? 'active' : 'pending'} />
                <button
                  className="btn-primary text-xs"
                  onClick={handleTrigger}
                  disabled={triggering}
                >
                  {triggering ? 'Running...' : 'Run Now'}
                </button>
              </div>
            </div>
          </div>

          {/* Run history */}
          {runs.isLoading ? (
            <LoadingSpinner message="Loading runs..." />
          ) : runs.isError ? (
            <ErrorState onRetry={() => runs.refetch()} />
          ) : (
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th className="w-8"></th>
                    <th>Run ID</th>
                    <th>Started</th>
                    <th>Status</th>
                    <th>Duration</th>
                    <th>Steps</th>
                    <th>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data?.runs.map((run) => (
                    <>
                      <tr
                        key={run.run_id}
                        className="cursor-pointer"
                        onClick={() => setExpandedRun(expandedRun === run.run_id ? null : run.run_id)}
                      >
                        <td>
                          {expandedRun === run.run_id
                            ? <ChevronDown size={14} className="text-warm-muted" />
                            : <ChevronRight size={14} className="text-warm-muted" />}
                        </td>
                        <td className="font-mono text-xs">{run.run_id}</td>
                        <td>{new Date(run.started_at).toLocaleString()}</td>
                        <td><StatusBadge status={run.status} /></td>
                        <td>{run.duration_s.toFixed(1)}s</td>
                        <td>{run.steps.length}</td>
                        <td>${run.total_cost_usd.toFixed(4)}</td>
                      </tr>
                      {expandedRun === run.run_id && (
                        <tr key={`${run.run_id}-detail`}>
                          <td colSpan={7} className="bg-warm-header-bg !p-0">
                            <div className="px-8 py-4">
                              <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider mb-3">
                                Step Details
                              </p>
                              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                                {run.steps.map((step, i) => (
                                  <div
                                    key={i}
                                    className="flex items-center justify-between bg-white rounded-lg px-3 py-2 border border-warm-border"
                                  >
                                    <span className="text-xs font-sans font-medium text-[#1a1a1a]">{step.step}</span>
                                    <div className="flex items-center gap-2">
                                      <StatusBadge status={step.status} />
                                      <span className="text-xs text-warm-muted">{step.duration_s.toFixed(1)}s</span>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Stats Tab */}
      {tab === 'stats' && (
        <div className="animate-tab-enter space-y-8">
          <div>
            <div className="section-header">Cost Breakdown</div>
            <CostBreakdown />
          </div>

          {/* Model info */}
          <div>
            <div className="section-header">Price Forecasting Model</div>
            {modelInfo.isLoading ? (
              <LoadingSpinner message="Loading model info..." />
            ) : modelInfo.isError ? (
              <ErrorState onRetry={() => modelInfo.refetch()} />
            ) : (
              <div className="space-y-4">
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className="text-xs font-sans font-semibold px-3 py-1 rounded-full"
                    style={{ backgroundColor: '#dbeafe', color: '#1e40af', border: '1px solid #93c5fd' }}
                  >
                    XGBoost Price Forecaster
                  </span>
                  {modelInfo.data?.model_metrics?.features && (
                    <span
                      className="text-xs font-sans font-semibold px-3 py-1 rounded-full"
                      style={{ backgroundColor: '#fef3c7', color: '#92400e', border: '1px solid #fcd34d' }}
                    >
                      {modelInfo.data.model_metrics.features.length} Features
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <MetricCard
                    label="Avg Error (RMSE)"
                    value={modelInfo.data?.model_metrics?.rmse?.toFixed(1) ?? '--'}
                    subtitle="typical prediction miss"
                  />
                  <MetricCard
                    label="Avg Deviation (MAE)"
                    value={modelInfo.data?.model_metrics?.mae?.toFixed(1) ?? '--'}
                    subtitle="average absolute error"
                  />
                  <MetricCard
                    label="Accuracy (R\u00b2)"
                    value={modelInfo.data?.model_metrics?.r2 ? `${(modelInfo.data.model_metrics.r2 * 100).toFixed(1)}%` : '--'}
                    subtitle="variance explained"
                  />
                  <MetricCard
                    label="Training Samples"
                    value={modelInfo.data?.model_metrics?.train_samples?.toLocaleString() ?? '--'}
                    subtitle="historical price records"
                  />
                </div>

                {/* Feature importances */}
                {modelInfo.data?.model_metrics?.feature_importances && (
                  <div className="card card-body">
                    <h3 className="text-sm font-semibold font-sans text-[#1a1a1a] mb-3">
                      What Drives the Forecast
                    </h3>
                    <div className="space-y-2">
                      {Object.entries(modelInfo.data.model_metrics.feature_importances)
                        .sort(([, a], [, b]) => b - a)
                        .slice(0, 10)
                        .map(([feature, importance]) => (
                          <div key={feature} className="flex items-center gap-3">
                            <span className="text-xs text-warm-body w-36 shrink-0 capitalize">
                              {feature.replace(/_/g, ' ')}
                            </span>
                            <div className="flex-1 h-2 bg-warm-header-bg rounded-full overflow-hidden">
                              <div
                                className="h-full rounded-full"
                                style={{
                                  width: `${Math.round(importance * 100)}%`,
                                  backgroundColor: '#d4a019',
                                }}
                              />
                            </div>
                            <span className="text-xs text-warm-muted w-10 text-right">
                              {Math.round(importance * 100)}%
                            </span>
                          </div>
                        ))}
                    </div>
                  </div>
                )}

                {/* Data sources */}
                {s?.data_sources && s.data_sources.length > 0 && (
                  <div className="card card-body">
                    <h3 className="text-sm font-semibold font-sans text-[#1a1a1a] mb-2">
                      Data Sources
                    </h3>
                    <div className="flex flex-wrap gap-2">
                      {s.data_sources.map((src) => (
                        <span key={src} className="badge-amber text-[0.7rem]">{src}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
