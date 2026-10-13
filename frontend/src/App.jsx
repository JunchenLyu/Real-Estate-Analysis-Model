import { NavLink, Route, Routes } from 'react-router-dom'
import Home from './pages/Home.jsx'
import Dashboard from './pages/Dashboard.jsx'
import Upload from './pages/Upload.jsx'
import Reports from './pages/Reports.jsx'
import Research from './pages/Research.jsx'

const NAV = [
  {
    to: '/', label: '智能问答', desc: 'AI Agent 分析',
    icon: <path d="M8 10h8M8 14h5M21 12a9 9 0 1 1-4.4-7.7L21 3l-1 3.6A8.96 8.96 0 0 1 21 12Z" />,
  },
  {
    to: '/dashboard', label: '风险仪表盘', desc: 'Dashboard',
    icon: <path d="M3 13h4v8H3zM10 9h4v12h-4zM17 5h4v16h-4z" />,
  },
  {
    to: '/research', label: '产业关联研究', desc: 'V2 · 关联 / 网络 / 时差',
    icon: <path d="M4 19V5m0 14h16M7 15l4-5 4 3 5-7" />,
  },
  {
    to: '/upload', label: '数据上传', desc: 'CSV / Excel',
    icon: <path d="M12 16V4m0 0 4 4m-4-4-4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />,
  },
  {
    to: '/reports', label: '报告中心', desc: 'Markdown / PDF',
    icon: <path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6" />,
  },
]

export default function App() {
  return (
    <div className="flex h-screen">
      <aside className="no-print w-60 shrink-0 border-r border-slate-800/70 bg-[#070c17]/90 backdrop-blur flex flex-col">
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
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/research" element={<Research />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/reports" element={<Reports />} />
        </Routes>
      </main>
    </div>
  )
}
