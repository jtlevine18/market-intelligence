import { useState, useMemo } from 'react'
import MetricCard from '../components/MetricCard'
import { LoadingSpinner, ErrorState } from '../components/LoadingState'
import {
  useRawInputs,
  useExtractedData,
  useReconciledData,
  useFacilities,
} from '../lib/api'

export default function Inputs() {
  const rawInputs = useRawInputs()
  const extracted = useExtractedData()
  const reconciled = useReconciledData()
  const facilities = useFacilities()

  const [selectedFacility, setSelectedFacility] = useState<string | null>(null)

  const facilityIds = useMemo(() => {
    return Object.keys(rawInputs.data?.raw_inputs ?? {})
  }, [rawInputs.data])

  const activeFacility = selectedFacility ?? facilityIds[0] ?? null

  const facilityNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    facilities.data?.facilities?.forEach((f) => {
      map[f.facility_id] = f.name
    })
    return map
  }, [facilities.data])

  // Aggregate metrics
  const totalConflicts = reconciled.data?.total_conflicts ?? 0
  const totalFacilities = rawInputs.data?.total_facilities ?? 0
  const avgQuality = useMemo(() => {
    if (!reconciled.data?.reconciled_data) return 0
    const entries = Object.values(reconciled.data.reconciled_data)
    if (!entries.length) return 0
    return entries.reduce((sum, e) => sum + e.quality_score, 0) / entries.length
  }, [reconciled.data])

  if (rawInputs.isLoading || extracted.isLoading || reconciled.isLoading)
    return <LoadingSpinner />
  if (rawInputs.isError)
    return <ErrorState onRetry={() => rawInputs.refetch()} />
  if (extracted.isError)
    return <ErrorState onRetry={() => extracted.refetch()} />

  const rawFacility = activeFacility
    ? rawInputs.data?.raw_inputs[activeFacility]
    : null
  const extractedFacility = activeFacility
    ? extracted.data?.extracted_data[activeFacility]
    : null
  const reconciledFacility = activeFacility
    ? reconciled.data?.reconciled_data[activeFacility]
    : null

  return (
    <div className="animate-slide-up">
      <div data-tour="inputs-title" className="pt-2 pb-6">
        <h1 className="page-title">Facility Data</h1>
        <p className="page-caption">
          AI reads messy stock reports from health facilities and turns them into reliable numbers
        </p>
      </div>

      <div data-tour="inputs-metrics" className="mb-8">
        <div className="section-header">Data Overview</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-stagger">
          <MetricCard
            label="Reports Received"
            value={totalFacilities}
            subtitle="facilities reporting"
          />
          <MetricCard
            label="Discrepancies Found"
            value={totalConflicts}
            subtitle="corrected automatically"
          />
          <MetricCard
            label="Processing"
            value="AI-Powered"
            subtitle="reads unstructured text"
          />
          <MetricCard
            label="Data Reliability"
            value={`${Math.round(avgQuality * 100)}%`}
            subtitle="after verification"
          />
        </div>
      </div>

      {/* Facility selector */}
      <div className="mb-6">
        <label className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider mr-3">
          Facility
        </label>
        <select
          value={activeFacility ?? ''}
          onChange={(e) => setSelectedFacility(e.target.value)}
          className="px-3 py-2 text-sm font-sans rounded-lg border border-warm-border bg-white text-[#1a1a1a] focus:outline-none focus:ring-2 focus:ring-gold/30"
        >
          {facilityIds.map((fid) => (
            <option key={fid} value={fid}>
              {facilityNameMap[fid] ?? fid}
            </option>
          ))}
        </select>
      </div>

      {/* Two-column layout */}
      {activeFacility && rawFacility && (
        <div
          data-tour="inputs-extraction"
          className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8"
        >
          {/* LEFT: Raw Input */}
          <div className="space-y-4">
            <div className="section-header">Report as Received</div>

            {/* Stock report — paper-like */}
            <div
              className="rounded-lg p-5 font-mono text-xs leading-relaxed whitespace-pre-wrap overflow-x-auto"
              style={{
                backgroundColor: '#fefae0',
                border: '1px solid #d4c89a',
                boxShadow: '2px 2px 8px rgba(0,0,0,0.06)',
                transform: 'rotate(-0.3deg)',
                maxHeight: 400,
                overflowY: 'auto',
              }}
            >
              {rawFacility.stock_report}
            </div>

            {/* IDSR report */}
            {rawFacility.idsr_report && (
              <div
                className="rounded-lg p-5 font-mono text-xs leading-relaxed whitespace-pre-wrap overflow-x-auto"
                style={{
                  backgroundColor: '#f0f4ff',
                  border: '1px solid #b8c9e8',
                  boxShadow: '2px 2px 8px rgba(0,0,0,0.04)',
                  transform: 'rotate(0.2deg)',
                  maxHeight: 300,
                  overflowY: 'auto',
                }}
              >
                {rawFacility.idsr_report}
              </div>
            )}

            {/* CHW messages — chat bubbles */}
            {rawFacility.chw_messages.length > 0 && (
              <div>
                <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider mb-2">
                  CHW Messages
                </p>
                <div className="space-y-2">
                  {rawFacility.chw_messages.map((msg, i) => (
                    <div
                      key={i}
                      className="text-xs leading-relaxed font-sans"
                      style={{
                        backgroundColor: '#dcfce7',
                        border: '1px solid #a7d9b8',
                        borderRadius: '12px 12px 12px 4px',
                        padding: '8px 12px',
                        maxWidth: '90%',
                      }}
                    >
                      {msg}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* RIGHT: Extracted + Reconciled Data */}
          <div className="space-y-4">
            <div className="section-header">What the AI Found</div>

            {/* Stock table */}
            {extractedFacility && (
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Drug</th>
                      <th>Stock Level</th>
                      <th>Days Remaining</th>
                      <th>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(extractedFacility.drugs).map(
                      ([drugId, drug]) => (
                        <tr key={drugId}>
                          <td className="font-semibold text-[#1a1a1a] text-xs">
                            {drugId}
                          </td>
                          <td>{drug.stock_level.toLocaleString()}</td>
                          <td>
                            <span
                              className="font-semibold"
                              style={{
                                color:
                                  drug.days_of_stock <= 14
                                    ? '#e63946'
                                    : drug.days_of_stock <= 30
                                      ? '#d4a019'
                                      : '#2a9d8f',
                              }}
                            >
                              {drug.days_of_stock.toFixed(0)}d
                            </span>
                          </td>
                          <td className="text-xs text-warm-muted">
                            {drug.source}
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {/* Disease cases */}
            {extractedFacility &&
              Object.keys(extractedFacility.disease_cases).length > 0 && (
                <div className="card card-body">
                  <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider mb-2">
                    Disease Cases (Weekly)
                  </p>
                  <div className="grid grid-cols-3 gap-3">
                    {Object.entries(extractedFacility.disease_cases).map(
                      ([disease, count]) => (
                        <div key={disease} className="text-center">
                          <p className="text-lg font-serif font-bold text-[#1a1a1a] m-0">
                            {count.toLocaleString()}
                          </p>
                          <p className="text-xs text-warm-muted m-0 capitalize">
                            {disease}
                          </p>
                        </div>
                      ),
                    )}
                  </div>
                </div>
              )}

            {/* CHW-identified alerts */}
            {extractedFacility &&
              extractedFacility.alerts.length > 0 && (
                <div>
                  <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider mb-2">
                    CHW-Identified Needs
                  </p>
                  <div className="space-y-2">
                    {extractedFacility.alerts.map((alert, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2"
                      >
                        <span className="badge-orange text-[0.65rem] shrink-0 mt-0.5">
                          urgent
                        </span>
                        <span className="text-xs text-warm-body leading-relaxed">
                          {alert}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

            {/* Conflicts */}
            {reconciledFacility &&
              reconciledFacility.conflicts.length > 0 && (
                <div data-tour="inputs-conflicts">
                  <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider mb-2">
                    Discrepancies Detected
                  </p>
                  <div className="space-y-3">
                    {reconciledFacility.conflicts.map((conflict, i) => (
                      <div
                        key={i}
                        className="rounded-lg p-3"
                        style={{
                          backgroundColor: '#fffbeb',
                          border: '2px solid #d4a019',
                        }}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          <span className="font-semibold text-sm text-[#1a1a1a]">
                            {conflict.drug_name}
                          </span>
                          <span className="badge-amber text-[0.65rem]">
                            {conflict.resolution}
                          </span>
                        </div>
                        <div className="grid grid-cols-2 gap-3 mb-2">
                          <div className="text-xs">
                            <span className="text-warm-muted">
                              Stock report:{' '}
                            </span>
                            <span className="font-semibold text-[#1a1a1a]">
                              {conflict.extracted_value.toLocaleString()}
                            </span>
                          </div>
                          <div className="text-xs">
                            <span className="text-warm-muted">
                              LMIS record:{' '}
                            </span>
                            <span className="font-semibold text-[#1a1a1a]">
                              {conflict.simulated_value.toLocaleString()}
                            </span>
                          </div>
                        </div>
                        <p className="text-xs text-warm-body leading-relaxed m-0 italic">
                          {conflict.reasoning}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

            {/* Quality score */}
            {reconciledFacility && (
              <div className="card card-body">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-sans font-semibold text-warm-muted uppercase tracking-wider m-0">
                    Data Reliability Score
                  </p>
                  <span
                    className="text-lg font-serif font-bold"
                    style={{
                      color:
                        reconciledFacility.quality_score >= 0.8
                          ? '#2a9d8f'
                          : reconciledFacility.quality_score >= 0.5
                            ? '#d4a019'
                            : '#e63946',
                    }}
                  >
                    {Math.round(reconciledFacility.quality_score * 100)}%
                  </span>
                </div>
                <div className="w-full h-2 bg-warm-header-bg rounded-full overflow-hidden mt-2">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${Math.round(reconciledFacility.quality_score * 100)}%`,
                      backgroundColor:
                        reconciledFacility.quality_score >= 0.8
                          ? '#2a9d8f'
                          : reconciledFacility.quality_score >= 0.5
                            ? '#d4a019'
                            : '#e63946',
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
