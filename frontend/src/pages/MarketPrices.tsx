import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  FileText,
  TrendingUp,
  IndianRupee,
  ArrowRight,
} from 'lucide-react'
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet'
import '../lib/leaflet-fix'
import MetricCard from '../components/MetricCard'
import { DashboardSkeleton, ErrorState } from '../components/LoadingState'
import {
  usePipelineStats,
  useMarketPrices,
  useMandis,
  usePriceConflicts,
} from '../lib/api'
import { formatRs, directionArrow } from '../lib/format'

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Abbreviate commodity names for grid headers */
function abbreviateCommodity(name: string): string {
  const abbrevs: Record<string, string> = {
    'paddy': 'PADDY',
    'rice': 'RICE',
    'groundnut': 'GNUT',
    'turmeric': 'TURM',
    'cotton': 'COTN',
    'maize': 'MAIZE',
    'banana': 'BANA',
    'coconut': 'COCO',
    'coconut (copra)': 'COPA',
    'onion': 'ONIN',
    'black gram': 'BGRAM',
    'black gram (urad)': 'URAD',
    'green gram (moong)': 'MUNG',
  }
  const lower = name.toLowerCase()
  return abbrevs[lower] ?? name.slice(0, 5).toUpperCase()
}

/** Price cell color: green above seasonal avg, red below, amber near */
function priceColor(price: number, avgPrice: number): string {
  const ratio = price / avgPrice
  if (ratio >= 1.05) return '#2a9d8f'
  if (ratio <= 0.95) return '#e63946'
  return '#d4a019'
}


// ── Component ────────────────────────────────────────────────────────────────

