import type { VercelRequest, VercelResponse } from '@vercel/node'

export default async function handler(req: VercelRequest, res: VercelResponse) {
  try {
    const dbUrl = process.env.DATABASE_URL
    if (!dbUrl) return res.status(500).json({ error: 'DATABASE_URL not set' })
    const { neon } = await import('@neondatabase/serverless')
    const sql = neon(dbUrl)

    const prices = await sql`
      SELECT DISTINCT ON (mandi_id, commodity_id)
        run_id, mandi_id, commodity_id, date, source, price_rs,
        arrivals_tonnes, quality_flag, created_at
      FROM market_prices
      ORDER BY mandi_id, commodity_id, created_at DESC
    `

    const enriched = prices.map((p: any) => ({
      mandi_id: p.mandi_id,
      mandi_name: p.mandi_id,
      commodity_id: p.commodity_id,
      commodity_name: p.commodity_id,
      price_rs: p.price_rs,
      reconciled_price_rs: p.price_rs,
      agmarknet_price_rs: null,
      enam_price_rs: null,
      confidence: 0.85,
      price_trend: 'flat',
      date: p.date || '',
      source_used: p.source || '',
    }))

    res.setHeader('Access-Control-Allow-Origin', '*')
    res.json({ market_prices: enriched, total: enriched.length, source: 'neon' })
  } catch (e: any) {
    res.status(500).json({ error: e.message })
  }
}
