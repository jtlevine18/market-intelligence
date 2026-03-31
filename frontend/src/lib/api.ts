import { useQuery } from '@tanstack/react-query'

const BASE_URL = import.meta.env.VITE_API_URL ?? ''

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`)
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

// ── Types (matched to actual backend response shapes) ─────────────────────

// ── New AI pipeline types ─────────────────────────────────────────────────

export interface RawFacilityInput {
  stock_report: string
  idsr_report?: string
  chw_messages: string[]
}

export interface RawInputsResponse {
  raw_inputs: Record<string, RawFacilityInput>
  total_facilities: number
  source: string
}

export interface ExtractedDrug {
  stock_level: number
  days_of_stock: number
  source: string
}

export interface ExtractedFacilityData {
  facility_id: string
  drugs: Record<string, ExtractedDrug>
  disease_cases: Record<string, number>
  alerts: string[]
}

export interface ExtractedDataResponse {
  extracted_data: Record<string, ExtractedFacilityData>
  total_facilities: number
  source: string
}

export interface ReconciledDrug {
  stock_level: number
  consumption_daily: number
  days_of_stock_remaining: number
  source: string
}

export interface Conflict {
  drug_id: string
  drug_name: string
  field: string
  simulated_value: number
  extracted_value: number
  resolution: string
  reasoning: string
}

export interface ReconciledFacilityData {
  facility_id: string
  stock_by_drug: Record<string, ReconciledDrug>
  conflicts: Conflict[]
  disease_cases: Record<string, number>
  quality_score: number
}

export interface ReconciledDataResponse {
  reconciled_data: Record<string, ReconciledFacilityData>
  total_facilities: number
  total_conflicts: number
  source: string
}

export interface MLModelMetrics {
  rmse?: number
  mae?: number
  r2?: number
  train_samples?: number
  test_samples?: number
  feature_importances?: Record<string, number>
}

export interface ResidualMetrics {
  rmse_residual_before?: number
  rmse_residual_after?: number
  rmse_improvement_pct?: number
  r2_residual?: number
  features_used?: string[]
  feature_importances?: Record<string, number>
}

export interface MLStackInfo {
  primary_model: {
    type: string
    features: number
    training_samples?: number
    metrics: MLModelMetrics
  }
  residual_correction: {
    type: string
    purpose: string
    metrics: ResidualMetrics
  }
  anomaly_detection: {
    type: string
    purpose: string
  }
  rag: {
    type: string
    purpose: string
  }
  agents: Record<string, string>
}

export interface ModelInfoResponse {
  model_metrics: {
    model_type: string
    primary_model?: MLModelMetrics
    residual_model?: ResidualMetrics
    features?: string[]
    feature_importances?: Record<string, number>
    // Legacy fields for epidemiological mode
    model_source?: string
    rmse?: number
    mae?: number
    r_squared?: number
    note?: string
  }
  ml_stack?: MLStackInfo
  source: string
}

export interface ReasoningTraceStep {
  round: number
  tool: string
  input: Record<string, unknown>
  result_summary: string
}

export interface Redistribution {
  from_facility: string
  to_facility: string
  drug_id: string
  quantity: number
  transit_days: number
  reason: string
}

// ── Core types ────────────────────────────────────────────────────────────

export interface Facility {
  facility_id: string
  name: string
  district: string
  country: string
  facility_type: string
  population_served: number
  reporting_quality: string
  data_quality_score: number
  budget_usd: number
  budget_used_usd: number
  stockout_risks: number
  last_updated: string
}

export interface FacilitiesResponse {
  facilities: Facility[]
  total: number
  countries?: string[]
}

export interface StockLevel {
  facility_id: string
  facility_name: string
  drug_id: string
  drug_name: string
  category: string
  critical: boolean
  stock_level: number
  consumption_daily: number
  days_of_stock: number
  stockout_risk: string
  date: string
  anomaly_score?: number
  is_anomaly?: boolean
}

export interface StockLevelsResponse {
  stock_levels: StockLevel[]
  total: number
}

export interface DemandForecast {
  facility_id: string
  facility_name: string
  drug_id: string
  drug_name: string
  category: string
  predicted_demand_monthly: number
  baseline_demand_monthly: number
  demand_multiplier: number
  confidence: number
  contributing_factors: Array<Record<string, unknown>>
  climate_driven: boolean
  risk_level: string
  model_source?: string
  prediction_interval?: { lower: number; upper: number }
  model_metrics?: { rmse: number; r_squared: number }
}

export interface DemandForecastResponse {
  forecasts: DemandForecast[]
  total: number
}

export interface ProcurementOrder {
  drug_id: string
  name: string
  category: string
  unit: string
  critical: boolean
  demand_qty: number
  safety_stock_qty: number
  total_need: number
  ordered_qty: number
  unit_cost_usd: number
  total_cost_usd: number
  coverage_pct: number
  stockout_risk: string
  days_of_stock: number
}

export interface ProcurementPlan {
  population: number
  budget_usd: number
  budget_used_usd: number
  budget_remaining_usd: number
  planning_months: number
  season: string
  fully_covered: number
  partially_covered: number
  not_covered: number
  critical_drugs_covered: number
  critical_drugs_total: number
  stockout_risks: number
  orders: ProcurementOrder[]
  facility_id: string
  facility_name: string
  agent_reasoning?: string
  optimization_method?: string
  reasoning_trace?: ReasoningTraceStep[]
  redistributions?: Redistribution[]
}

export interface ProcurementPlanResponse {
  plans: ProcurementPlan[]
  total: number
}

export interface StockoutRisk {
  facility_id: string
  facility_name: string
  drug_id: string
  drug_name: string
  category: string
  critical: boolean
  stock_level: number
  consumption_daily: number
  days_of_stock: number
  stockout_risk: string
  date: string
}

export interface StockoutRisksResponse {
  risks: StockoutRisk[]
  total: number
  high: number
  critical: number
}

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
  facilities_processed?: number
  stockout_risks_found?: number
}

export interface PipelineRunsResponse {
  runs: PipelineRun[]
  total: number
}

export interface PipelineStats {
  total_runs: number
  successful_runs: number
  success_rate: number
  facilities_monitored: number
  drugs_tracked: number
  high_risk_stockouts: number
  total_cost_usd: number
  avg_cost_per_run_usd: number
  last_run: string | null
  data_sources?: string[]
}

// ── Query hooks ──────────────────────────────────────────────────────────

const STALE_5MIN = 5 * 60 * 1000

export function useFacilities() {
  return useQuery<FacilitiesResponse>({
    queryKey: ['facilities'],
    queryFn: () => fetchJson('/api/facilities'),
    staleTime: STALE_5MIN,
  })
}

export function useStockLevels() {
  return useQuery<StockLevelsResponse>({
    queryKey: ['stock-levels'],
    queryFn: () => fetchJson('/api/stock-levels'),
    staleTime: STALE_5MIN,
  })
}

export function useDemandForecast() {
  return useQuery<DemandForecastResponse>({
    queryKey: ['demand-forecast'],
    queryFn: () => fetchJson('/api/demand-forecast'),
    staleTime: STALE_5MIN,
  })
}

export function useProcurementPlan() {
  return useQuery<ProcurementPlanResponse>({
    queryKey: ['procurement-plan'],
    queryFn: () => fetchJson('/api/procurement-plan'),
    staleTime: STALE_5MIN,
  })
}

export function useStockoutRisks() {
  return useQuery<StockoutRisksResponse>({
    queryKey: ['stockout-risks'],
    queryFn: () => fetchJson('/api/stockout-risks'),
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
