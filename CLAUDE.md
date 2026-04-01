# Market Intelligence Agent

AI-powered post-harvest market timing and routing for Tamil Nadu smallholder farmers. Acts as an agent working FOR the farmer — scrapes conflicting government price data, reconciles discrepancies, forecasts prices, tells her when/where to sell, and assesses whether she should seek credit.

Part of Jeff Levine's portfolio: Weather AI tells her what to plant, Market Intelligence tells her when to sell and whether to borrow.

## Architecture

6-step pipeline: `INGEST → EXTRACT → RECONCILE → FORECAST → OPTIMIZE → RECOMMEND`

Each step has Claude agent + rule-based fallback. Pipeline runs end-to-end without Claude (set `ANTHROPIC_API_KEY` to enable Claude agents). Real NASA POWER data fetched for all 15 mandis. Agmarknet API integration available (set `MARKET_INTEL_USE_REAL_API=1`).

### Pipeline steps
1. **INGEST** — Agmarknet API (data.gov.in), eNAM scraper (simulated), NASA POWER weather
2. **EXTRACT** — Normalize commodity names, detect stale data, flag anomalies (5 Claude tools)
3. **RECONCILE** — Resolve Agmarknet vs eNAM price conflicts (5 Claude investigation tools: compare_sources, check_neighbors, seasonal_norms, verify_arrivals, transport_arbitrage)
4. **FORECAST** — XGBoost price model, 15 features, 7/14/30d horizons with confidence intervals
5. **OPTIMIZE** — Sell optimizer (net price after transport + storage loss + mandi fees) + credit readiness assessment
6. **RECOMMEND** — Claude-generated sell advice in English + Tamil via RAG

## Key files

### Backend (Python, FastAPI)
```
config.py                          — 15 mandis, 10 commodities, seasonal indices, loss coefficients, 3 farmer personas
src/api.py                         — 12 API endpoints + demo data generator (seed=42)
src/pipeline.py                    — MarketIntelligencePipeline orchestrator
src/ingestion/agmarknet.py         — data.gov.in API client (real + demo mode)
src/ingestion/enam_scraper.py      — Simulated eNAM prices with realistic 3-12% divergence
src/ingestion/nasa_power.py        — NASA POWER async client
src/extraction/agent.py            — Claude + RuleBasedExtractor (normalize, stale detection, anomalies)
src/reconciliation/agent.py        — Claude + RuleBasedReconciler (5 investigation tools)
src/forecasting/price_model.py     — XGBoostPriceModel (15 features, seasonal baseline fallback)
src/optimizer.py                   — SellOption/SellRecommendation + CreditReadiness assessment
src/recommendation_agent.py        — Claude broker agent (5 tools, English + Tamil)
src/rag/knowledge_base.py          — 27 chunks: TN crop calendars, MSP, storage, mandi regulations
src/rag/provider.py                — Hybrid FAISS + BM25 retrieval
src/store.py                       — Thread-safe PipelineStore singleton
src/scheduler.py                   — APScheduler, daily pipeline runs
src/db.py                          — Neon PostgreSQL ORM (optional, graceful fallback)
```

### Frontend (React 18, TypeScript, Vite, Tailwind)
```
frontend/src/pages/MarketPrices.tsx — Price grid (mandi x commodity) + Tamil Nadu map
frontend/src/pages/Forecast.tsx     — Price forecast charts with confidence bands
frontend/src/pages/SellOptimizer.tsx — Farmer cards + sell options table + credit readiness
frontend/src/pages/Pipeline.tsx     — 6-step architecture view + run history
frontend/src/pages/Inputs.tsx       — Side-by-side reconciliation with investigation steps
frontend/src/lib/api.ts             — Types + React Query hooks
frontend/src/lib/tour.ts            — Joyride tour (11 steps, story-driven)
frontend/src/components/Sidebar.tsx — Nav with amber/saffron accent
```

## Running locally

```bash
# Backend (port 7860)
cd ~/market-intelligence
python3 -m uvicorn src.api:app --port 7860 --reload

# Frontend (port 5173/5174)
cd frontend && npm run dev
```

Frontend proxies `/api/*` to localhost:7860 via vite.config.ts. Alternatively set `VITE_API_URL=http://localhost:7860` in `frontend/.env.local` for direct API calls.

## Environment variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | Claude agents for extraction/reconciliation/recommendation | None (rule-based fallback) |
| `MARKET_INTEL_USE_REAL_API` | Enable real Agmarknet API (set to `1`) | Disabled (demo data) |
| `DATA_GOV_IN_API_KEY` | data.gov.in API key | Public default key |
| `DATABASE_URL` | Neon PostgreSQL connection | None (in-memory demo) |
| `VITE_API_URL` | Frontend API base URL | Empty (uses proxy) |

## Data sources

- **Agmarknet** (data.gov.in) — Real daily wholesale prices for Tamil Nadu mandis. Commodity names: Paddy, Groundnut, Turmeric(Finger), Cotton, Coconut, Maize, Urad (Black Gram), Moong(Green Gram), Onion, Banana. API returns current-day data only (no historical date filters).
- **eNAM** — Simulated with realistic 3-12% price divergence from Agmarknet. Real scraper skeleton exists.
- **NASA POWER** — Real daily weather for all 15 mandi locations (temperature, precipitation, humidity).

## Credit readiness feature

Integrated into the sell optimizer (not a standalone tool). For each farmer, after computing sell options:
- Calculates expected/worst-case revenue from best sell option
- Sets max advisable loan at 40% of expected revenue
- Assesses strengths (high confidence, storage, good margins) and risks (low confidence, no storage, tight margins, few markets)
- Classifies as `strong`, `moderate`, or `not_yet`
- Generates bilingual advice (English + Tamil)

The framing is farmer-centric: "should you seek credit?" not "should a lender approve you?"

## Important conventions

- All prices in Indian Rupees (Rs or ₹), per quintal
- Demo data is deterministic (seed=42) and tells a coherent story about March 2026 Tamil Nadu markets
- CORS is set to `allow_origins=["*"]` for local development
- Pre-trained XGBoost model saved to `models/` directory — first pipeline run trains from scratch (~100s), subsequent runs load saved model
- Onion replaced sugarcane (sugarcane is sold at mills, not mandis)
- The tool is an AI agent working FOR the farmer — this framing matters for the portfolio narrative

## Deployment

- **Docker**: `Dockerfile` builds Python 3.11-slim + PyTorch CPU + sentence-transformers
- **HF Spaces**: Backend on port 7860
- **Vercel**: Frontend (static build from `frontend/dist/`)
- Do NOT push to production without confirming target with Jeff first
