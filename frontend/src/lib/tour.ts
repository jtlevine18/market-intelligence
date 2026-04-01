import type { Step } from 'react-joyride'

export const tourSteps: Step[] = [
  // ── Market Prices (/) ──
  {
    target: '[data-tour="hero"]',
    title: 'Meet your market broker',
    content:
      'Lakshmi harvests rice in Thanjavur. She has three mandis within 40km, each reporting different prices. ' +
      'This AI agent scrapes both government price databases, reconciles the discrepancies, and tells her exactly ' +
      'where and when to sell \u2014 down to the rupee.',
    placement: 'bottom',
    disableBeacon: true,
  },
  {
    target: '[data-tour="stage-cards"]',
    title: 'Three stages, one decision',
    content:
      'First: scrape prices from Agmarknet (data.gov.in API) and eNAM for 15 Tamil Nadu mandis. ' +
      'Second: when they disagree \u2014 and they do, 5\u201312% of the time \u2014 investigate and reconcile. ' +
      'Third: compute the best (mandi, timing) combination after transport costs and storage losses.',
    placement: 'bottom',
    disableBeacon: true,
  },
  {
    target: '[data-tour="metrics"]',
    title: 'Live numbers',
    content:
      '15 mandis, 10 commodities (rice, groundnut, turmeric, cotton, onion...), and every price conflict ' +
      'resolved automatically. These update after each pipeline run.',
    placement: 'top',
    disableBeacon: true,
  },
  // ── Inputs (/inputs) ──
  {
    target: '[data-tour="inputs-title"]',
    title: 'The problem nobody solves',
    content:
      'Agmarknet says \u20b92,100 for rice at Thanjavur. eNAM says \u20b92,250. Same market, same day. ' +
      'No existing tool reconciles these \u2014 farmers and traders just guess. ' +
      'This agent investigates using 5 different checks.',
    placement: 'bottom',
    disableBeacon: true,
  },
  {
    target: '[data-tour="inputs-reconciled"]',
    title: 'Investigation, not averaging',
    content:
      'The agent checks neighboring mandis, seasonal norms, arrival volumes, and transport arbitrage. ' +
      'If Thanjavur says \u20b92,100 but every neighbor says \u20b92,200+, Thanjavur\u2019s data is probably stale. ' +
      'Each resolution shows the full reasoning chain.',
    placement: 'top',
    disableBeacon: true,
  },
  {
    target: '[data-tour="inputs-metrics"]',
    title: 'Trust, quantified',
    content:
      'Every reconciled price gets a confidence score. Poor-reporting mandis score lower. ' +
      'The system is transparent about what it knows and what it\u2019s guessing.',
    placement: 'bottom',
    disableBeacon: true,
  },
  // ── Forecast (/forecast) ──
  {
    target: '[data-tour="forecast-title"]',
    title: 'Should she sell now or wait?',
    content:
      'Rice prices typically drop 15% in October (post-harvest glut) and climb through May. ' +
      'The model uses 15 features \u2014 seasonal patterns, rainfall, mandi arrivals \u2014 to predict ' +
      'prices at 7, 14, and 30 days. That turns "sell now or wait" from a guess into a calculation.',
    placement: 'bottom',
    disableBeacon: true,
  },
  {
    target: '[data-tour="forecast-metrics"]',
    title: 'Confidence matters',
    content:
      'Forecasts come with confidence intervals. A prediction of \u20b92,300 \u00b1 \u20b9150 means something different ' +
      'than \u20b92,300 \u00b1 \u20b9500. The system shows both so the farmer can weigh the risk.',
    placement: 'bottom',
    disableBeacon: true,
  },
  // ── Sell Advisor (/sell) ──
  {
    target: '[data-tour="sell-title"]',
    title: 'The full calculation',
    content:
      'Lakshmi (rice, Thanjavur), Kumar (turmeric, Erode), Meena (banana, Dindigul). For each farmer, ' +
      'the agent evaluates every nearby mandi at every time horizon: market price minus transport, ' +
      'minus storage loss, minus mandi fees = net price. Then recommends the best option.',
    placement: 'bottom',
    disableBeacon: true,
  },
  {
    target: '[data-tour="sell-metrics"]',
    title: 'Real tradeoffs, real numbers',
    content:
      'Kumbakonam might offer \u20b9150 more per quintal than Thanjavur, but it\u2019s 30km away. ' +
      'Transport costs \u20b980. Net gain: \u20b970. Worth the trip? That\u2019s what the options table shows \u2014 ' +
      'every cost component, transparent.',
    placement: 'bottom',
    disableBeacon: true,
  },
  // ── Final (/) ──
  {
    target: '[data-tour="hero"]',
    title: 'The hard problem remains',
    content:
      'This system automates the journey from messy government data to a personalized sell recommendation. ' +
      'The hard problems that remain are human: getting smartphones into farmers\u2019 hands, ' +
      'building trust in data-driven advice, and connecting this to the platforms farmers already use. ' +
      'That\u2019s where the investment should go.',
    placement: 'center',
    disableBeacon: true,
  },
]

export const stepRoutes: Record<number, string> = {
  0: '/',
  1: '/',
  2: '/',
  3: '/inputs',
  4: '/inputs',
  5: '/inputs',
  6: '/forecast',
  7: '/forecast',
  8: '/sell',
  9: '/sell',
  10: '/',
}

export const tourStyles = {
  options: {
    zIndex: 10000,
    arrowColor: '#1a1a1a',
    backgroundColor: '#1a1a1a',
    primaryColor: '#d4a019',
    textColor: '#e0dcd5',
    overlayColor: 'rgba(0, 0, 0, 0.45)',
  },
  tooltip: {
    borderRadius: 10,
    padding: '20px 22px',
    maxWidth: 380,
    fontFamily: '"DM Sans", system-ui, sans-serif',
    fontSize: '0.88rem',
    lineHeight: 1.6,
  },
  tooltipTitle: {
    fontFamily: '"Source Serif 4", Georgia, serif',
    fontWeight: 700,
    fontSize: '1.05rem',
    color: '#d4a019',
    marginBottom: 8,
  },
  tooltipContent: {
    padding: '8px 0 0',
  },
  buttonNext: {
    backgroundColor: '#d4a019',
    color: '#fff',
    borderRadius: 6,
    fontFamily: '"DM Sans", system-ui, sans-serif',
    fontWeight: 600,
    fontSize: '0.8rem',
    letterSpacing: '0.5px',
    textTransform: 'uppercase' as const,
    padding: '8px 18px',
  },
  buttonBack: {
    color: '#888',
    fontFamily: '"DM Sans", system-ui, sans-serif',
    fontWeight: 500,
    fontSize: '0.8rem',
    marginRight: 8,
  },
  buttonSkip: {
    color: '#666',
    fontFamily: '"DM Sans", system-ui, sans-serif',
    fontSize: '0.75rem',
  },
  spotlight: {
    borderRadius: 10,
  },
  beacon: {
    display: 'none',
  },
  beaconInner: {
    display: 'none',
  },
  beaconOuter: {
    display: 'none',
  },
}
