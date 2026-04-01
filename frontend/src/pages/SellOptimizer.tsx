import { useState, useMemo } from 'react'
import { MapContainer, TileLayer, CircleMarker, Polyline, Popup } from 'react-leaflet'
import '../lib/leaflet-fix'
import { ChevronDown, ChevronRight } from 'lucide-react'
import MetricCard from '../components/MetricCard'
import { LoadingSpinner, ErrorState } from '../components/LoadingState'
import { useSellRecommendations, useMandis, type SellRecommendation } from '../lib/api'
import { formatRs } from '../lib/format'

function netPriceColor(net: number, best: number): string {
  if (net >= best * 0.95) return '#2a9d8f'
  if (net >= best * 0.85) return '#d4a019'
  return '#e63946'
}

export default function SellOptimizer() {
  const recommendations = useSellRecommendations()
  const mandis = useMandis()
  const [selectedFarmer, setSelectedFarmer] = useState<number>(0)
  const [expandedReasoning, setExpandedReasoning] = useState<number | null>(null)

  const recs = recommendations.data?.sell_recommendations ?? []
  const allMandis = mandis.data?.mandis ?? []

  // ── Mandi coordinate lookup ─────────────────────────────────────────────
  const mandiCoords = useMemo(() => {
    const m = new Map<string, [number, number]>()
    for (const mandi of allMandis) {
      m.set(mandi.mandi_id, [mandi.latitude, mandi.longitude])
    }
    return m
  }, [allMandis])

  // ── Aggregate metrics ───────────────────────────────────────────────────
  const metrics = useMemo(() => {
    if (!recs.length) return { farmers: 0, bestGain: 0, avgImprovement: 0, markets: 0 }
    const bestGain = Math.max(...recs.map((r) => r.potential_gain_rs))
    const avgImprovement = recs.reduce((s, r) => {
      const worst = Math.min(...r.all_options.map((o) => o.net_price_rs))
      const best = r.best_option.net_price_rs
      return s + (worst > 0 ? ((best - worst) / worst) * 100 : 0)
    }, 0) / recs.length
    const marketsSet = new Set<string>()
    recs.forEach((r) => r.all_options.forEach((o) => marketsSet.add(o.mandi_id)))
    return { farmers: recs.length, bestGain, avgImprovement: Math.round(avgImprovement), markets: marketsSet.size }
  }, [recs])

  const activeFarmer: SellRecommendation | null = recs[selectedFarmer] ?? null

  // ── Sort options by net price descending ────────────────────────────────
  const sortedOptions = useMemo(() => {
    if (!activeFarmer) return []
    return [...activeFarmer.all_options].sort((a, b) => b.net_price_rs - a.net_price_rs)
  }, [activeFarmer])

  const bestNetPrice = sortedOptions[0]?.net_price_rs ?? 0

  if (recommendations.isLoading) return <LoadingSpinner />
  if (recommendations.isError) return <ErrorState onRetry={() => recommendations.refetch()} />

  return (
    <div className="animate-slide-up">
      <div data-tour="sell-title" className="pt-2 pb-6">
        <h1 className="page-title">Sell Advisor</h1>
        <p className="page-caption">
          Your AI broker finds the best deal
        </p>
      </div>

      {/* ── Metric cards ───────────────────────────────────────────────── */}
      <div data-tour="sell-metrics" className="mb-8">
        <div className="section-header">Overview</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-stagger">
          <MetricCard
            label="Farmers Analyzed"
            value={metrics.farmers}
            subtitle="sample recommendations"
          />
          <MetricCard
            label="Best Potential Gain"
            value={formatRs(metrics.bestGain)}
            subtitle="per quintal vs nearest"
          />
          <MetricCard
            label="Avg Net Improvement"
            value={`${metrics.avgImprovement}%`}
            subtitle="best vs worst option"
          />
          <MetricCard
            label="Markets Compared"
            value={metrics.markets}
            subtitle="mandis evaluated"
          />
        </div>
      </div>

      {/* ── Farmer cards ───────────────────────────────────────────────── */}
      <div className="mb-8">
        <div className="section-header">Farmer Recommendations</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {recs.map((rec, idx) => {
            const isActive = selectedFarmer === idx
            const isExpanded = expandedReasoning === idx
            const nearest = [...rec.all_options].sort((a, b) => a.distance_km - b.distance_km)[0]
            const gainVsNearest = nearest
              ? rec.best_option.net_price_rs - nearest.net_price_rs
              : rec.potential_gain_rs
            const gainPct = nearest && nearest.net_price_rs > 0
              ? Math.round((gainVsNearest / nearest.net_price_rs) * 100)
              : 0

            return (
              <div
                key={idx}
                className={`card-accent p-5 cursor-pointer ${isActive ? 'accent-amber' : 'accent-green'}`}
                style={isActive ? { borderLeftWidth: 4 } : undefined}
                onClick={() => setSelectedFarmer(idx)}
              >
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <h3 className="text-base font-serif font-bold text-[#1a1a1a] m-0">
                      {rec.farmer_name}
                    </h3>
                    <p className="text-xs text-warm-muted mt-0.5 m-0">
                      {rec.commodity_name} &middot; {rec.quantity_quintals} quintals
                    </p>
                  </div>
                </div>

                {/* Best option */}
                <div className="mt-3 p-3 rounded-lg" style={{ background: 'rgba(42,157,143,0.06)', border: '1px solid rgba(42,157,143,0.15)' }}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-warm-muted">Best option</span>
                    <span className="text-xs font-semibold" style={{ color: '#2a9d8f' }}>
                      {rec.best_option.mandi_name}
                    </span>
                  </div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-warm-muted">Timing</span>
                    <span className="text-xs font-semibold text-[#1a1a1a]">{rec.best_option.sell_timing}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-warm-muted">Net price</span>
                    <span className="text-sm font-serif font-bold" style={{ color: '#2a9d8f' }}>
                      {formatRs(rec.best_option.net_price_rs)}/q
                    </span>
                  </div>
                </div>

                {/* Gain vs nearest */}
                {gainVsNearest > 0 && (
                  <div className="mt-2 text-xs font-semibold" style={{ color: '#2a9d8f' }}>
                    +{formatRs(gainVsNearest)}/quintal (+{gainPct}%) vs nearest mandi
                  </div>
                )}

                {/* Collapsible recommendation text */}
                <button
                  className="mt-3 flex items-center gap-1 text-xs font-sans font-medium text-warm-muted hover:text-[#1a1a1a] transition-colors bg-transparent border-none cursor-pointer p-0"
                  onClick={(e) => { e.stopPropagation(); setExpandedReasoning(isExpanded ? null : idx) }}
                >
                  {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  AI recommendation
                </button>
                {isExpanded && (
                  <div className="mt-2 space-y-2 animate-tab-enter">
                    <p className="text-xs text-warm-body leading-relaxed m-0">
                      {rec.recommendation_text}
                    </p>
                    {rec.recommendation_tamil && (
                      <p className="text-xs text-warm-muted leading-relaxed m-0 italic">
                        {rec.recommendation_tamil}
                      </p>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Credit Readiness ─────────────────────────────────────────── */}
      {activeFarmer?.credit_readiness && (
        <div className="mb-8">
          <div className="section-header">{activeFarmer.farmer_name} — Credit Readiness</div>
          {(() => {
            const cr = activeFarmer.credit_readiness
            const readinessColor = cr.readiness === 'strong' ? '#2a9d8f' : cr.readiness === 'moderate' ? '#d4a019' : '#e63946'
            const readinessLabel = cr.readiness === 'strong' ? 'Strong' : cr.readiness === 'moderate' ? 'Moderate' : 'Not Yet'
            return (
              <div className="card-accent p-5" style={{ borderLeftColor: readinessColor, borderLeftWidth: 4 }}>
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: readinessColor }}>
                      {readinessLabel}
                    </span>
                    <p className="text-sm text-warm-body mt-1 leading-relaxed" style={{ maxWidth: 560 }}>
                      {cr.advice_en}
                    </p>
                  </div>
                  <div className="text-right ml-6 shrink-0">
                    <div className="text-xs text-warm-muted">Expected revenue</div>
                    <div className="text-lg font-serif font-bold" style={{ color: '#1a1a1a' }}>
                      {formatRs(cr.expected_revenue_rs)}
                    </div>
                    <div className="text-xs text-warm-muted mt-1">Max advisable loan</div>
                    <div className="text-base font-serif font-semibold" style={{ color: readinessColor }}>
                      {formatRs(cr.max_advisable_input_loan_rs)}
                    </div>
                  </div>
                </div>
                {(cr.strengths.length > 0 || cr.risks.length > 0) && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3 pt-3 border-t border-warm-border">
                    {cr.strengths.length > 0 && (
                      <div>
                        <div className="text-xs font-semibold text-warm-muted mb-1.5">Strengths</div>
                        <ul className="space-y-1">
                          {cr.strengths.map((s, i) => (
                            <li key={i} className="flex items-start gap-1.5 text-xs text-warm-body">
                              <span style={{ color: '#2a9d8f', flexShrink: 0 }}>✓</span> {s}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {cr.risks.length > 0 && (
                      <div>
                        <div className="text-xs font-semibold text-warm-muted mb-1.5">Risks</div>
                        <ul className="space-y-1">
                          {cr.risks.map((r, i) => (
                            <li key={i} className="flex items-start gap-1.5 text-xs text-warm-body">
                              <span style={{ color: '#e63946', flexShrink: 0 }}>!</span> {r}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })()}
        </div>
      )}

      {/* ── Map: farmer + mandis with routes ───────────────────────────── */}
      {activeFarmer && (
        <div className="mb-8">
          <div className="section-header">{activeFarmer.farmer_name} \u2014 Sell Options Map</div>
          <div className="rounded-[10px] border border-warm-border overflow-hidden" style={{ height: 400 }}>
            <MapContainer
              center={[activeFarmer.farmer_lat, activeFarmer.farmer_lon]}
              zoom={9}
              style={{ height: '100%', width: '100%' }}
              scrollWheelZoom={false}
              attributionControl={false}
            >
              <TileLayer
                url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
                attribution='&copy; <a href="https://carto.com/">CARTO</a>'
              />

              {/* Route lines from farmer to each mandi */}
              {activeFarmer.all_options.map((opt, i) => {
                const mandiPos = mandiCoords.get(opt.mandi_id)
                if (!mandiPos) return null
                return (
                  <Polyline
                    key={`route-${i}`}
                    positions={[
                      [activeFarmer.farmer_lat, activeFarmer.farmer_lon],
                      mandiPos,
                    ]}
                    pathOptions={{
                      color: netPriceColor(opt.net_price_rs, bestNetPrice),
                      weight: opt.mandi_id === activeFarmer.best_option.mandi_id ? 3 : 1.5,
                      opacity: opt.mandi_id === activeFarmer.best_option.mandi_id ? 0.9 : 0.4,
                      dashArray: opt.mandi_id === activeFarmer.best_option.mandi_id ? undefined : '6 4',
                    }}
                  />
                )
              })}

              {/* Mandi markers */}
              {activeFarmer.all_options.map((opt) => {
                const mandiPos = mandiCoords.get(opt.mandi_id)
                if (!mandiPos) return null
                const isBest = opt.mandi_id === activeFarmer.best_option.mandi_id
                return (
                  <CircleMarker
                    key={opt.mandi_id}
                    center={mandiPos}
                    radius={isBest ? 10 : 7}
                    pathOptions={{
                      color: '#fff',
                      weight: 2,
                      fillColor: netPriceColor(opt.net_price_rs, bestNetPrice),
                      fillOpacity: 0.9,
                    }}
                  >
                    <Popup>
                      <div style={{ fontFamily: '"DM Sans", sans-serif', minWidth: 180 }}>
                        <div style={{ fontFamily: '"Source Serif 4", serif', fontWeight: 700, fontSize: '0.95rem', marginBottom: 4 }}>
                          {opt.mandi_name}
                        </div>
                        <div style={{ fontSize: '0.8rem' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                            <span style={{ color: '#888' }}>Timing</span>
                            <span style={{ fontWeight: 600 }}>{opt.sell_timing}</span>
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                            <span style={{ color: '#888' }}>Market price</span>
                            <span>{formatRs(opt.market_price_rs)}</span>
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                            <span style={{ color: '#888' }}>Transport</span>
                            <span style={{ color: '#e63946' }}>-{formatRs(opt.transport_cost_rs)}</span>
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', borderTop: '1px solid #eee', marginTop: 4, paddingTop: 4 }}>
                            <span style={{ fontWeight: 600 }}>Net price</span>
                            <span style={{ fontWeight: 700, color: '#2a9d8f' }}>{formatRs(opt.net_price_rs)}/q</span>
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                            <span style={{ color: '#888' }}>Distance</span>
                            <span>{opt.distance_km.toFixed(0)} km ({opt.drive_time_min} min)</span>
                          </div>
                        </div>
                      </div>
                    </Popup>
                  </CircleMarker>
                )
              })}

              {/* Farmer marker (distinct style) */}
              <CircleMarker
                center={[activeFarmer.farmer_lat, activeFarmer.farmer_lon]}
                radius={10}
                pathOptions={{
                  color: '#d4a019',
                  weight: 3,
                  fillColor: '#fff',
                  fillOpacity: 1,
                }}
              >
                <Popup>
                  <div style={{ fontFamily: '"DM Sans", sans-serif' }}>
                    <div style={{ fontFamily: '"Source Serif 4", serif', fontWeight: 700, fontSize: '0.95rem' }}>
                      {activeFarmer.farmer_name}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: '#888', marginTop: 2 }}>
                      {activeFarmer.commodity_name} &middot; {activeFarmer.quantity_quintals} quintals
                    </div>
                  </div>
                </Popup>
              </CircleMarker>
            </MapContainer>
          </div>

          {/* Map legend */}
          <div className="flex items-center gap-5 mt-3 text-xs text-warm-muted">
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full border-2" style={{ borderColor: '#d4a019', background: '#fff' }} />
              Farmer
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full" style={{ background: '#2a9d8f' }} />
              Best net price
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full" style={{ background: '#d4a019' }} />
              Mid range
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-full" style={{ background: '#e63946' }} />
              Worst net price
            </div>
          </div>
        </div>
      )}

      {/* ── Options table ──────────────────────────────────────────────── */}
      {activeFarmer && sortedOptions.length > 0 && (
        <div className="mb-8">
          <div className="section-header">{activeFarmer.farmer_name} \u2014 All Options Ranked</div>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Mandi</th>
                  <th>Timing</th>
                  <th>Market Price</th>
                  <th>Transport</th>
                  <th>Storage Loss</th>
                  <th>Mandi Fee</th>
                  <th>Net Price</th>
                  <th>Distance</th>
                </tr>
              </thead>
              <tbody>
                {sortedOptions.map((opt, idx) => {
                  const isBest = idx === 0
                  return (
                    <tr
                      key={`${opt.mandi_id}-${opt.sell_timing}`}
                      className={isBest ? '!bg-emerald-50/40' : ''}
                    >
                      <td>
                        {isBest ? (
                          <span className="badge-green text-[0.65rem]">Best</span>
                        ) : (
                          <span className="text-xs text-warm-muted">#{idx + 1}</span>
                        )}
                      </td>
                      <td className="font-semibold text-[#1a1a1a]">{opt.mandi_name}</td>
                      <td>{opt.sell_timing}</td>
                      <td>{formatRs(opt.market_price_rs)}</td>
                      <td className="text-xs" style={{ color: '#e63946' }}>-{formatRs(opt.transport_cost_rs)}</td>
                      <td className="text-xs" style={{ color: '#e63946' }}>-{formatRs(opt.storage_loss_rs)}</td>
                      <td className="text-xs" style={{ color: '#e63946' }}>-{formatRs(opt.mandi_fee_rs)}</td>
                      <td>
                        <span className="font-semibold" style={{ color: netPriceColor(opt.net_price_rs, bestNetPrice) }}>
                          {formatRs(opt.net_price_rs)}
                        </span>
                      </td>
                      <td className="text-xs text-warm-muted">
                        {opt.distance_km.toFixed(0)} km
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
