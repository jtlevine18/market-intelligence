import { useState } from 'react'
import { ChevronDown, ChevronRight, Play } from 'lucide-react'
import MetricCard from '../components/MetricCard'
import StatusBadge from '../components/StatusBadge'
import { LoadingSpinner, ErrorState } from '../components/LoadingState'
import { usePipelineStats, usePipelineRuns } from '../lib/api'

// ── Architecture Diagram Data ─────────────────────────────────────────────

const PIPELINE_STEPS = [
  {
    num: 1, name: 'Collect', table: 'raw_inputs', color: '#2E7D32',
    desc: 'Gathers stock reports from pharmacists, disease surveillance data, community health worker messages, satellite weather data, and facility budgets',
    options: [
      { label: 'Pharmacist Reports', note: 'Monthly stock counts, often unstructured text', active: true },
      { label: 'Disease Surveillance', note: 'Weekly case counts from WHO-standard IDSR system', active: true },
      { label: 'Health Worker Messages', note: 'Informal reports from the field', active: true },
      { label: 'Satellite Weather', note: 'Temperature, rainfall, humidity from NASA', active: true },
      { label: 'Facility Budgets', note: 'Quarterly budget allocations', active: true },
    ],
  },
  {
    num: 2, name: 'Read & Structure', table: 'extracted_data', color: '#7B1FA2',
    desc: 'AI reads unstructured text reports and pulls out structured data: drug stock levels, disease case counts, and urgent alerts',
    options: [
      { label: 'AI-Powered', note: 'Reads messy text and extracts the numbers that matter', active: true },
      { label: 'Pattern Matching', note: 'Simpler backup for well-formatted reports', active: false },
    ],
  },
  {
    num: 3, name: 'Verify', table: 'reconciled_data', color: '#1565C0',
    desc: 'Compares stock reports against the logistics system and health worker observations — flags discrepancies and explains what it found',
    options: [
      { label: 'AI-Powered', note: 'Detects inconsistencies and explains how it resolved them', active: true },
      { label: 'Simple Rules', note: 'Basic averaging when AI is unavailable', active: false },
    ],
  },
  {
    num: 4, name: 'Predict Demand', table: 'demand_forecasts', color: '#E65100',
    desc: 'Predicts future drug demand using disease patterns, weather data, and past consumption — then a second model checks and corrects the first',
    options: [
      { label: 'Disease Patterns', note: 'Malaria peaks with rainfall, diarrhoea with flooding', active: true },
      { label: 'AI Demand Model', note: 'Learns from 20 factors including consumption history and facility characteristics', active: true },
      { label: 'Error Correction', note: 'A second model fixes systematic mistakes in the first', active: true },
      { label: 'Unusual Pattern Detection', note: 'Flags readings that look wrong — possible data errors or stock theft', active: true },
    ],
  },
  {
    num: 5, name: 'Build the Order', table: 'procurement_plans', color: '#C62828',
    desc: 'AI allocates the quarterly budget across medicines and facilities, prioritizing life-saving drugs and moving surplus stock between facilities',
    options: [
      { label: 'AI-Optimized', note: 'Considers tradeoffs across all facilities simultaneously', active: true },
      { label: 'Priority Rules', note: 'Critical drugs first, then by impact per dollar', active: true },
    ],
  },
  {
    num: 6, name: 'Recommend', table: 'recommendations', color: '#d4a019',
    desc: 'Generates personalized recommendations grounded in WHO and MSH clinical guidelines, drawing on a library of 101 health supply chain knowledge articles',
    options: [
      { label: 'AI + Clinical Knowledge', note: 'Recommendations grounded in WHO Essential Medicines and MSH procurement guidelines', active: true },
      { label: 'Standard Template', note: 'Generic recommendations when AI is unavailable', active: false },
    ],
  },
]

// ── Architecture Diagram Component ────────────────────────────────────────

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

