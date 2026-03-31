import { useState, useMemo } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { MapContainer, TileLayer, CircleMarker, Polyline, Popup } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { ArrowRight } from 'lucide-react'
import MetricCard from '../components/MetricCard'
import { LoadingSpinner, ErrorState } from '../components/LoadingState'
import {
  useProcurementPlan,
  useFacilities,
  type ProcurementPlan,
} from '../lib/api'

// Fix Leaflet default icon issue with bundlers
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
})

// ── Facility coordinates (fallback when API doesn't include lat/lon) ─────
const FACILITY_COORDS: Record<string, [number, number]> = {
  'FAC-IKJ': [6.6018, 3.3515],
  'FAC-AJE': [6.45, 3.3333],
  'FAC-EPE': [6.5833, 3.9833],
  'FAC-KMC': [12.0, 8.5167],
  'FAC-UNG': [12.0833, 8.4833],
  'FAC-MAI': [11.8333, 13.15],
  'FAC-AMA': [5.56, -0.19],
  'FAC-GMA': [5.5333, -0.3],
  'FAC-KMA': [6.6884, -1.6244],
  'FAC-OBU': [6.2, -1.6667],
}

function urgencyColor(plan: ProcurementPlan | undefined): string {
  if (!plan) return '#888'
  const hasCriticalRisk = plan.orders?.some(
    (o) => o.critical && (o.stockout_risk === 'critical' || o.stockout_risk === 'high'),
  )
  if (hasCriticalRisk) return '#e63946'
  if (plan.stockout_risks > 0) return '#d4a019'
  return '#2a9d8f'
}

function coverageColor(pct: number): string {
  if (pct >= 80) return '#2a9d8f'
  if (pct >= 50) return '#d4a019'
  if (pct >= 20) return '#e67e22'
  return '#e63946'
}

const darkTooltipStyle = {
  backgroundColor: '#1a1a1a',
  border: 'none',
  borderRadius: 8,
  color: '#e0dcd5',
  fontFamily: '"DM Sans", sans-serif',
  fontSize: '0.8rem',
}

type Tab = 'overview' | 'action' | 'impact' | 'evidence'

// ── Main Component ───────────────────────────────────────────────────────

