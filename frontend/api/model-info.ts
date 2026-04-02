import type { VercelRequest, VercelResponse } from '@vercel/node'

export default async function handler(req: VercelRequest, res: VercelResponse) {
  res.setHeader('Access-Control-Allow-Origin', '*')
  res.json({
    model_metrics: {
      model_type: 'chronos_xgboost_mos',
      rmse: null,
      mae: null,
      r2: null,
      directional_accuracy: null,
      train_samples: null,
      features: [
        'current_reconciled_price', 'price_trend_7d', 'seasonal_index',
        'mandi_arrival_volume_7d_avg', 'rainfall_7d', 'days_since_harvest',
      ],
    },
    source: 'static',
  })
}