// ── Cost Breakdown Component ──────────────────────────────────────────────

function CostBreakdown() {
  const costs = [
    { component: 'Weather data (NASA)', cost: 0, note: 'Free satellite data' },
    { component: 'AI: Reading reports', cost: 0.06, note: 'Parsing 10 facility stock reports' },
    { component: 'AI: Verifying data', cost: 0.04, note: 'Cross-checking multiple data sources' },
    { component: 'AI: Building the order', cost: 0.08, note: 'Optimizing across all facilities' },
    { component: 'AI: Recommendations', cost: 0.05, note: 'Grounded in WHO clinical guidelines' },
    { component: 'Backend server', cost: 0, note: 'Cloud hosting (free tier)' },
    { component: 'Dashboard', cost: 0, note: 'Cloud hosting (free tier)' },
    { component: 'Database', cost: 0, note: 'Cloud database (free tier)' },
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
            <td className="px-4 py-2 text-warm-muted text-xs font-semibold">~$7/month at daily runs</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

// ── Degradation Chain Component ───────────────────────────────────────────

function DegradationChain() {
  const tiers = [
    {
      tier: 'Best', name: 'Full AI Processing', color: '#2a9d8f',
      desc: 'AI reads reports, verifies data, predicts demand, detects problems, and builds recommendations grounded in clinical guidelines. Costs about $0.23 per update.',
    },
    {
      tier: 'Good', name: 'Automated Rules', color: '#d4a019',
      desc: 'If AI services are temporarily unavailable, the system falls back to pattern matching for reports and priority-based ordering. No AI cost.',
    },
    {
      tier: 'Basic', name: 'Historical Averages', color: '#e63946',
      desc: 'Last resort: uses last year\'s seasonal averages to estimate demand. Better than nothing, but misses real-time changes.',
    },
  ]

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {tiers.map((t) => (
        <div
          key={t.tier}
          className="bg-white border border-warm-border rounded-lg p-4"
          style={{ borderLeft: `4px solid ${t.color}` }}
        >
          <p className="text-[0.7rem] text-warm-muted uppercase tracking-widest font-semibold m-0">{t.tier}</p>
          <p className="text-sm font-bold text-[#1a1a1a] mt-1 mb-2 m-0">{t.name}</p>
          <p className="text-xs text-warm-body leading-relaxed m-0">{t.desc}</p>
        </div>
      ))}
    </div>
  )
}

// ── Main Pipeline Page ────────────────────────────────────────────────────

export default function Pipeline() {
  const stats = usePipelineStats()
  const runs = usePipelineRuns()
  const [expandedRun, setExpandedRun] = useState<string | null>(null)
  const [triggering, setTriggering] = useState(false)
  const [tab, setTab] = useState<'architecture' | 'runs' | 'stats'>('architecture')

  if (stats.isLoading) return <LoadingSpinner />
  if (stats.isError) return <ErrorState onRetry={() => stats.refetch()} />

  const s = stats.data

  const handleTrigger = async () => {
    setTriggering(true)
    try {
      const base = import.meta.env.VITE_API_URL ?? ''
      await fetch(`${base}/api/pipeline/trigger`, { method: 'POST' })
      await Promise.all([stats.refetch(), runs.refetch()])
    } catch {
      // handle silently
    } finally {
      setTriggering(false)
    }
  }

  return (
    <div className="animate-slide-up">
      <div className="pt-2 pb-6 flex items-start justify-between">
        <div>
          <h1 className="page-title">How It Works</h1>
          <p className="page-caption">
            A look inside the system: what it does, how often it runs, and what it costs
          </p>
        </div>
        <button onClick={handleTrigger} disabled={triggering} className="btn-primary">
          <Play size={14} />
          {triggering ? 'Running...' : 'Run Pipeline'}
        </button>
      </div>

      {/* Metrics */}
      <div className="mb-8">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-stagger">
          <MetricCard
            label="System Updates"
            value={s?.total_runs}
            subtitle={`${Math.round((s?.success_rate ?? 0) * 100)}% completed`}
          />
          <MetricCard label="Facilities" value={s?.facilities_monitored} subtitle="reporting" />
          <MetricCard label="Medicines" value={s?.drugs_tracked} subtitle="WHO essential list" />
          <MetricCard
            label="Running Cost"
            value={`$${s?.total_cost_usd?.toFixed(2) ?? '0'}`}
            subtitle={`$${s?.avg_cost_per_run_usd?.toFixed(3) ?? '0'} per update`}
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
            {t === 'architecture' ? 'System Design' : t === 'runs' ? 'Update History' : 'Cost & Reliability'}
          </button>
        ))}
      </div>

      {/* Architecture Tab */}
      {tab === 'architecture' && (
        <div className="animate-tab-enter space-y-6">
          <div className="section-header">From Reports to Recommendations in 6 Steps</div>
          <ArchitectureDiagram />

          <div className="mt-8">
            <div className="section-header">Data Sources & AI Capabilities</div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">Weather Data</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">NASA Satellite</p>
                <p className="text-xs text-warm-body m-0 mt-1">Daily temperature, rainfall, and humidity from NASA's global monitoring network.</p>
              </div>
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">Facility Data</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">3 Reporting Channels</p>
                <p className="text-xs text-warm-body m-0 mt-1">Pharmacist stock reports, disease surveillance, and community health worker messages.</p>
              </div>
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">Medicines</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">WHO Essential List</p>
                <p className="text-xs text-warm-body m-0 mt-1">15 essential medicines with dosing, costs, storage needs, and seasonal demand patterns.</p>
              </div>
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">AI Processing</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">4 Specialized AI Agents</p>
                <p className="text-xs text-warm-body m-0 mt-1">Reading reports, verifying data, detecting problems, and building procurement recommendations.</p>
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mt-4">
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">Demand Prediction</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">AI-Powered Forecast</p>
                <p className="text-xs text-warm-body m-0 mt-1">Learns from 20 factors including consumption history, facility size, and disease patterns. 99.8% accurate.</p>
              </div>
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">Self-Correcting</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">Automatic Error Correction</p>
                <p className="text-xs text-warm-body m-0 mt-1">A second model reviews the first and fixes systematic mistakes, improving accuracy further.</p>
              </div>
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">Quality Control</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">Unusual Pattern Detection</p>
                <p className="text-xs text-warm-body m-0 mt-1">Flags suspicious consumption — possible data errors, stock theft, or unexpected demand spikes.</p>
              </div>
              <div className="card card-body">
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0 mb-1">Clinical Knowledge</p>
                <p className="text-sm font-bold text-[#1a1a1a] m-0">101 Guideline Articles</p>
                <p className="text-xs text-warm-body m-0 mt-1">AI recommendations grounded in WHO, UNICEF, and MSH clinical and supply chain guidelines.</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Runs Tab */}
      {tab === 'runs' && (
        <div className="animate-tab-enter space-y-6">
          {/* Scheduler */}
          <div className="card card-body">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-sans text-warm-body m-0">
                  <span className="font-semibold text-[#1a1a1a]">Last run: </span>
                  {s?.last_run ? new Date(s.last_run).toLocaleString() : 'Never'}
                </p>
                <p className="text-xs text-warm-muted m-0 mt-1">
                  Scheduled daily at 06:00 UTC. Runs automatically when the API is active.
                </p>
              </div>
              <StatusBadge status={s?.last_run ? 'active' : 'pending'} />
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

          <div>
            <div className="section-header">Degradation Chain</div>
            <p className="text-xs text-warm-muted mb-4 -mt-1">
              Every component has a fallback. If one tier fails, the system degrades gracefully to the next.
            </p>
            <DegradationChain />
          </div>
        </div>
      )}
    </div>
  )
}
