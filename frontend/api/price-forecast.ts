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

    const forecasts = await sql`
      SELECT DISTINCT ON (mandi_id, commodity_id, horizon_days)
        run_id, mandi_id, commodity_id, forecast_date, horizon_days,
        predicted_price, ci_lower, ci_upper, model_type, created_at
      FROM price_forecasts
      ORDER BY mandi_id, commodity_id, horizon_days, created_at DESC
    `

    const grouped: Record<string, any> = {}
    for (const f of forecasts) {
      const key = `${f.mandi_id}|${f.commodity_id}`
      if (!grouped[key]) {
        grouped[key] = {
          mandi_id: f.mandi_id,
          mandi_name: MANDI_NAMES[f.mandi_id] || f.mandi_id,
          commodity_id: f.commodity_id,
          commodity_name: COMMODITY_NAMES[f.commodity_id] || f.commodity_id,
          current_price_rs: null,
          price_7d: null, price_14d: null, price_30d: null,
          ci_lower_7d: null, ci_upper_7d: null,
          direction: 'flat',
          confidence: 0.8,
        }
      }
      const g = grouped[key]
      if (f.horizon_days === 7) {
        g.price_7d = f.predicted_price
        g.ci_lower_7d = f.ci_lower
        g.ci_upper_7d = f.ci_upper
        g.current_price_rs = f.predicted_price
      } else if (f.horizon_days === 14) {
        g.price_14d = f.predicted_price
      } else if (f.horizon_days === 30) {
        g.price_30d = f.predicted_price
      }
    }

    const result = Object.values(grouped)
    res.setHeader('Access-Control-Allow-Origin', '*')
    res.json({ price_forecasts: result, total: result.length, source: 'neon' })
  } catch (e: any) {
    res.status(500).json({ error: e.message })
  }
}
