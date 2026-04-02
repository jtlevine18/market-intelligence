import type { VercelRequest, VercelResponse } from '@vercel/node'

export default async function handler(req: VercelRequest, res: VercelResponse) {
  try {
    const dbUrl = process.env.DATABASE_URL
    if (!dbUrl) return res.json({ status: 'ok', pipeline_data: false, error: 'no DATABASE_URL' })
    const { neon } = await import('@neondatabase/serverless')
    const sql = neon(dbUrl)
    const result = await sql`SELECT count(*) as n FROM pipeline_runs`
    res.json({ status: 'ok', pipeline_data: Number(result[0]?.n) > 0, runs: Number(result[0]?.n), source: 'neon' })
  } catch (e: any) {
    res.json({ status: 'ok', pipeline_data: false, error: e.message })
  }
}
