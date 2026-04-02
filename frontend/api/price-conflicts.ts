import type { VercelRequest, VercelResponse } from '@vercel/node'

export default async function handler(req: VercelRequest, res: VercelResponse) {
  try {
    const dbUrl = process.env.DATABASE_URL
    if (!dbUrl) {
      res.setHeader('Access-Control-Allow-Origin', '*')
      return res.json({ price_conflicts: [], total: 0, source: 'neon' })
    }
    const { neon } = await import('@neondatabase/serverless')
    const sql = neon(dbUrl)

    // Price conflicts are stored as JSONB on the latest pipeline_run
    const runs = await sql`
      SELECT price_conflicts FROM pipeline_runs
      WHERE price_conflicts IS NOT NULL
      ORDER BY started_at DESC LIMIT 1
    `

    const conflicts = runs[0]?.price_conflicts || []

    res.setHeader('Access-Control-Allow-Origin', '*')
    res.json({ price_conflicts: conflicts, total: conflicts.length, source: 'neon' })
  } catch (e: any) {
    res.setHeader('Access-Control-Allow-Origin', '*')
    res.json({ price_conflicts: [], total: 0, source: 'neon' })
  }
}
