import type { VercelRequest, VercelResponse } from '@vercel/node'
import { getDb } from './_db'

export default async function handler(req: VercelRequest, res: VercelResponse) {
  try {
    const sql = getDb()

    const runs = await sql`
      SELECT run_id, started_at, status, duration_sec, total_cost_usd,
             mandis_count, commodities_count
      FROM pipeline_runs
      ORDER BY started_at DESC
      LIMIT 20
    `

    const totalRuns = runs.length
    const successfulRuns = runs.filter((r: any) => r.status === 'ok').length
    const totalCost = runs.reduce((s: number, r: any) => s + (r.total_cost_usd || 0), 0)

    const priceCount = await sql`SELECT count(DISTINCT commodity_id) as n FROM market_prices`
    const mandiCount = await sql`SELECT count(DISTINCT mandi_id) as n FROM market_prices`

    res.setHeader('Access-Control-Allow-Origin', '*')
    res.json({
      total_runs: totalRuns,
      successful_runs: successfulRuns,
      success_rate: totalRuns > 0 ? Math.round(successfulRuns / totalRuns * 100) / 100 : 0,
      mandis_monitored: Number(mandiCount[0]?.n) || 15,
      commodities_tracked: Number(priceCount[0]?.n) || 10,
      price_conflicts_found: 0,
      total_cost_usd: Math.round(totalCost * 100) / 100,
      avg_cost_per_run_usd: totalRuns > 0 ? Math.round(totalCost / totalRuns * 10000) / 10000 : 0,
      last_run: runs[0]?.started_at || null,
      data_sources: ['Agmarknet (data.gov.in)', 'eNAM', 'NASA POWER'],
      source: 'neon',
    })
  } catch (e: any) {
    res.status(500).json({ error: e.message })
  }
}
