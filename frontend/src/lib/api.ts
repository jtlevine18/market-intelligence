import { useQuery } from '@tanstack/react-query'

const BASE_URL = import.meta.env.VITE_API_URL ?? ''

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`)
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

// ── Types ────────────────────────────────────────────────────────────────────

export interface Mandi {
  mandi_id: string
  name: string
  district: string
  latitude: number
  longitude: number
  market_type: string
  enam_integrated: boolean
  reporting_quality: string
  commodities_traded: string[]
  last_updated: string
}

export interface MandisResponse {
  mandis: Mandi[]
  total: number
}

export interface MarketPrice {
  mandi_id: string
  mandi_name: string
  commodity_id: string
  commodity_name: string
  category: string
  price_rs: number
  agmarknet_price_rs: number | null
  enam_price_rs: number | null
  reconciled_price_rs: number
  confidence: number
  price_trend: string
  date: string
}

export interface MarketPricesResponse {
  market_prices: MarketPrice[]
  total: number
}

export interface PriceForecast {
  mandi_id: string
  mandi_name: string
  commodity_id: string
  commodity_name: string
  current_price_rs: number
  price_7d: number
  price_14d: number
  price_30d: number
  ci_lower_7d: number
  ci_upper_7d: number
  direction: string
  confidence: number
  seasonal_index: number
}

export interface PriceForecastsResponse {
  price_forecasts: PriceForecast[]
  total: number
}

export interface SellOption {
  mandi_id: string
  mandi_name: string
  sell_timing: string
  market_price_rs: number
  transport_cost_rs: number
  storage_loss_rs: number
  mandi_fee_rs: number
  net_price_rs: number
  distance_km: number
  drive_time_min: number
  confidence: number
}

export interface CreditReadiness {
  readiness: 'strong' | 'moderate' | 'not_yet'
  expected_revenue_rs: number
  min_revenue_rs: number
  max_advisable_input_loan_rs: number
  revenue_confidence: number
  loan_to_revenue_pct: number
  strengths: string[]
  risks: string[]
  advice_en: string
  advice_ta: string
}

export interface SellRecommendation {
  farmer_name: string
  commodity_id: string
  commodity_name: string
  quantity_quintals: number
  farmer_lat: number
  farmer_lon: number
  best_option: SellOption
  all_options: SellOption[]
  potential_gain_rs: number
  recommendation_text: string
  recommendation_tamil: string
  credit_readiness?: CreditReadiness
}

export interface SellRecommendationsResponse {
  sell_recommendations: SellRecommendation[]
  total: number
}

export interface PriceConflict {
  mandi_id: string
  mandi_name: string
  commodity_id: string
  commodity_name: string
  agmarknet_price: number
  enam_price: number
  delta_pct: number
  resolution: string
  reconciled_price: number
  reasoning: string
}

export interface PriceConflictsResponse {
  price_conflicts: PriceConflict[]
  total: number
}

// ── Raw / Extracted / Reconciled responses ────────────────────────────────────

export interface RawInputsResponse {
  raw_inputs: Record<string, unknown>
  sources: string[]
}

export interface ExtractedDataResponse {
  extracted_data: Record<string, unknown>
  total_mandis: number
}

export interface ReconciledDataResponse {
  reconciled_data: Record<string, unknown>
  total_mandis: number
  total_conflicts: number
}

// ── Model info ───────────────────────────────────────────────────────────────

export interface ModelInfoResponse {
  model_metrics: {
    model_type: string
    rmse?: number
    mae?: number
    r2?: number
    features?: string[]
    feature_importances?: Record<string, number>
    train_samples?: number
    test_samples?: number
  }
  ml_stack?: {
    primary_model: { type: string; features: number; metrics: Record<string, number> }
    agents: Record<string, string>
    [key: string]: unknown
  }
}

// ── Pipeline types ───────────────────────────────────────────────────────────

export interface PipelineStep {
  step: string
  status: string
  duration_s: number
}

export interface PipelineRun {
  run_id: string
  started_at: string
  ended_at: string
  status: string
  duration_s: number
  steps: PipelineStep[]
  total_cost_usd: number
}

export interface PipelineRunsResponse {
  runs: PipelineRun[]
  total: number
}

export interface PipelineStats {
  total_runs: number
  success_rate: number
  mandis_monitored: number
  commodities_tracked: number
  price_conflicts_found: number
  total_cost_usd: number
  last_run: string | null
  data_sources: string[]
}

// ── Query hooks ──────────────────────────────────────────────────────────────

const STALE_5MIN = 5 * 60 * 1000

export function useMandis() {
  return useQuery<MandisResponse>({
    queryKey: ['mandis'],
    queryFn: () => fetchJson('/api/mandis'),
    staleTime: STALE_5MIN,
  })
}

export function useMarketPrices() {
  return useQuery<MarketPricesResponse>({
    queryKey: ['market-prices'],
    queryFn: () => fetchJson('/api/market-prices'),
    staleTime: STALE_5MIN,
  })
}

export function usePriceForecasts() {
  return useQuery<PriceForecastsResponse>({
    queryKey: ['price-forecast'],
    queryFn: () => fetchJson('/api/price-forecast'),
    staleTime: STALE_5MIN,
  })
}

export function useSellRecommendations() {
  return useQuery<SellRecommendationsResponse>({
    queryKey: ['sell-recommendations'],
    queryFn: () => fetchJson('/api/sell-recommendations'),
    staleTime: STALE_5MIN,
  })
}

export function usePriceConflicts() {
  return useQuery<PriceConflictsResponse>({
    queryKey: ['price-conflicts'],
    queryFn: () => fetchJson('/api/price-conflicts'),
    staleTime: STALE_5MIN,
  })
}

export function useRawInputs() {
  return useQuery<RawInputsResponse>({
    queryKey: ['raw-inputs'],
    queryFn: () => fetchJson('/api/raw-inputs'),
    staleTime: STALE_5MIN,
  })
}

export function useExtractedData() {
  return useQuery<ExtractedDataResponse>({
    queryKey: ['extracted-data'],
    queryFn: () => fetchJson('/api/extracted-data'),
    staleTime: STALE_5MIN,
  })
}

export function useReconciledData() {
  return useQuery<ReconciledDataResponse>({
    queryKey: ['reconciled-data'],
    queryFn: () => fetchJson('/api/reconciled-data'),
    staleTime: STALE_5MIN,
  })
}

export function useModelInfo() {
  return useQuery<ModelInfoResponse>({
    queryKey: ['model-info'],
    queryFn: () => fetchJson('/api/model-info'),
    staleTime: STALE_5MIN,
  })
}

export function usePipelineRuns() {
  return useQuery<PipelineRunsResponse>({
    queryKey: ['pipeline-runs'],
    queryFn: () => fetchJson('/api/pipeline/runs'),
    staleTime: STALE_5MIN,
  })
}

export function usePipelineStats() {
  return useQuery<PipelineStats>({
    queryKey: ['pipeline-stats'],
    queryFn: () => fetchJson('/api/pipeline/stats'),
    staleTime: STALE_5MIN,
  })
}