export default function Procurement() {
  const procurement = useProcurementPlan()
  const facilities = useFacilities()
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  const [selectedFacility, setSelectedFacility] = useState<string | null>(null)

  const plans = procurement.data?.plans ?? []
  const allFacilities = facilities.data?.facilities ?? []

  // Build plan lookup by facility_id
  const planMap = useMemo(() => {
    const m = new Map<string, ProcurementPlan>()
    for (const p of plans) {
      if (p.facility_id) m.set(p.facility_id, p)
    }
    return m
  }, [plans])

  // Facility name lookup
  const nameMap = useMemo(() => {
    const m: Record<string, string> = {}
    allFacilities.forEach((f) => { m[f.facility_id] = f.name })
    plans.forEach((p) => { if (p.facility_id && p.facility_name) m[p.facility_id] = p.facility_name })
    return m
  }, [allFacilities, plans])

  // Aggregate metrics across all plans
  const agg = useMemo(() => {
    let totalBudget = 0, totalUsed = 0, totalRisks = 0
    let critCovered = 0, critTotal = 0
    for (const p of plans) {
      totalBudget += p.budget_usd
      totalUsed += p.budget_used_usd
      totalRisks += p.stockout_risks
      critCovered += p.critical_drugs_covered
      critTotal += p.critical_drugs_total
    }
    return {
      totalBudget,
      totalUsed,
      totalRisks,
      critCovered,
      critTotal,
      facilitiesCount: Math.max(plans.length, allFacilities.length),
    }
  }, [plans, allFacilities])

  // All redistributions across plans
  const allRedistributions = useMemo(() => {
    return plans.flatMap((p) => p.redistributions ?? [])
  }, [plans])

  // Coverage chart data (aggregate orders across plans, dedupe by drug)
  const coverageData = useMemo(() => {
    const drugMap = new Map<string, { name: string; coverage: number; risk: string; critical: boolean }>()
    for (const p of plans) {
      for (const o of p.orders ?? []) {
        const existing = drugMap.get(o.drug_id)
        if (!existing || o.coverage_pct < existing.coverage) {
          drugMap.set(o.drug_id, {
            name: o.name.length > 20 ? o.name.slice(0, 18) + '...' : o.name,
            coverage: Math.round(o.coverage_pct),
            risk: o.stockout_risk,
            critical: o.critical,
          })
        }
      }
    }
    return Array.from(drugMap.values()).sort((a, b) => a.coverage - b.coverage)
  }, [plans])

  // First plan for reasoning/evidence (agent runs once across all facilities)
  const primaryPlan = plans[0] ?? null

  if (procurement.isLoading || facilities.isLoading) return <LoadingSpinner />
  if (procurement.isError) return <ErrorState onRetry={() => procurement.refetch()} />

  const tabs: { key: Tab; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'action', label: 'Action Plan' },
    { key: 'impact', label: 'Impact' },
    { key: 'evidence', label: 'Evidence' },
  ]

  return (
    <div className="animate-slide-up">
      <div data-tour="procurement-title" className="pt-2 pb-6">
        <h1 className="page-title">Recommendations</h1>
        <p className="page-caption">
          AI-generated procurement recommendations for {agg.facilitiesCount} facilities across Lagos State
        </p>
      </div>

      <div data-tour="procurement-tabs">
        <div className="tab-list mb-6">
          {tabs.map((t) => (
            <button
              key={t.key}
              className={`tab-item ${activeTab === t.key ? 'active' : ''}`}
              onClick={() => setActiveTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── TAB 1: OVERVIEW (MAP) — use display toggle to avoid remounting Leaflet ── */}
        <div className="space-y-6" style={{ display: activeTab === 'overview' ? 'block' : 'none' }}>
            {/* Map */}
            <div className="rounded-[10px] border border-warm-border overflow-hidden" style={{ height: 420 }}>
              <MapContainer
                center={[6.52, 3.45]}
                zoom={10}
                style={{ height: '100%', width: '100%' }}
                scrollWheelZoom={false}
                attributionControl={false}
              >
                <TileLayer
                  url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
                  attribution='&copy; <a href="https://carto.com/">CARTO</a>'
                />

                {/* Redistribution flow lines */}
                {allRedistributions.map((r, i) => {
                  const from = FACILITY_COORDS[r.from_facility]
                  const to = FACILITY_COORDS[r.to_facility]
                  if (!from || !to) return null
                  // Curved line via midpoint offset
                  const midLat = (from[0] + to[0]) / 2 + 0.5
                  const midLon = (from[1] + to[1]) / 2 + 0.5
                  return (
                    <Polyline
                      key={`flow-${i}`}
                      positions={[from, [midLat, midLon], to]}
                      pathOptions={{
                        color: '#d4a019',
                        weight: 2,
                        opacity: 0.7,
                        dashArray: '6 4',
                      }}
                    />
                  )
                })}

                {/* Facility markers */}
                {allFacilities.map((fac) => {
                  const coords = FACILITY_COORDS[fac.facility_id]
                  if (!coords) return null
                  const plan = planMap.get(fac.facility_id)
                  const color = urgencyColor(plan)
                  const isSelected = selectedFacility === fac.facility_id

                  return (
                    <CircleMarker
                      key={fac.facility_id}
                      center={coords}
                      radius={isSelected ? 12 : 8}
                      pathOptions={{
                        color: '#fff',
                        weight: 2,
                        fillColor: color,
                        fillOpacity: 0.9,
                      }}
                      eventHandlers={{
                        click: () => setSelectedFacility(fac.facility_id),
                      }}
                    >
                      <Popup>
                        <div style={{ fontFamily: '"DM Sans", sans-serif', minWidth: 200 }}>
                          <div style={{ fontFamily: '"Source Serif 4", serif', fontWeight: 700, fontSize: '0.95rem', marginBottom: 4 }}>
                            {fac.name}
                          </div>
                          <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: 8 }}>
                            {fac.district}, {fac.country} &middot; pop. {fac.population_served.toLocaleString()}
                          </div>
                          {plan ? (
                            <div style={{ fontSize: '0.8rem' }}>
                              {plan.orders
                                ?.filter((o) => o.critical || o.stockout_risk === 'high' || o.stockout_risk === 'critical')
                                .slice(0, 4)
                                .map((o) => (
                                  <div key={o.drug_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', borderBottom: '1px solid #f0ede8' }}>
                                    <span style={{ fontWeight: 500 }}>{o.name}</span>
                                    <span style={{ color: coverageColor(o.coverage_pct), fontWeight: 600, fontSize: '0.75rem' }}>
                                      {Math.round(o.coverage_pct)}%
                                    </span>
                                  </div>
                                ))}
                              {plan.stockout_risks > 0 && (
                                <div style={{ marginTop: 6, padding: '4px 8px', background: 'rgba(230,57,70,0.08)', borderRadius: 6, fontSize: '0.72rem', color: '#e63946' }}>
                                  {plan.stockout_risks} medicine{plan.stockout_risks > 1 ? 's' : ''} at risk
                                </div>
                              )}
                            </div>
                          ) : (
                            <div style={{ fontSize: '0.8rem', color: '#888' }}>No procurement plan available</div>
                          )}
                        </div>
                      </Popup>
                    </CircleMarker>
                  )
                })}
              </MapContainer>
            </div>

            {/* Legend */}
            <div className="flex items-center gap-5 text-xs text-warm-muted">
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded-full" style={{ background: '#2a9d8f' }} />
                Covered
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded-full" style={{ background: '#d4a019' }} />
                Some risk
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded-full" style={{ background: '#e63946' }} />
                Critical risk
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-6 border-t-2 border-dashed" style={{ borderColor: '#d4a019' }} />
                Stock redistribution
              </div>
            </div>

            {/* Metrics */}
            <div data-tour="procurement-metrics" className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-stagger">
              <MetricCard
                label="Facilities"
                value={agg.facilitiesCount}
                subtitle="across Lagos State"
              />
              <MetricCard
                label="Critical Coverage"
                value={`${agg.critCovered}/${agg.critTotal}`}
                subtitle="life-saving drugs covered"
              />
              <MetricCard
                label="Stockout Risks"
                value={agg.totalRisks}
                subtitle="medicines at risk"
              />
              <MetricCard
                label="Budget Allocated"
                value={`$${Math.round(agg.totalUsed).toLocaleString()}`}
                subtitle={`of $${Math.round(agg.totalBudget).toLocaleString()}`}
              />
            </div>

            {/* Redistributions summary */}
            {allRedistributions.length > 0 && (
              <div>
                <div className="section-header">Stock Redistributions</div>
                <p className="text-xs text-warm-body -mt-2 mb-3">
                  Instead of ordering new stock, the AI identified surplus at some facilities that can cover shortages at others.
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {allRedistributions.map((r, i) => (
                    <div key={i} className="card-accent accent-amber p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm font-semibold text-[#1a1a1a]">
                          {nameMap[r.from_facility] ?? r.from_facility}
                        </span>
                        <ArrowRight size={14} className="text-warm-muted" />
                        <span className="text-sm font-semibold text-[#1a1a1a]">
                          {nameMap[r.to_facility] ?? r.to_facility}
                        </span>
                      </div>
                      <div className="text-xs text-warm-body">
                        <span className="font-semibold">{r.quantity.toLocaleString()}</span> units of{' '}
                        <span className="font-mono text-[#1a1a1a]">{r.drug_id}</span>
                        {' '}&middot;{' '}{r.transit_days} day{r.transit_days > 1 ? 's' : ''} transit
                      </div>
                      <p className="text-xs text-warm-muted italic mt-1 m-0">{r.reason}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

        {/* ── TAB 2: ACTION PLAN ─────────────────────────────────────────── */}
        {activeTab === 'action' && (
          <div className="animate-tab-enter space-y-4">
            {plans.length === 0 && (
              <p className="text-sm text-warm-muted">No procurement plans available.</p>
            )}
            {plans.map((plan) => {
              const hasCriticalRisk = plan.orders?.some(
                (o) => o.critical && (o.stockout_risk === 'critical' || o.stockout_risk === 'high'),
              )
              const accentClass = hasCriticalRisk
                ? 'accent-red'
                : plan.stockout_risks > 0
                  ? 'accent-amber'
                  : 'accent-green'

              const facilityRedists = allRedistributions.filter(
                (r) => r.from_facility === plan.facility_id || r.to_facility === plan.facility_id,
              )

              const priorityOrders = [...(plan.orders ?? [])]
                .sort((a, b) => {
                  if (a.critical && !b.critical) return -1
                  if (!a.critical && b.critical) return 1
                  return a.coverage_pct - b.coverage_pct
                })
                .slice(0, 5)

              return (
                <div key={plan.facility_id} className={`card-accent ${accentClass} p-5`}>
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <h3 className="text-base font-serif font-bold text-[#1a1a1a] m-0">
                        {plan.facility_name}
                      </h3>
                      <p className="text-xs text-warm-muted mt-0.5 m-0">
                        Pop. {plan.population.toLocaleString()} &middot; Budget ${plan.budget_usd.toLocaleString()} &middot; {plan.season} season
                      </p>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-serif font-bold" style={{ color: coverageColor(Math.round((plan.budget_used_usd / Math.max(plan.budget_usd, 1)) * 100)) }}>
                        {Math.round((plan.budget_used_usd / Math.max(plan.budget_usd, 1)) * 100)}%
                      </div>
                      <div className="text-[10px] text-warm-muted uppercase tracking-wider">budget used</div>
                    </div>
                  </div>

                  {/* Priority orders */}
                  <div className="space-y-1.5 mb-3">
                    {priorityOrders.map((o) => (
                      <div key={o.drug_id} className="flex items-center gap-2 text-sm">
                        <div
                          className="w-1.5 h-1.5 rounded-full shrink-0"
                          style={{ background: coverageColor(o.coverage_pct) }}
                        />
                        <span className="text-warm-body flex-1">
                          <span className="font-semibold text-[#1a1a1a]">{o.name}</span>
                          {' '}&mdash;{' '}order {o.ordered_qty.toLocaleString()} {o.unit}
                        </span>
                        {o.critical && <span className="badge-red text-[0.6rem]">critical</span>}
                        <span className="text-xs font-semibold" style={{ color: coverageColor(o.coverage_pct) }}>
                          {Math.round(o.coverage_pct)}%
                        </span>
                      </div>
                    ))}
                  </div>

                  {/* Redistributions involving this facility */}
                  {facilityRedists.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-warm-border/50">
                      {facilityRedists.map((r, i) => {
                        const isReceiving = r.to_facility === plan.facility_id
                        return (
                          <div key={i} className="flex items-center gap-2 text-xs text-warm-body">
                            <span style={{ color: '#d4a019' }}>{isReceiving ? '← Receiving' : '→ Sending'}</span>
                            <span className="font-semibold">{r.quantity.toLocaleString()}</span> {r.drug_id}
                            {isReceiving
                              ? <> from {nameMap[r.from_facility] ?? r.from_facility}</>
                              : <> to {nameMap[r.to_facility] ?? r.to_facility}</>
                            }
                            <span className="text-warm-muted">({r.transit_days}d)</span>
                          </div>
                        )
                      })}
                    </div>
                  )}

                  {/* Clinical impact callout */}
                  {hasCriticalRisk && (
                    <div className="mt-3 p-2.5 rounded-md text-xs" style={{ background: 'rgba(230,57,70,0.06)', border: '1px solid rgba(230,57,70,0.15)' }}>
                      <span className="font-semibold" style={{ color: '#e63946' }}>Clinical impact risk:</span>{' '}
                      <span className="text-warm-body">
                        Without critical medicines, estimated 2-8 preventable deaths per 1,000 untreated cases (WHO/MSH guidelines)
                      </span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {/* ── TAB 3: IMPACT ──────────────────────────────────────────────── */}
        {activeTab === 'impact' && (
          <div className="animate-tab-enter space-y-6">
            {/* Before/After comparison */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 animate-stagger">
              <div className="card-accent accent-green p-5">
                <div className="text-[10px] uppercase tracking-wider text-warm-muted font-semibold mb-1">
                  Stockout Risks
                </div>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-serif font-bold" style={{ color: '#e63946' }}>
                    {agg.totalRisks}
                  </span>
                  <ArrowRight size={14} className="text-warm-muted" />
                  <span className="text-2xl font-serif font-bold" style={{ color: '#2a9d8f' }}>
                    {Math.max(0, agg.totalRisks - allRedistributions.length)}
                  </span>
                </div>
                <p className="text-xs text-warm-muted mt-1 m-0">
                  after recommendations applied
                </p>
              </div>

              <div className="card-accent accent-blue p-5">
                <div className="text-[10px] uppercase tracking-wider text-warm-muted font-semibold mb-1">
                  Critical Drug Coverage
                </div>
                <div className="text-2xl font-serif font-bold text-[#1a1a1a]">
                  {agg.critCovered}/{agg.critTotal}
                </div>
                <p className="text-xs text-warm-muted mt-1 m-0">
                  life-saving medicines fully funded
                </p>
              </div>

              <div className="card-accent accent-amber p-5">
                <div className="text-[10px] uppercase tracking-wider text-warm-muted font-semibold mb-1">
                  Budget Efficiency
                </div>
                <div className="text-2xl font-serif font-bold text-[#1a1a1a]">
                  {agg.totalBudget > 0 ? Math.round((agg.totalUsed / agg.totalBudget) * 100) : 0}%
                </div>
                <p className="text-xs text-warm-muted mt-1 m-0">
                  of available budget allocated
                </p>
              </div>
            </div>

            {/* Budget context */}
            {primaryPlan && (
              <div className="card card-body">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-warm-muted uppercase tracking-wider">
                    Total Budget Allocation
                  </span>
                  <span className="text-sm font-semibold text-[#1a1a1a]">
                    ${Math.round(agg.totalUsed).toLocaleString()} of ${Math.round(agg.totalBudget).toLocaleString()}
                  </span>
                </div>
                <div className="w-full h-3 bg-warm-header-bg rounded-full overflow-hidden mb-2">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${Math.min(100, agg.totalBudget > 0 ? (agg.totalUsed / agg.totalBudget) * 100 : 0)}%`,
                      backgroundColor: '#2a9d8f',
                    }}
                  />
                </div>
                <p className="text-xs text-warm-body m-0">
                  {agg.totalBudget - agg.totalUsed > 0
                    ? `$${Math.round(agg.totalBudget - agg.totalUsed).toLocaleString()} remaining — non-critical medicines may be partially funded`
                    : 'Budget fully allocated across all facilities'}
                </p>
              </div>
            )}

            {/* Coverage by drug */}
            {coverageData.length > 0 && (
              <div>
                <div className="section-header">Coverage by Medicine</div>
                <div className="card card-body">
                  <div style={{ width: '100%', height: Math.max(300, coverageData.length * 28) }}>
                    <ResponsiveContainer>
                      <BarChart
                        data={coverageData}
                        layout="vertical"
                        margin={{ top: 5, right: 30, bottom: 5, left: 140 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#e0dcd5" />
                        <XAxis
                          type="number"
                          tick={{ fontSize: 11, fill: '#888' }}
                          domain={[0, 100]}
                          unit="%"
                        />
                        <YAxis
                          type="category"
                          dataKey="name"
                          tick={{ fontSize: 10, fill: '#555' }}
                          width={130}
                        />
                        <Tooltip
                          contentStyle={darkTooltipStyle}
                          formatter={(value: number) => [`${value}%`, 'Coverage']}
                        />
                        <Bar dataKey="coverage" radius={[0, 4, 4, 0]}>
                          {coverageData.map((entry, i) => (
                            <Cell key={i} fill={coverageColor(entry.coverage)} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── TAB 4: EVIDENCE ────────────────────────────────────────────── */}
        {activeTab === 'evidence' && (
          <div className="animate-tab-enter space-y-6">
            {/* Optimization method */}
            {primaryPlan && (
              <div className="flex items-center gap-3">
                {primaryPlan.optimization_method === 'claude_agent' ? (
                  <span className="text-xs font-sans font-semibold px-3 py-1 rounded-full"
                    style={{ backgroundColor: 'rgba(42,157,143,0.12)', color: '#2a9d8f', border: '1px solid rgba(42,157,143,0.35)' }}>
                    AI-Optimized
                  </span>
                ) : (
                  <span className="text-xs font-sans font-semibold px-3 py-1 rounded-full"
                    style={{ backgroundColor: '#f1f5f9', color: '#475569', border: '1px solid #cbd5e1' }}>
                    Rule-Based
                  </span>
                )}
                <span className="text-xs text-warm-muted">
                  How the budget was allocated across {plans.length} facilities
                </span>
              </div>
            )}

            {/* Agent reasoning narrative */}
            {primaryPlan?.agent_reasoning && (
              <div className="card-accent accent-green p-5">
                <h3 className="text-sm font-semibold font-sans text-[#1a1a1a] mb-2">
                  AI Reasoning
                </h3>
                <div className="text-sm text-warm-body leading-relaxed whitespace-pre-wrap">
                  {primaryPlan.agent_reasoning}
                </div>
              </div>
            )}

            {/* Decision steps */}
            {primaryPlan?.reasoning_trace && primaryPlan.reasoning_trace.length > 0 && (
              <div>
                <div className="section-header">Decision Steps</div>
                <div className="space-y-2">
                  {primaryPlan.reasoning_trace.map((step, i) => (
                    <div key={i} className="card card-body flex items-start gap-3">
                      <div
                        className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0 mt-0.5"
                        style={{ background: '#2a9d8f' }}
                      >
                        {step.round}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-[0.7rem] font-mono px-2 py-0.5 rounded"
                            style={{ backgroundColor: 'rgba(42,157,143,0.1)', color: '#2a9d8f' }}>
                            {step.tool}
                          </span>
                        </div>
                        <p className="text-sm text-warm-body m-0 leading-relaxed">
                          {step.result_summary}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Redistributions table */}
            {allRedistributions.length > 0 && (
              <div>
                <div className="section-header">Cross-Facility Redistributions</div>
                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>From</th>
                        <th>To</th>
                        <th>Medicine</th>
                        <th>Quantity</th>
                        <th>Transit</th>
                        <th>Reasoning</th>
                      </tr>
                    </thead>
                    <tbody>
                      {allRedistributions.map((r, i) => (
                        <tr key={i}>
                          <td className="text-xs font-semibold text-[#1a1a1a]">
                            {nameMap[r.from_facility] ?? r.from_facility}
                          </td>
                          <td className="text-xs font-semibold text-[#1a1a1a]">
                            {nameMap[r.to_facility] ?? r.to_facility}
                          </td>
                          <td className="text-xs font-mono">{r.drug_id}</td>
                          <td>{r.quantity.toLocaleString()}</td>
                          <td>{r.transit_days} day{r.transit_days > 1 ? 's' : ''}</td>
                          <td className="text-xs text-warm-body">{r.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
