import type { VercelRequest, VercelResponse } from '@vercel/node'
import { getDb } from './_db'

export default async function handler(req: VercelRequest, res: VercelResponse) {
  try {
    const sql = getDb()
    const result = await sql`SELECT count(*) as n FROM pipeline_runs`
    const hasData = Number(result[0]?.n) > 0

    res.setHeader('Access-Control-Allow-Origin', '*')
    res.json({
      status: 'ok',
      service: 'market-intelligence-agent',
      version: '1.0.0',
      pipeline_data: hasData,
      source: 'neon',
    })
  } catch (e: any) {
    res.json({
      status: 'ok',
      service: 'market-intelligence-agent',
      version: '1.0.0',
      pipeline_data: false,
      source: 'neon-error',
    })
  }
}
