import type { VercelRequest, VercelResponse } from '@vercel/node'
import { getDb } from './_db'

export default async function handler(req: VercelRequest, res: VercelResponse) {
  try {
    const sql = await getDb()
    const recs = await sql`
      SELECT DISTINCT ON (farmer_id)
        run_id, farmer_id, commodity_id, best_mandi_id, best_timing,
        net_price_rs, potential_gain_rs, recommendation_text, created_at
      FROM sell_recommendations
      ORDER BY farmer_id, created_at DESC
    `

    const result = recs.map((r: any) => ({
      farmer_id: r.farmer_id,
      farmer_name: r.farmer_id,
      commodity_id: r.commodity_id,
      commodity_name: r.commodity_id,
      best_option: {
        mandi_id: r.best_mandi_id,
        mandi_name: r.best_mandi_id,
        sell_timing: r.best_timing,
        net_price_rs: r.net_price_rs,
      },
      potential_gain_rs: r.potential_gain_rs,
      recommendation_text: r.recommendation_text,
      all_options: [],
    }))

    res.setHeader('Access-Control-Allow-Origin', '*')
    res.json({ sell_recommendations: result, total: result.length, source: 'neon' })
  } catch (e: any) {
    res.status(500).json({ error: e.message })
  }
}
