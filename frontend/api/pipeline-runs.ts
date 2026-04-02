import type { VercelRequest, VercelResponse } from '@vercel/node'

export default async function handler(req: VercelRequest, res: VercelResponse) {
  try {
    const dbUrl = process.env.DATABASE_URL
    if (!dbUrl) return res.status(500).json({ error: 'DATABASE_URL not set' })
    const { neon } = await import('@neondatabase/serverless')
    const sql = neon(dbUrl)
    const runs = await sql`
      SELECT run_id, started_at, finished_at, status, duration_sec,
             total_cost_usd, mandis_count, commodities_count, step_results
      FROM pipeline_runs
      ORDER BY started_at DESC
      LIMIT 20
    `

    const result = runs.map((r: any) => ({
      run_id: r.run_id,
      started_at: r.started_at,
      ended_at: r.finished_at,
      status: r.status,
      duration_s: r.duration_sec,
      mandis_processed: r.mandis_count,
      commodities_tracked: r.commodities_count,
      total_cost_usd: r.total_cost_usd,
      steps: JSON.parse(r.step_results || '[]'),
    }))

    res.setHeader('Access-Control-Allow-Origin', '*')
    res.json({ runs: result, source: 'neon' })
  } catch (e: any) {
    res.status(500).json({ error: e.message })
  }
}
