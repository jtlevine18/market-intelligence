import { NavLink } from 'react-router-dom'
import {
  Home,
  FileText,
  TrendingUp,
  ShoppingCart,
  Activity,
  Settings,
} from 'lucide-react'

const NAV_ITEMS = [
  { to: '/', label: 'Home', icon: Home, tourId: 'nav-home' },
  { to: '/inputs', label: 'Data', icon: FileText, tourId: 'nav-inputs' },
  { to: '/demand', label: 'Forecast', icon: TrendingUp, tourId: 'nav-demand' },
  { to: '/procurement', label: 'Recommendations', icon: ShoppingCart, tourId: 'nav-procurement' },
  { to: '/pipeline', label: 'How It Works', icon: Settings, tourId: 'nav-pipeline' },
]

export default function Sidebar() {
  return (
    <aside
      className="fixed top-0 left-0 z-50 h-full w-56 flex flex-col"
      style={{ background: 'linear-gradient(180deg, #1a2220 0%, #1a1a1a 100%)' }}
    >
      {/* Brand — teal health accent */}
      <div className="flex items-center h-16 px-5 border-b border-white/10">
        <NavLink to="/" className="flex items-center gap-2.5 no-underline">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: '#2a9d8f' }}
          >
            <Activity size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white leading-tight font-serif m-0">
              Supply Chain
            </h1>
            <p className="text-[10px] text-[#e0dcd5] font-sans font-medium uppercase tracking-wider m-0">
              OPTIMIZER
            </p>
          </div>
        </NavLink>
      </div>

      {/* Navigation — teal accent for active state */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map(({ to, label, icon: Icon, tourId }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            data-tour={tourId}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-sans font-medium transition-colors duration-100 ${
                isActive
                  ? 'text-white'
                  : 'text-[#e0dcd5] hover:bg-white/5 hover:text-white'
              }`
            }
            style={({ isActive }) =>
              isActive
                ? { background: 'rgba(42, 157, 143, 0.15)', color: '#5ec4b6' }
                : undefined
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-white/10">
        <p className="text-[10px] text-[#e0dcd5]/60 font-sans uppercase tracking-wider m-0">
          Lagos State Health Network
        </p>
      </div>
    </aside>
  )
}
