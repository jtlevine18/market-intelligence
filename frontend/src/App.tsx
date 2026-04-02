import { useCallback, useEffect, useState } from 'react'
import { Routes, Route, useNavigate, useSearchParams } from 'react-router-dom'
import Joyride, { type CallBackProps, STATUS, EVENTS, ACTIONS } from 'react-joyride'
import { Package } from 'lucide-react'
import Sidebar from './components/Sidebar'
import MarketPrices from './pages/MarketPrices'
import Forecast from './pages/Forecast'
import SellOptimizer from './pages/SellOptimizer'
import Pipeline from './pages/Pipeline'
import Inputs from './pages/Inputs'
import { tourSteps, stepRoutes, tourStyles } from './lib/tour'
import TourTooltip from './components/TourTooltip'

export default function App() {
  const [searchParams] = useSearchParams()
  const [runTour, setRunTour] = useState(false)
  const [stepIndex, setStepIndex] = useState(0)
  const navigate = useNavigate()

  // Auto-start on first visit, or when ?tour=true
  useEffect(() => {
    const forced = searchParams.get('tour') === 'true'
    const seen = localStorage.getItem('market_tour_v2') === '1'
    if (forced || !seen) {
      const timer = setTimeout(() => {
        setRunTour(true)
        setStepIndex(0)
        localStorage.setItem('market_tour_v2', '1')
      }, 1500)
      return () => clearTimeout(timer)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Listen for relaunch from the Tour button
  useEffect(() => {
    function handleRelaunch() {
      navigate('/')
      setTimeout(() => {
        setStepIndex(0)
        setRunTour(true)
      }, 400)
    }
    window.addEventListener('relaunch-tour', handleRelaunch)
    return () => window.removeEventListener('relaunch-tour', handleRelaunch)
  }, [navigate])

  const handleJoyrideCallback = useCallback(
    (data: CallBackProps) => {
      const { status, action, index, type } = data

      if (status === STATUS.FINISHED || status === STATUS.SKIPPED || action === ACTIONS.CLOSE) {
        setRunTour(false)
        setStepIndex(0)
        return
      }

      if (type === EVENTS.STEP_AFTER) {
        const nextIndex = action === ACTIONS.PREV ? index - 1 : index + 1
        const nextRoute = stepRoutes[nextIndex]
        const currentRoute = stepRoutes[index]
        const needsNav = nextRoute !== undefined && nextRoute !== currentRoute

        setRunTour(false)

        if (needsNav) {
          navigate(nextRoute!)
          setTimeout(() => {
            setStepIndex(nextIndex)
            setRunTour(true)
          }, 1200)
        } else {
          setTimeout(() => {
            setStepIndex(nextIndex)
            setRunTour(true)
          }, 150)
        }
      }
    },
    [navigate],
  )

  return (
    <div className="flex min-h-screen">
      <Sidebar />

      <div className="flex-1 ml-56 flex flex-col">
        <header className="flex items-center justify-end h-10 px-8 shrink-0">
          <button
            onClick={() => window.dispatchEvent(new Event('relaunch-tour'))}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-sans font-medium text-warm-muted hover:text-[#1a1a1a] hover:bg-warm-header-bg transition-colors"
            title="Take the guided tour"
          >
            <Package size={14} />
            Tour
          </button>
        </header>

        <main className="flex-1 px-8 pb-8">
          <Routes>
            <Route path="/" element={<MarketPrices />} />
            <Route path="/forecast" element={<Forecast />} />
            <Route path="/sell" element={<SellOptimizer />} />
            <Route path="/pipeline" element={<Pipeline />} />
            <Route path="/inputs" element={<Inputs />} />
          </Routes>
        </main>
      </div>

      <Joyride
        steps={tourSteps}
        run={runTour}
        stepIndex={stepIndex}
        continuous
        showSkipButton
        scrollToFirstStep
        disableOverlayClose
        spotlightClicks={false}
        callback={handleJoyrideCallback}
        styles={tourStyles}
        tooltipComponent={TourTooltip}
        floaterProps={{ disableAnimation: true }}
        locale={{
          back: 'Back',
          close: 'Close',
          last: 'Finish',
          next: 'Next',
          skip: 'Skip tour',
        }}
      />
    </div>
  )
}
