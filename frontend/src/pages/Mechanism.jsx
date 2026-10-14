import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getV2Overview } from '../api.js'

export default function Mechanism() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { getV2Overview().then(setData).catch(e => setError(e.response?.data?.detail || e.message)) }, [])
  const sourceLabel = ref => data?.theories.find(item => item.id === ref)?.title
    || data?.mechanisms.find(item => item.id === ref)?.title
    || data?.sources.find(item => item.id === ref)?.label
    || ref

  return (
    <div className="p-5 md:p-8 max-w-7xl mx-auto space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="text-xl font-bold">传导机制解析</h1><p className="text-xs text-slate-500 mt-1">实体需求、贸易信用、交付周期与金融反馈</p></div>
        <Link to="/simulation" className="text-sm text-blue-300 hover:text-blue-200">进入动态仿真 →</Link>
      </header>
      {error && <div role="alert" className="text-red-300 text-sm">{error}</div>}
      {!data && !error && <p className="text-slate-500 text-sm">正在读取机制库…</p>}
      {data && <div className="grid grid-cols-1 xl:grid-cols-[220px_1fr] gap-6">
        <nav className="xl:sticky xl:top-6 self-start border-l border-slate-800 pl-3 space-y-1">
          {data.mechanisms.map(item => <a key={item.id} href={`#${item.id}`} className="block px-2 py-2 text-xs text-slate-400 hover:text-blue-300">{item.title}<span className="block text-slate-600 mt-0.5">{item.window}</span></a>)}
        </nav>
        <div className="space-y-5">
          {data.mechanisms.map(item => <section id={item.id} key={item.id} className="card !rounded-lg scroll-mt-6">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <h2 className="text-base font-semibold text-slate-100">{item.title}</h2>
              <span className="text-xs text-cyan-300 border border-cyan-900 rounded-md px-2 py-1">{item.window}</span>
            </div>
            <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-2">
              {item.path.map((step, index) => <div key={step} className="relative min-h-20 border border-slate-800 rounded-md p-3 text-sm text-slate-300 leading-5">
                <span className="block text-[10px] text-slate-600 mb-1">步骤 {index + 1}</span>{step}
                {index < item.path.length - 1 && <span className="hidden md:block absolute -right-3 top-1/2 text-slate-600">→</span>}
              </div>)}
            </div>
            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div><h3 className="text-slate-500 mb-2">验证指标</h3><div className="flex flex-wrap gap-1.5">{item.indicators.map(x => <span key={x} className="px-2 py-1 bg-slate-900 rounded-md text-slate-300">{x}</span>)}</div></div>
              <div><h3 className="text-slate-500 mb-2">解释边界</h3><p className="text-amber-100/75 leading-5">{item.boundary}</p></div>
            </div>
            <div className="mt-4 text-xs text-slate-500">理论与数据依据：{item.source_refs.map(sourceLabel).join('、')}</div>
          </section>)}
        </div>
      </div>}
    </div>
  )
}