export default function MarketPrices() {
  const stats = usePipelineStats()
  const prices = useMarketPrices()
  const mandis = useMandis()
  const conflicts = usePriceConflicts()
  const [hoveredCell, setHoveredCell] = useState<string | null>(null)

  // ── Price grid data ─────────────────────────────────────────────────────
  const priceGrid = useMemo(() => {
    if (!prices.data?.market_prices?.length) return null

    const priceList = prices.data.market_prices

    const mandiMap = new Map<string, string>()
    const commodityMap = new Map<string, string>()
    for (const p of priceList) {
      if (!mandiMap.has(p.mandi_id)) mandiMap.set(p.mandi_id, p.mandi_name)
      if (!commodityMap.has(p.commodity_id)) commodityMap.set(p.commodity_id, p.commodity_name)
    }

    const mandiList = Array.from(mandiMap.entries())
    const commodityList = Array.from(commodityMap.entries())

    // Build lookup: "mandiId|commodityId" -> MarketPrice
    const lookup = new Map<string, typeof priceList[0]>()
    for (const p of priceList) {
      lookup.set(`${p.mandi_id}|${p.commodity_id}`, p)
    }

    // Compute average price per commodity for coloring
    const avgPrices = new Map<string, number>()
    for (const [cid] of commodityList) {
      const commodityPrices = priceList.filter((p) => p.commodity_id === cid)
      if (commodityPrices.length) {
        const avg = commodityPrices.reduce((s, p) => s + p.reconciled_price_rs, 0) / commodityPrices.length
        avgPrices.set(cid, avg)
      }
    }

    return { mandis: mandiList, commodities: commodityList, lookup, avgPrices }
  }, [prices.data])

  // ── Conflict counts per mandi (for map coloring) ──────────────────────
  const conflictsByMandi = useMemo(() => {
    const counts = new Map<string, number>()
    if (conflicts.data?.price_conflicts) {
      for (const c of conflicts.data.price_conflicts) {
        counts.set(c.mandi_id, (counts.get(c.mandi_id) ?? 0) + 1)
      }
    }
    return counts
  }, [conflicts.data])

  // ── Loading / error states ──────────────────────────────────────────────
  if (stats.isLoading || prices.isLoading) return <DashboardSkeleton />
  if (stats.isError) return <ErrorState onRetry={() => stats.refetch()} />
  if (prices.isError) return <ErrorState onRetry={() => prices.refetch()} />

  const s = stats.data
  const totalPrices = prices.data?.total ?? 0
  const totalConflicts = conflicts.data?.total ?? 0
  const mandisMonitored = s?.mandis_monitored ?? 0
  const commoditiesTracked = s?.commodities_tracked ?? 0
  const conflictsResolved = s?.price_conflicts_found ?? 0
  const successRate = Math.round((s?.success_rate ?? 0) * 100)

  return (
    <div className="animate-slide-up">
      {/* Hero */}
      <div data-tour="hero" className="pt-2 pb-6">
        <h1 className="page-title">Market Prices</h1>
        <p className="page-caption">
          Reconciled prices across {mandisMonitored || 15} Tamil Nadu mandis
        </p>
      </div>

      {/* ── Stage Cards ───────────────────────────────────────────────────── */}
      <div data-tour="stage-cards" className="mb-8">
        <div className="section-header">How It Works</div>
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr_auto_1fr] gap-3 items-stretch">

          {/* Card 1: Scraped */}
          <Link to="/inputs" className="card-accent accent-amber no-underline block p-5">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-9 h-9 rounded-lg bg-amber-50 flex items-center justify-center">
                <FileText size={18} className="text-warning" />
              </div>
              <h3 className="text-sm font-semibold text-[#1a1a1a] font-sans m-0">
                Scraped
              </h3>
            </div>
            <p className="text-xs text-warm-body leading-relaxed m-0">
              Price records collected from Agmarknet and eNAM government databases daily
            </p>
            <div className="mt-4 pt-3 border-t border-warm-border/60 grid grid-cols-2 gap-2">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-warm-muted font-semibold">
                  Records
                </div>
                <div className="text-base font-serif font-bold text-[#1a1a1a]">
                  {totalPrices}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-warm-muted font-semibold">
                  Sources
                </div>
                <div className="text-base font-serif font-bold text-[#1a1a1a]">
                  2
                </div>
              </div>
            </div>
          </Link>

          <div className="hidden md:flex items-center justify-center">
            <ArrowRight size={20} className="text-warm-border" />
          </div>

          {/* Card 2: Reconciled */}
          <Link to="/inputs" className="card-accent accent-green no-underline block p-5">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-9 h-9 rounded-lg bg-emerald-50 flex items-center justify-center">
                <IndianRupee size={18} className="text-success" />
              </div>
              <h3 className="text-sm font-semibold text-[#1a1a1a] font-sans m-0">
                Reconciled
              </h3>
            </div>
            <p className="text-xs text-warm-body leading-relaxed m-0">
              Conflicting prices investigated, resolved, and merged into a single trusted price
            </p>
            <div className="mt-4 pt-3 border-t border-warm-border/60 grid grid-cols-2 gap-2">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-warm-muted font-semibold">
                  Conflicts
                </div>
                <div className="text-base font-serif font-bold text-[#1a1a1a]">
                  {conflictsResolved || totalConflicts}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-warm-muted font-semibold">
                  Quality
                </div>
                <div className="text-base font-serif font-bold text-[#1a1a1a]">
                  {successRate}%
                </div>
              </div>
            </div>
          </Link>

          <div className="hidden md:flex items-center justify-center">
            <ArrowRight size={20} className="text-warm-border" />
          </div>

          {/* Card 3: Forecasted */}
          <Link to="/forecast" className="card-accent accent-blue no-underline block p-5">
            <div className="flex items-center gap-3 mb-2">
              <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center">
                <TrendingUp size={18} className="text-info" />
              </div>
              <h3 className="text-sm font-semibold text-[#1a1a1a] font-sans m-0">
                Forecasted
              </h3>
            </div>
            <p className="text-xs text-warm-body leading-relaxed m-0">
              Price predictions for 7, 14, and 30 days out with confidence intervals
            </p>
            <div className="mt-4 pt-3 border-t border-warm-border/60 grid grid-cols-2 gap-2">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-warm-muted font-semibold">
                  Commodities
                </div>
                <div className="text-base font-serif font-bold text-[#1a1a1a]">
                  {commoditiesTracked}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-warm-muted font-semibold">
                  Horizon
                </div>
                <div className="text-base font-serif font-bold text-[#1a1a1a]">
                  7-30d
                </div>
              </div>
            </div>
          </Link>
        </div>
      </div>

      {/* ── Metrics ───────────────────────────────────────────────────────── */}
      <div data-tour="metrics" className="mb-8">
        <div className="section-header">Current Status</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-stagger">
          <MetricCard
            label="Mandis Monitored"
            value={mandisMonitored}
            subtitle="across Tamil Nadu"
          />
          <MetricCard
            label="Commodities Tracked"
            value={commoditiesTracked}
            subtitle="agricultural products"
          />
          <MetricCard
            label="Conflicts Resolved"
            value={conflictsResolved || totalConflicts}
            subtitle="price discrepancies"
          />
          <MetricCard
            label="Avg Confidence"
            value={`${successRate}%`}
            subtitle="data reliability"
          />
        </div>
      </div>

      {/* ── Price Grid (mandi x commodity) ─────────────────────────────────── */}
      <div className="mb-8">
        <div className="section-header">Price Overview</div>
        {priceGrid ? (
          <div className="bg-white rounded-[10px] border border-warm-border p-5 overflow-x-auto">
            <table className="w-full border-collapse" style={{ minWidth: 500 }}>
              <thead>
                <tr>
                  <th className="text-left text-[10px] uppercase tracking-wider text-warm-muted font-sans font-semibold pb-2 pr-2"
                      style={{ letterSpacing: '1.2px' }}>
                    Mandi
                  </th>
                  {priceGrid.commodities.map(([cid, cname]) => (
                    <th
                      key={cid}
                      className="text-center text-[10px] uppercase tracking-wider text-warm-muted font-sans font-semibold pb-2 px-1"
                      style={{ letterSpacing: '1px' }}
                      title={cname}
                    >
                      {abbreviateCommodity(cname)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {priceGrid.mandis.map(([mid, mname]) => (
                  <tr key={mid}>
                    <td className="text-xs text-warm-body font-sans py-1 pr-3 whitespace-nowrap">
                      {mname}
                    </td>
                    {priceGrid.commodities.map(([cid]) => {
                      const entry = priceGrid.lookup.get(`${mid}|${cid}`)
                      const cellKey = `${mid}|${cid}`
                      if (!entry) {
                        return (
                          <td key={cid} className="py-1 px-1">
                            <div className="stock-cell"
                                 style={{ background: '#f0ede8', color: '#aaa' }}>
                              --
                            </div>
                          </td>
                        )
                      }
                      const avg = priceGrid.avgPrices.get(cid) ?? entry.reconciled_price_rs
                      const color = priceColor(entry.reconciled_price_rs, avg)
                      const isHovered = hoveredCell === cellKey

                      return (
                        <td key={cid} className="py-1 px-1 relative">
                          <div
                            className="stock-cell cursor-default"
                            style={{
                              background: color,
                              color: '#fff',
                            }}
                            onMouseEnter={() => setHoveredCell(cellKey)}
                            onMouseLeave={() => setHoveredCell(null)}
                          >
                            {formatRs(entry.reconciled_price_rs)}
                          </div>
                          {isHovered && (
                            <div
                              className="absolute z-40 p-3 rounded-lg shadow-lg text-xs"
                              style={{
                                background: '#1a1a1a',
                                color: '#e0dcd5',
                                bottom: '100%',
                                left: '50%',
                                transform: 'translateX(-50%)',
                                minWidth: 180,
                                marginBottom: 4,
                                fontFamily: '"DM Sans", sans-serif',
                              }}
                            >
                              <div className="font-semibold text-[#d4a019] mb-1">
                                {entry.commodity_name}
                              </div>
                              <div className="space-y-1">
                                {entry.agmarknet_price_rs !== null && (
                                  <div className="flex justify-between">
                                    <span className="text-[#999]">Agmarknet</span>
                                    <span>{formatRs(entry.agmarknet_price_rs)}</span>
                                  </div>
                                )}
                                {entry.enam_price_rs !== null && (
                                  <div className="flex justify-between">
                                    <span className="text-[#999]">eNAM</span>
                                    <span>{formatRs(entry.enam_price_rs)}</span>
                                  </div>
                                )}
                                <div className="flex justify-between border-t border-white/20 pt-1">
                                  <span className="text-[#999]">Reconciled</span>
                                  <span className="font-semibold">{formatRs(entry.reconciled_price_rs)}</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-[#999]">Confidence</span>
                                  <span>{Math.round(entry.confidence * 100)}%</span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-[#999]">Trend</span>
                                  <span>{directionArrow(entry.price_trend)} {entry.price_trend}</span>
                                </div>
                              </div>
                            </div>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Legend */}
            <div className="flex items-center gap-4 mt-4 pt-3 border-t border-warm-border/40">
              <span className="text-[10px] uppercase tracking-wider text-warm-muted font-semibold"
                    style={{ letterSpacing: '1px' }}>
                vs seasonal avg:
              </span>
              <div className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 rounded-sm" style={{ background: '#2a9d8f' }} />
                <span className="text-[11px] text-warm-body font-sans">Above (+5%)</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 rounded-sm" style={{ background: '#d4a019' }} />
                <span className="text-[11px] text-warm-body font-sans">Near avg</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 rounded-sm" style={{ background: '#e63946' }} />
                <span className="text-[11px] text-warm-body font-sans">Below (-5%)</span>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-warm-muted font-sans">No price data available.</p>
        )}
      </div>

      {/* ── Map ───────────────────────────────────────────────────────────── */}
      <div className="mb-8">
        <div className="section-header">Mandi Network</div>
        <div className="rounded-[10px] border border-warm-border overflow-hidden" style={{ height: 420 }}>
          <MapContainer
            center={[10.8, 78.8]}
            zoom={7}
            style={{ height: '100%', width: '100%' }}
            scrollWheelZoom={false}
            attributionControl={false}
          >
            <TileLayer
              url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
              attribution='&copy; <a href="https://carto.com/">CARTO</a>'
            />

            {(mandis.data?.mandis ?? []).map((mandi) => {
              const conflictCount = conflictsByMandi.get(mandi.mandi_id) ?? 0
              let pinColor = '#2a9d8f'
              if (conflictCount >= 3) pinColor = '#e63946'
              else if (conflictCount >= 1) pinColor = '#d4a019'

              return (
                <CircleMarker
                  key={mandi.mandi_id}
                  center={[mandi.latitude, mandi.longitude]}
                  radius={8}
                  pathOptions={{
                    color: '#fff',
                    weight: 2,
                    fillColor: pinColor,
                    fillOpacity: 0.9,
                  }}
                >
                  <Popup>
                    <div style={{ fontFamily: '"DM Sans", sans-serif', minWidth: 200 }}>
                      <div style={{ fontFamily: '"Source Serif 4", serif', fontWeight: 700, fontSize: '0.95rem', marginBottom: 4 }}>
                        {mandi.name}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: 8 }}>
                        {mandi.district} &middot; {mandi.market_type}
                        {mandi.enam_integrated && ' \u00b7 eNAM'}
                      </div>
                      <div style={{ fontSize: '0.8rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                          <span style={{ color: '#888' }}>Commodities</span>
                          <span style={{ fontWeight: 600 }}>{mandi.commodities_traded.length}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                          <span style={{ color: '#888' }}>Reporting</span>
                          <span style={{ fontWeight: 600, color: mandi.reporting_quality === 'good' ? '#2a9d8f' : '#d4a019' }}>
                            {mandi.reporting_quality}
                          </span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                          <span style={{ color: '#888' }}>Conflicts</span>
                          <span style={{
                            fontWeight: 600,
                            color: conflictCount > 0 ? '#e63946' : '#2a9d8f'
                          }}>
                            {conflictCount}
                          </span>
                        </div>
                      </div>
                    </div>
                  </Popup>
                </CircleMarker>
              )
            })}
          </MapContainer>
        </div>

        {/* Map legend */}
        <div className="flex items-center gap-5 mt-3 text-xs text-warm-muted">
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full" style={{ background: '#2a9d8f' }} />
            No conflicts
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full" style={{ background: '#d4a019' }} />
            Some conflicts
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 rounded-full" style={{ background: '#e63946' }} />
            Many conflicts
          </div>
        </div>
      </div>
    </div>
  )
}
