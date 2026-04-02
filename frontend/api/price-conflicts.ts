import type { VercelRequest, VercelResponse } from '@vercel/node'

export default async function handler(req: VercelRequest, res: VercelResponse) {
  // Price conflicts are generated live by the pipeline reconciliation step
  // and stored in-memory only. From Neon we can reconstruct from market_prices
  // where multiple sources reported different prices.
  // For now, return empty — conflicts are a live pipeline feature.
  res.setHeader('Access-Control-Allow-Origin', '*')
  res.json({ price_conflicts: [], total: 0, source: 'neon' })
}
