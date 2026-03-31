import { useState, useMemo } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import MetricCard from '../components/MetricCard'
import StatusBadge from '../components/StatusBadge'
import { LoadingSpinner, ErrorState } from '../components/LoadingState'
import { useProcurementPlan, useFacilities } from '../lib/api'

function coverageColor(pct: number): string {
  if (pct >= 80) return '#2a9d8f'
  if (pct >= 50) return '#d4a019'
  if (pct >= 20) return '#e67e22'
  return '#e63946'
}

export default function Procurement() {
  const { data, isLoading, isError, refetch } = useProcurementPlan()
  const facilities = useFacilities()
  const [activeTab, setActiveTab] = useState<'plan' | 'reasoning'>('plan')
  const [expandedTraceRounds, setExpandedTraceRounds] = useState<
    Set<number>
  >(new Set())

  const plan = data?.plans?.[0] ?? null

  const facilityNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    facilities.data?.facilities?.forEach((f) => {
      map[f.facility_id] = f.name
    })
    return map
  }, [facilities.data])

  const sortedOrders = useMemo(() => {
    if (!plan?.orders) return []
    return [...plan.orders].sort((a, b) => {
      if (a.critical && !b.critical) return -1
      if (!a.critical && b.critical) return 1
      return 0
    })
  }, [plan])

  const toggleTraceRound = (round: number) => {
    setExpandedTraceRounds((prev) => {
      const next = new Set(prev)
      if (next.has(round)) {
        next.delete(round)
      } else {
        next.add(round)
      }
      return next
    })
  }

  if (isLoading) return <LoadingSpinner />
  if (isError) return <ErrorState onRetry={() => refetch()} />
  if (!plan) return null

  const budgetUsedPct =
    plan.budget_usd > 0
      ? (plan.budget_used_usd / plan.budget_usd) * 100
      : 0

  return (
    <div className="animate-slide-up">
      <div data-tour="procurement-title" className="pt-2 pb-6">
        <h1 className="page-title">Order Recommendation</h1>
        <p className="page-caption">
          What to order for the next {plan.planning_months} months of {plan.season} season, within the available budget
        </p>
      </div>

      {/* Budget summary bar */}
      <div className="mb-6 card card-body">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-6">
            <div>
              <span className="text-xs font-sans font-medium text-warm-muted uppercase tracking-wider">
                Total Budget
              </span>
              <p className="text-lg font-serif font-bold text-[#1a1a1a] m-0">
                ${plan.budget_usd.toLocaleString()}
              </p>
            </div>
            <div>
              <span className="text-xs font-sans font-medium text-warm-muted uppercase tracking-wider">
                Used
              </span>
              <p className="text-lg font-serif font-bold text-[#1a1a1a] m-0">
                ${plan.budget_used_usd.toLocaleString()}
              </p>
            </div>
            <div>
              <span className="text-xs font-sans font-medium text-warm-muted uppercase tracking-wider">
                Remaining
              </span>
              <p
                className="text-lg font-serif font-bold m-0"
                style={{
                  color:
                    plan.budget_remaining_usd > 0 ? '#2a9d8f' : '#e63946',
                }}
              >
                ${plan.budget_remaining_usd.toLocaleString()}
              </p>
            </div>
          </div>
          <span className="text-sm font-sans font-semibold text-warm-body">
            {Math.round(budgetUsedPct)}% allocated
          </span>
        </div>
        <div className="w-full h-3 bg-warm-header-bg rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${Math.min(budgetUsedPct, 100)}%`,
              backgroundColor:
                budgetUsedPct > 95
                  ? '#e63946'
                  : budgetUsedPct > 80
                    ? '#d4a019'
                    : '#2a9d8f',
            }}
          />
        </div>
      </div>

      <div data-tour="procurement-metrics" className="mb-8">
        <div className="section-header">Coverage Summary</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-stagger">
          <MetricCard
            label="Budget Used"
            value={`$${plan.budget_used_usd.toLocaleString()}`}
            subtitle={`of $${plan.budget_usd.toLocaleString()}`}
          />
          <MetricCard
            label="Fully Covered"
            value={plan.fully_covered}
            subtitle={`${plan.partially_covered} partial, ${plan.not_covered} uncovered`}
          />
          <MetricCard
            label="Stockout Risks"
            value={plan.stockout_risks}
            subtitle="drugs at risk"
          />
          <MetricCard
            label="Critical Coverage"
            value={`${plan.critical_drugs_covered}/${plan.critical_drugs_total}`}
            subtitle="critical drugs covered"
          />
        </div>
      </div>

      <div data-tour="procurement-tabs">
        <div className="tab-list mb-6">
          <button
            className={`tab-item ${activeTab === 'plan' ? 'active' : ''}`}
            onClick={() => setActiveTab('plan')}
          >
            Order Details
          </button>
          <button
            className={`tab-item ${activeTab === 'reasoning' ? 'active' : ''}`}
            onClick={() => setActiveTab('reasoning')}
          >
            AI Decisions
          </button>
        </div>

        {activeTab === 'plan' && (
          <div className="animate-tab-enter table-container">
            <table>
              <thead>
                <tr>
                  <th>Drug</th>
                  <th>Category</th>
                  <th>Critical</th>
                  <th>Total Need</th>
                  <th>Ordered</th>
                  <th>Unit Cost</th>
                  <th>Total Cost</th>
                  <th>Coverage</th>
                  <th>Stockout Risk</th>
                  <th>Days of Stock</th>
                </tr>
              </thead>
              <tbody>
                {sortedOrders.map((o) => (
                  <tr key={o.drug_id}>
                    <td className="font-semibold text-[#1a1a1a]">{o.name}</td>
                    <td>{o.category}</td>
                    <td>
                      {o.critical && (
                        <span className="badge-red">critical</span>
                      )}
                    </td>
                    <td>
                      {o.total_need.toLocaleString()} {o.unit}
                    </td>
                    <td>{o.ordered_qty.toLocaleString()}</td>
                    <td>${o.unit_cost_usd.toFixed(2)}</td>
                    <td className="font-semibold">
                      ${o.total_cost_usd.toFixed(2)}
                    </td>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className="w-14 h-2 bg-warm-header-bg rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full transition-all"
                            style={{
                              width: `${Math.min(o.coverage_pct, 100)}%`,
                              backgroundColor: coverageColor(o.coverage_pct),
                            }}
                          />
                        </div>
                        <span
                          className="text-xs font-semibold"
                          style={{
                            color: coverageColor(o.coverage_pct),
                          }}
                        >
                          {Math.round(o.coverage_pct)}%
                        </span>
                      </div>
                    </td>
                    <td>
                      <StatusBadge status={o.stockout_risk} />
                    </td>
                    <td>{o.days_of_stock}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === 'reasoning' && (
          <div className="animate-tab-enter space-y-6">
            {/* Optimization method badge */}
            <div className="flex items-center gap-3">
              {plan.optimization_method === 'claude_agent' ? (
                <span
                  className="text-xs font-sans font-semibold px-3 py-1 rounded-full"
                  style={{
                    backgroundColor: '#f3e8ff',
                    color: '#6b21a8',
                    border: '1px solid #c084fc',
                  }}
                >
                  AI-Optimized
                </span>
              ) : (
                <span
                  className="text-xs font-sans font-semibold px-3 py-1 rounded-full"
                  style={{
                    backgroundColor: '#f1f5f9',
                    color: '#475569',
                    border: '1px solid #cbd5e1',
                  }}
                >
                  Rule-Based
                </span>
              )}
              <span className="text-xs text-warm-muted">
                How the budget was allocated
              </span>
            </div>

            {/* Tool call trace */}
            {plan.reasoning_trace && plan.reasoning_trace.length > 0 && (
              <div>
                <div className="section-header">Decision Steps</div>
                <div className="space-y-2">
                  {plan.reasoning_trace.map((step, i) => (
                    <div
                      key={i}
                      className="bg-white border border-warm-border rounded-lg overflow-hidden"
                    >
                      <button
                        onClick={() => toggleTraceRound(i)}
                        className="w-full flex items-center gap-3 px-4 py-3 text-left bg-transparent border-none cursor-pointer hover:bg-warm-header-bg/50 transition-colors"
                      >
                        {expandedTraceRounds.has(i) ? (
                          <ChevronDown
                            size={14}
                            className="text-warm-muted shrink-0"
                          />
                        ) : (
                          <ChevronRight
                            size={14}
                            className="text-warm-muted shrink-0"
                          />
                        )}
                        <span
                          className="text-[0.7rem] font-mono px-2 py-0.5 rounded shrink-0"
                          style={{
                            backgroundColor: '#f3e8ff',
                            color: '#6b21a8',
                          }}
                        >
                          {step.tool}
                        </span>
                        <span className="text-xs text-warm-body truncate flex-1">
                          {step.result_summary}
                        </span>
                        <span className="text-[0.65rem] text-warm-muted shrink-0">
                          Round {step.round}
                        </span>
                      </button>
                      {expandedTraceRounds.has(i) && (
                        <div className="px-4 pb-3 pt-0 border-t border-warm-border/50">
                          <div className="grid grid-cols-2 gap-4 mt-2">
                            <div>
                              <p className="text-[0.65rem] font-sans font-semibold text-warm-muted uppercase tracking-wider mb-1">
                                Input
                              </p>
                              <pre className="text-xs text-warm-body bg-warm-header-bg rounded-md p-2 m-0 overflow-x-auto">
                                {JSON.stringify(step.input, null, 2)}
                              </pre>
                            </div>
                            <div>
                              <p className="text-[0.65rem] font-sans font-semibold text-warm-muted uppercase tracking-wider mb-1">
                                Output
                              </p>
                              <p className="text-xs text-warm-body leading-relaxed m-0">
                                {step.result_summary}
                              </p>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Redistributions table */}
            {plan.redistributions && plan.redistributions.length > 0 && (
              <div>
                <div className="section-header">Cross-Facility Redistributions</div>
                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>From</th>
                        <th>To</th>
                        <th>Drug</th>
                        <th>Quantity</th>
                        <th>Transit</th>
                        <th>Reasoning</th>
                      </tr>
                    </thead>
                    <tbody>
                      {plan.redistributions.map((r, i) => (
                        <tr key={i}>
                          <td className="text-xs font-semibold text-[#1a1a1a]">
                            {facilityNameMap[r.from_facility] ??
                              r.from_facility}
                          </td>
                          <td className="text-xs font-semibold text-[#1a1a1a]">
                            {facilityNameMap[r.to_facility] ?? r.to_facility}
                          </td>
                          <td className="text-xs">{r.drug_id}</td>
                          <td>{r.quantity.toLocaleString()}</td>
                          <td>{r.transit_days}d</td>
                          <td className="text-xs text-warm-body">
                            {r.reason}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Narrative reasoning */}
            {plan.agent_reasoning && (
              <div className="card card-body">
                <h3 className="text-sm font-semibold font-sans text-[#1a1a1a] mb-3">
                  Agent Narrative
                </h3>
                <div className="text-sm text-warm-body leading-relaxed whitespace-pre-wrap font-sans">
                  {plan.agent_reasoning}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
