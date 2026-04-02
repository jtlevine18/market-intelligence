import type { VercelRequest, VercelResponse } from '@vercel/node'

const FARMERS: Record<string, { name: string; lat: number; lon: number; commodity: string; quantity: number }> = {
  'FMR-LKSH': { name: 'Lakshmi', lat: 10.78, lon: 79.14, commodity: 'RICE-SAMBA', quantity: 25 },
  'FMR-KUMR': { name: 'Kumar', lat: 11.34, lon: 77.72, commodity: 'TUR-FIN', quantity: 15 },
  'FMR-MEEN': { name: 'Meena', lat: 10.36, lon: 77.97, commodity: 'BAN-ROB', quantity: 30 },
}

const COMMODITY_NAMES: Record<string, string> = {
  'RICE-SAMBA': 'Rice (Samba Paddy)',
  'TUR-FIN': 'Turmeric',
  'BAN-ROB': 'Banana',
  'GNUT-POD': 'Groundnut',
  'COT-MCU': 'Cotton',
  'ONI-RED': 'Onion',
  'COP-DRY': 'Coconut (Copra)',
  'MZE-YEL': 'Maize',
  'URD-BLK': 'Black Gram (Urad)',
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
    const recs = await sql`
      SELECT DISTINCT ON (farmer_id)
        run_id, farmer_id, commodity_id, best_mandi_id, best_timing,
        net_price_rs, potential_gain_rs, recommendation_text, created_at
      FROM sell_recommendations
      ORDER BY farmer_id, created_at DESC
    `

    const result = recs.map((r: any) => {
      const farmer = FARMERS[r.farmer_id] || { name: r.farmer_id, lat: 10.8, lon: 78.8, commodity: r.commodity_id, quantity: 20 }
      return {
        farmer_id: r.farmer_id,
        farmer_name: farmer.name,
        commodity_id: r.commodity_id,
        commodity_name: COMMODITY_NAMES[r.commodity_id] || r.commodity_id,
        quantity_quintals: farmer.quantity,
        farmer_lat: farmer.lat,
        farmer_lon: farmer.lon,
        best_option: {
          mandi_id: r.best_mandi_id,
          mandi_name: MANDI_NAMES[r.best_mandi_id] || r.best_mandi_id,
          sell_timing: r.best_timing || 'now',
          net_price_rs: r.net_price_rs,
          market_price_rs: r.net_price_rs,
          transport_cost_rs: 0,
          storage_loss_rs: 0,
          mandi_fee_rs: 0,
          distance_km: 0,
        },
        all_options: [],
        potential_gain_rs: r.potential_gain_rs || 0,
        recommendation_text: r.recommendation_text || '',
        recommendation_tamil: '',
        credit_readiness: null,
      }
    })

    res.setHeader('Access-Control-Allow-Origin', '*')
    res.json({ sell_recommendations: result, total: result.length, source: 'neon' })
  } catch (e: any) {
    res.status(500).json({ error: e.message })
  }
}
