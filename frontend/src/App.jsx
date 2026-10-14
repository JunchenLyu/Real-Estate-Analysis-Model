import { NavLink, Route, Routes } from 'react-router-dom'
import Home from './pages/Home.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Upload from './pages/Upload.jsx'
import Reports from './pages/Reports.jsx'
import Research from './pages/Research.jsx'
import Knowledge from './pages/Knowledge.jsx'
import Mechanism from './pages/Mechanism.jsx'
import Simulation from './pages/Simulation.jsx'
import Strategy from './pages/Strategy.jsx'

const NAV = [
  {
    to: '/', label: '首页', desc: '项目与智能问答',
    icon: <path d="M8 10h8M8 14h5M21 12a9 9 0 1 1-4.4-7.7L21 3l-1 3.6A8.96 8.96 0 0 1 21 12Z" />,
  },
  {
    to: '/knowledge', label: '传导知识库', desc: '理论 / 文献 / 案例',
    icon: <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5v13Zm0 0V6.5M8 8h8M8 12h6" />,
  },
  {
    to: '/static', label: '静态传导结果', desc: '需求 / 供给 / 关联',
    icon: <path d="M3 13h4v8H3zM10 9h4v12h-4zM17 5h4v16h-4z" />,
  },
  {
    to: '/mechanism', label: '传导机制解析', desc: '渠道 / 时滞 / 依据',
    icon: <path d="M4 7h6l2 3h8M4 17h6l2-3h8M17 7l3 3-3 3" />,
  },
  {
    to: '/simulation', label: '动态传导仿真', desc: '时序 / 压力测试',
    icon: <path d="M4 19V5m0 14h16M7 15l4-5 4 3 5-7M17 5h3v3" />,
  },
  {
    to: '/strategy', label: '分主体智能策略', desc: '受控知识输出',
    icon: <path d="M12 3a4 4 0 0 1 4 4c0 3-4 3-4 7M12 18v.01M5 20v-2a4 4 0 0 1 4-4h1" />,
  },
  {
    to: '/reports', label: '专业报告生成', desc: '完整 / 摘要 / PDF',
    icon: <path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6" />,
  },
]

export default function App() {
  return (
    <div className="flex h-screen flex-col lg:flex-row">
      <aside className="no-print w-60 shrink-0 border-r border-slate-800/70 bg-[#070c17] hidden lg:flex flex-col">
        <div className="p-5 border-b border-slate-800/70">
          <div className="text-gradient text-2xl font-extrabold leading-tight tracking-tight">RE Risk</div>
          <div className="text-slate-500 text-xs mt-1.5 leading-5">房地产产业链风险<br />智能分析平台</div>
        </div>
        <nav className="flex-1 p-3 space-y-1.5">
          {NAV.map(n => (
            <NavLink key={n.to} to={n.to} end={n.to === '/'}
              className={({ isActive }) =>
                `group flex items-center gap-3 px-3.5 py-2.5 rounded-xl border transition-all duration-200 ${isActive
                  ? 'bg-blue-600/15 text-blue-300 border-blue-500/40 shadow-[0_0_18px_rgba(59,130,246,0.18)]'
                  : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-200 border-transparent'}`}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
                strokeLinecap="round" strokeLinejoin="round"
                className="w-[18px] h-[18px] shrink-0 opacity-80 group-hover:opacity-100">
                {n.icon}
              </svg>
              <div>
                <div className="text-sm font-medium leading-tight">{n.label}</div>
                <div className="text-[11px] text-slate-500 mt-0.5">{n.desc}</div>
              </div>
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t border-slate-800/70">
          <div className="flex items-center gap-2 text-xs text-slate-400 mb-2">
            <span className="glow-dot" /> 引擎已就绪
          </div>
          <div className="text-[11px] text-slate-600 leading-5">
            LLM Agent + RAG 知识库<br />投入产出模型 + 风险评分
          </div>
        </div>
      </aside>
      <nav className="no-print lg:hidden flex shrink-0 overflow-x-auto border-b border-slate-800 bg-[#070c17] px-2 py-2 gap-1">
        {NAV.map(n => <NavLink key={n.to} to={n.to} end={n.to === '/'}
          className={({ isActive }) => `shrink-0 px-3 py-2 rounded-md text-xs ${isActive ? 'bg-blue-600/20 text-blue-300' : 'text-slate-400'}`}>{n.label}</NavLink>)}
      </nav>
      <main className="flex-1 overflow-auto min-w-0">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/static" element={<Research />} />
          <Route path="/research" element={<Research />} />
          <Route path="/mechanism" element={<Mechanism />} />
          <Route path="/simulation" element={<Simulation />} />
          <Route path="/strategy" element={<Strategy />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/reports" element={<Reports />} />
        </Routes>
      </main>
    </div>
  )
}
