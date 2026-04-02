import type { VercelRequest, VercelResponse } from '@vercel/node'

const COMMODITY_NAMES: Record<string, string> = {
  'RICE-SAMBA': 'Rice (Samba)', 'GNUT-POD': 'Groundnut', 'TUR-FIN': 'Turmeric',
  'COT-MCU': 'Cotton', 'ONI-RED': 'Onion', 'MZE-YEL': 'Maize',
  'URAD-BLK': 'Urad (Black Gram)', 'MOONG-GRN': 'Moong (Green Gram)',
  'BAN-ROB': 'Banana', 'COCO-HUS': 'Coconut',
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  try {
    const dbUrl = process.env.DATABASE_URL
    if (!dbUrl) {
      res.setHeader('Access-Control-Allow-Origin', '*')
      return res.json({ price_conflicts: [], total: 0, source: 'neon' })
    }
    const { neon } = await import('@neondatabase/serverless')
    const sql = neon(dbUrl)

    const runs = await sql`
      SELECT price_conflicts FROM pipeline_runs
      WHERE price_conflicts IS NOT NULL
      ORDER BY started_at DESC LIMIT 1
    `

    const raw = runs[0]?.price_conflicts || []

    // Enrich with commodity names and provide defaults for missing fields
    const conflicts = raw.map((c: any) => ({
      ...c,
      commodity_name: c.commodity_name || COMMODITY_NAMES[c.commodity_id] || c.commodity_id,
      delta_pct: c.delta_pct || 0,
      reasoning: c.reasoning || c.resolution || 'Auto-reconciled based on source reliability',
      confidence: c.confidence || 0.7,
      investigation_steps: c.investigation_steps || null,
    }))

    res.setHeader('Access-Control-Allow-Origin', '*')
    res.json({ price_conflicts: conflicts, total: conflicts.length, source: 'neon' })
  } catch (e: any) {
    res.setHeader('Access-Control-Allow-Origin', '*')
    res.json({ price_conflicts: [], total: 0, source: 'neon' })
  }
}
