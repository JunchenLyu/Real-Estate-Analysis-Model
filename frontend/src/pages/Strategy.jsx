import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getV2Overview } from '../api.js'

export default function Strategy() {
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState('regulator')
  const [error, setError] = useState('')
  useEffect(() => { getV2Overview().then(setData).catch(e => setError(e.response?.data?.detail || e.message)) }, [])
  const item = data?.strategies.find(x => x.id === selected)
  const theoryLink = ref => ref.startsWith('theory-') ? `/knowledge#${ref}` : `/mechanism#${ref}`
  const sourceLabel = ref => data?.theories.find(x => x.id === ref)?.title
    || data?.mechanisms.find(x => x.id === ref)?.title
    || data?.sources.find(x => x.id === ref)?.label
    || ref

  return (
    <div className="p-5 md:p-8 max-w-7xl mx-auto space-y-6">
      <header><h1 className="text-xl font-bold">分主体智能策略</h1><p className="text-xs text-slate-500 mt-1">固定知识条目组合，不由大模型新增策略或改变传导逻辑</p></header>
      {error && <div role="alert" className="text-sm text-red-300">{error}</div>}
      {data && item && <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-6">
        <div className="flex gap-2 overflow-x-auto pb-2 lg:block lg:space-y-1 lg:overflow-visible lg:pb-0 no-print">{data.strategies.map(x => <button key={x.id} onClick={() => setSelected(x.id)} className={`w-44 shrink-0 text-left px-3 py-3 rounded-lg border lg:w-full ${selected === x.id ? 'border-blue-500 bg-blue-600/10 text-blue-200' : 'border-transparent text-slate-400 hover:bg-slate-900'}`}><span className="text-sm">{x.stakeholder}</span><span className="block text-[11px] text-slate-600 mt-1">{x.objective}</span></button>)}</div>
        <section className="card !rounded-lg">
          <div className="border-b border-slate-800 pb-4"><h2 className="text-lg font-semibold text-slate-100">{item.stakeholder}</h2><p className="text-sm text-cyan-300 mt-1">{item.objective}</p></div>
          <div className="mt-5"><h3 className="section-label mb-3">策略组合</h3><ol className="space-y-3">{item.actions.map((action, index) => <li key={action} className="flex gap-3 text-sm text-slate-300 leading-6"><span className="w-6 h-6 shrink-0 rounded-full border border-blue-800 text-blue-300 text-xs flex items-center justify-center">{index + 1}</span><span>{action}</span></li>)}</ol></div>
          <div className="mt-6"><h3 className="section-label mb-3">重点监测指标</h3><div className="flex flex-wrap gap-2">{item.indicators.map(x => <span key={x} className="text-xs px-2.5 py-1.5 rounded-md bg-slate-900 text-slate-300 border border-slate-800">{x}</span>)}</div></div>
          <div className="mt-6"><h3 className="section-label mb-3">理论依据</h3><div className="flex flex-wrap gap-2">{item.source_refs.map(ref => <Link key={ref} to={theoryLink(ref)} className="text-xs text-blue-300 hover:text-blue-200 border border-blue-900 rounded-md px-2.5 py-1.5">查看 {sourceLabel(ref)} →</Link>)}</div></div>
          <p className="mt-6 border-t border-slate-800 pt-4 text-xs text-amber-100/75 leading-5">{data.disclaimer}</p>
        </section>
      </div>}
    </div>
  )
}
