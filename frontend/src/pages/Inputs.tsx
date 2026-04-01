import { useMemo } from 'react'
import MetricCard from '../components/MetricCard'
import { LoadingSpinner, ErrorState } from '../components/LoadingState'
import {
  usePriceConflicts,
  useMarketPrices,
  usePipelineStats,
} from '../lib/api'
import { formatRs } from '../lib/format'

function deltaPctColor(pct: number): string {
  if (pct >= 10) return '#e63946'
  if (pct >= 5) return '#d4a019'
  return '#2a9d8f'
}

export default function Inputs() {
  const conflicts = usePriceConflicts()
  const prices = useMarketPrices()
  const stats = usePipelineStats()

  const conflictList = conflicts.data?.price_conflicts ?? []
  const totalPrices = prices.data?.total ?? 0
  const totalConflicts = conflicts.data?.total ?? 0

  // ── Pick a sample conflict for the side-by-side view ────────────────────
  const sampleConflict = conflictList[0] ?? null

  // ── Find matching price records for the sample conflict ─────────────────
  const samplePrices = useMemo(() => {
    if (!sampleConflict || !prices.data?.market_prices) return []
    return prices.data.market_prices.filter(
      (p) => p.mandi_id === sampleConflict.mandi_id && p.commodity_id === sampleConflict.commodity_id,
    )
  }, [sampleConflict, prices.data])

  // ── Metrics ─────────────────────────────────────────────────────────────
  const sourcesCount = (stats.data?.data_sources ?? []).length || 2
  const resolutionRate = totalConflicts > 0
    ? Math.round((conflictList.filter((c) => c.reconciled_price > 0).length / totalConflicts) * 100)
    : 100

  if (conflicts.isLoading || prices.isLoading) return <LoadingSpinner />
  if (conflicts.isError) return <ErrorState onRetry={() => conflicts.refetch()} />

  return (
    <div className="animate-slide-up">
      <div data-tour="inputs-title" className="pt-2 pb-6">
        <h1 className="page-title">Data Sources</h1>
        <p className="page-caption">
          How conflicting government data gets reconciled into a single trusted price
        </p>
      </div>

      {/* ── Metrics ───────────────────────────────────────────────────────── */}
      <div data-tour="inputs-metrics" className="mb-8">
        <div className="section-header">Data Overview</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-stagger">
          <MetricCard
            label="Price Records"
            value={totalPrices}
            subtitle="scraped today"
          />
          <MetricCard
            label="Sources"
            value={sourcesCount}
            subtitle="Agmarknet + eNAM"
          />
          <MetricCard
            label="Conflicts Found"
            value={totalConflicts}
            subtitle="price discrepancies"
          />
          <MetricCard
            label="Resolution Rate"
            value={`${resolutionRate}%`}
            subtitle="auto-reconciled"
          />
        </div>
      </div>

      {/* ── Side-by-side: Raw vs Reconciled ────────────────────────────────── */}
      {sampleConflict && (
        <div data-tour="inputs-reconciled" className="mb-8">
          <div className="section-header">Example: Price Reconciliation</div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            {/* LEFT: Raw conflicting data */}
            <div className="space-y-4">
              <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0">
                Raw Data (Conflicting)
              </p>

              {/* Agmarknet report */}
              <div
                className="rounded-lg p-5"
                style={{
                  backgroundColor: '#fefae0',
                  border: '1px solid #d4c89a',
                  boxShadow: '2px 2px 8px rgba(0,0,0,0.06)',
                }}
              >
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold text-[#1a1a1a] uppercase tracking-wider">Agmarknet</span>
                  <span className="badge-amber text-[0.65rem]">Source A</span>
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-warm-muted">Mandi</span>
                    <span className="font-semibold text-[#1a1a1a]">{sampleConflict.mandi_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-warm-muted">Commodity</span>
                    <span className="font-semibold text-[#1a1a1a]">{sampleConflict.commodity_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-warm-muted">Price</span>
                    <span className="font-serif font-bold text-lg text-[#1a1a1a]">
                      {formatRs(sampleConflict.agmarknet_price)}
                    </span>
                  </div>
                </div>
              </div>

              {/* eNAM report */}
              <div
                className="rounded-lg p-5"
                style={{
                  backgroundColor: '#f0f4ff',
                  border: '1px solid #b8c9e8',
                  boxShadow: '2px 2px 8px rgba(0,0,0,0.04)',
                }}
              >
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold text-[#1a1a1a] uppercase tracking-wider">eNAM</span>
                  <span className="badge-blue text-[0.65rem]">Source B</span>
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-warm-muted">Mandi</span>
                    <span className="font-semibold text-[#1a1a1a]">{sampleConflict.mandi_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-warm-muted">Commodity</span>
                    <span className="font-semibold text-[#1a1a1a]">{sampleConflict.commodity_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-warm-muted">Price</span>
                    <span className="font-serif font-bold text-lg text-[#1a1a1a]">
                      {formatRs(sampleConflict.enam_price)}
                    </span>
                  </div>
                </div>
              </div>

              {/* Delta callout */}
              <div
                className="rounded-lg p-3 text-center"
                style={{
                  background: 'rgba(230, 57, 70, 0.06)',
                  border: '1px solid rgba(230, 57, 70, 0.2)',
                }}
              >
                <span className="text-xs text-warm-muted">Price difference: </span>
                <span className="text-sm font-serif font-bold" style={{ color: deltaPctColor(sampleConflict.delta_pct) }}>
                  {sampleConflict.delta_pct.toFixed(1)}%
                </span>
                <span className="text-xs text-warm-muted">
                  {' '}({formatRs(Math.abs(sampleConflict.agmarknet_price - sampleConflict.enam_price))})
                </span>
              </div>
            </div>

            {/* RIGHT: Reconciled result */}
            <div className="space-y-4">
              <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0">
                AI Reconciled
              </p>

              <div
                className="rounded-lg p-5"
                style={{
                  backgroundColor: '#f0faf8',
                  border: '2px solid #2a9d8f',
                }}
              >
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#2a9d8f' }}>
                    Reconciled Price
                  </span>
                  <span className="badge-green text-[0.65rem]">{sampleConflict.resolution}</span>
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-warm-muted">Mandi</span>
                    <span className="font-semibold text-[#1a1a1a]">{sampleConflict.mandi_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-warm-muted">Commodity</span>
                    <span className="font-semibold text-[#1a1a1a]">{sampleConflict.commodity_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-warm-muted">Final price</span>
                    <span className="font-serif font-bold text-xl" style={{ color: '#2a9d8f' }}>
                      {formatRs(sampleConflict.reconciled_price)}
                    </span>
                  </div>
                </div>
              </div>

              {/* Investigation steps */}
              {(sampleConflict as Record<string, unknown>).investigation_steps && (
                <div className="card-accent accent-amber p-4">
                  <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider mb-3 m-0">
                    Agent Investigation
                  </p>
                  <div className="space-y-2.5">
                    {((sampleConflict as Record<string, unknown>).investigation_steps as Array<{tool: string; finding: string}>).map((step, i) => (
                      <div key={i} className="flex gap-2">
                        <span className="shrink-0 mt-0.5 w-5 h-5 rounded flex items-center justify-center text-[0.6rem] font-bold" style={{ background: 'rgba(212,160,25,0.15)', color: '#d4a019' }}>
                          {i + 1}
                        </span>
                        <div>
                          <span className="text-[0.7rem] font-mono font-semibold text-warm-muted">{step.tool}</span>
                          <p className="text-xs text-warm-body leading-relaxed m-0 mt-0.5">{step.finding}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 pt-3 border-t border-warm-border">
                    <p className="text-xs font-semibold m-0" style={{ color: '#2a9d8f' }}>
                      Decision: {sampleConflict.reasoning}
                    </p>
                  </div>
                </div>
              )}

              {/* Fallback: plain reasoning if no investigation steps */}
              {!(sampleConflict as Record<string, unknown>).investigation_steps && (
                <div className="card-accent accent-amber p-4">
                  <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider mb-2 m-0">
                    AI Reasoning
                  </p>
                  <p className="text-sm text-warm-body leading-relaxed m-0">
                    {sampleConflict.reasoning}
                  </p>
                </div>
              )}

              {/* Related prices for this mandi/commodity */}
              {samplePrices.length > 0 && (
                <div className="card card-body">
                  <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider mb-2 m-0">
                    Full Price Record
                  </p>
                  <div className="space-y-1.5 text-sm">
                    {samplePrices.map((p, i) => (
                      <div key={i} className="flex justify-between">
                        <span className="text-warm-muted">{p.date}</span>
                        <span className="font-semibold text-[#1a1a1a]">{formatRs(p.reconciled_price_rs)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── All Conflicts ──────────────────────────────────────────────────── */}
      <div className="mb-8">
        <div className="section-header">All Price Conflicts</div>
        {conflictList.length === 0 ? (
          <p className="text-sm text-warm-muted font-sans">No price conflicts detected.</p>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Mandi</th>
                  <th>Commodity</th>
                  <th>Agmarknet</th>
                  <th>eNAM</th>
                  <th>Delta</th>
                  <th>Resolution</th>
                  <th>Reconciled</th>
                  <th>Reasoning</th>
                </tr>
              </thead>
              <tbody>
                {conflictList.map((c, i) => (
                  <tr key={`${c.mandi_id}-${c.commodity_id}-${i}`}>
                    <td className="font-semibold text-[#1a1a1a]">{c.mandi_name}</td>
                    <td>{c.commodity_name}</td>
                    <td>{formatRs(c.agmarknet_price)}</td>
                    <td>{formatRs(c.enam_price)}</td>
                    <td>
                      <span className="font-semibold" style={{ color: deltaPctColor(c.delta_pct) }}>
                        {c.delta_pct.toFixed(1)}%
                      </span>
                    </td>
                    <td>
                      <span className="badge-amber text-[0.65rem]">{c.resolution}</span>
                    </td>
                    <td className="font-semibold" style={{ color: '#2a9d8f' }}>
                      {formatRs(c.reconciled_price)}
                    </td>
                    <td className="text-xs text-warm-body max-w-xs">
                      {c.reasoning.length > 100 ? c.reasoning.slice(0, 100) + '\u2026' : c.reasoning}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
