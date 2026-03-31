import type { Step } from 'react-joyride'

export const tourSteps: Step[] = [
  // ── Dashboard ──
  {
    target: '[data-tour="hero"]',
    title: 'Welcome',
    content:
      'This tool helps district health officers keep essential medicines in stock. ' +
      'It reads messy facility reports, predicts which drugs will run out, and recommends what to order — ' +
      'across 10 real health facilities in Lagos State, Nigeria.',
    placement: 'bottom',
    disableBeacon: true,
  },
  {
    target: '[data-tour="stage-cards"]',
    title: 'From raw reports to an order plan',
    content:
      'Data moves through three stages: cleaning and verifying facility reports, ' +
      'predicting future drug demand based on disease patterns, and building an optimized order ' +
      'that fits the quarterly budget.',
    placement: 'bottom',
    disableBeacon: true,
  },
  {
    target: '[data-tour="metrics"]',
    title: 'Key numbers at a glance',
    content:
      'How many facilities are reporting, which drugs are at risk of running out, ' +
      'and how reliably the system is running. These update automatically after each run.',
    placement: 'top',
    disableBeacon: true,
  },
  // ── Inputs ──
  {
    target: '[data-tour="inputs-title"]',
    title: 'Turning paperwork into data',
    content:
      'Facility pharmacists send stock counts as unstructured text — sometimes handwritten, ' +
      'sometimes a WhatsApp message. AI reads these reports and pulls out the numbers that matter: ' +
      'how much of each drug is left, and how fast it\'s being used.',
    placement: 'bottom',
    disableBeacon: true,
  },
  {
    target: '[data-tour="inputs-extraction"]',
    title: 'Messy in, clean out',
    content:
      'On the left, the report as received. On the right, structured data the system can work with. ' +
      'This is where AI adds the most value — making sense of inconsistent, incomplete facility reports ' +
      'that would otherwise take hours to process by hand.',
    placement: 'top',
    disableBeacon: true,
  },
  {
    target: '[data-tour="inputs-metrics"]',
    title: 'Catching errors before they cause stockouts',
    content:
      'When a pharmacist\'s report doesn\'t match the logistics system, the AI flags the discrepancy, ' +
      'explains what it found, and produces a corrected number. Each facility gets a data reliability score.',
    placement: 'bottom',
    disableBeacon: true,
  },
  // ── Demand ──
  {
    target: '[data-tour="demand-title"]',
    title: 'Predicting what\'s needed next',
    content:
      'Rainfall drives malaria. Flooding drives diarrhoea. The system watches weather patterns and ' +
      'predicts how drug demand will shift — so facilities can order more antimalarials before ' +
      'the rainy season, not after they\'ve already run out.',
    placement: 'bottom',
    disableBeacon: true,
  },
  {
    target: '[data-tour="demand-metrics"]',
    title: 'Forecast confidence',
    content:
      'How many drugs were forecasted, how much demand is expected to change, and how confident ' +
      'the predictions are. Higher confidence means the system has better data to work with.',
    placement: 'bottom',
    disableBeacon: true,
  },
  // ── Procurement ──
  {
    target: '[data-tour="procurement-title"]',
    title: 'From forecast to action',
    content:
      'The map shows all 10 facilities — green means covered, red means medicines are running out. ' +
      'Dashed lines show where the AI recommends moving surplus stock between facilities ' +
      'instead of ordering more.',
    placement: 'bottom',
    disableBeacon: true,
  },
  {
    target: '[data-tour="procurement-metrics"]',
    title: 'What\'s covered and what\'s not',
    content:
      'Critical drug coverage, stockout risks, and budget allocation at a glance. ' +
      'Click any facility on the map to see its specific recommendations.',
    placement: 'bottom',
    disableBeacon: true,
  },
  {
    target: '[data-tour="procurement-tabs"]',
    title: 'Four ways to look at the same plan',
    content:
      'Overview shows the map. Action Plan lists what each facility should do. ' +
      'Impact shows what happens if recommendations are followed. ' +
      'Evidence shows exactly how the AI made its decisions.',
    placement: 'top',
    disableBeacon: true,
  },
  // ── Final ──
  {
    target: '[data-tour="hero"]',
    title: 'The hard problems remain',
    content:
      'This system automates the journey from messy reports to an optimized drug order. ' +
      'The hard problems that remain are human ones: health workers reporting accurately, ' +
      'facility staff acting on recommendations, and the physical logistics of getting drugs ' +
      'from warehouse to clinic. That\u2019s where the investment should go.',
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
  6: '/demand',
  7: '/demand',
  8: '/procurement',
  9: '/procurement',
  10: '/procurement',
  11: '/',
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
