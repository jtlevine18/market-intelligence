import type { VercelRequest, VercelResponse } from '@vercel/node'

const COMMODITY_NAMES: Record<string, string> = {
  'RICE-SAMBA': 'Rice (Samba Paddy)', 'TUR-FIN': 'Turmeric', 'BAN-ROB': 'Banana',
  'GNUT-POD': 'Groundnut', 'COT-MCU': 'Cotton', 'ONI-RED': 'Onion',
  'COP-DRY': 'Coconut (Copra)', 'MZE-YEL': 'Maize', 'URD-BLK': 'Black Gram (Urad)',
  'MNG-GRN': 'Green Gram (Moong)',
}

const MANDI_NAMES: Record<string, string> = {
  'MND-TJR': 'Thanjavur', 'MND-MDR': 'Madurai Periyar', 'MND-SLM': 'Salem',
  'MND-ERD': 'Erode (Turmeric Market)', 'MND-CBE': 'Coimbatore', 'MND-TNV': 'Tirunelveli',
  'MND-KBK': 'Kumbakonam', 'MND-VPM': 'Villupuram', 'MND-DGL': 'Dindigul',
  'MND-TRC': 'Tiruchirappalli', 'MND-NGP': 'Nagapattinam', 'MND-KRR': 'Karur',
  'MND-VLR': 'Vellore', 'MND-TUT': 'Thoothukudi', 'MND-RMD': 'Ramanathapuram',
}

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
      mandi_name: MANDI_NAMES[p.mandi_id] || p.mandi_id,
      commodity_id: p.commodity_id,
      commodity_name: COMMODITY_NAMES[p.commodity_id] || p.commodity_id,
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
