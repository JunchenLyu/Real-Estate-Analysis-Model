import { useEffect, useMemo, useState } from 'react'
import Chart from '../components/Chart.jsx'
import { runSimulation } from '../api.js'

const COLORS = ['#f59e0b', '#38bdf8', '#22c55e', '#ef4444']
const SERIES = [
  ['trade_credit', '中游贸易信用'], ['upstream_demand', '上游实体需求'],
  ['downstream_completion', '下游交付需求'], ['negative_feedback', '负向反馈'],
]

export default function Simulation() {
  const [shock, setShock] = useState(15)
  const [direction, setDirection] = useState('下降')
  const [result, setResult] = useState(null)
  const [month, setMonth] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const run = async () => {
    setBusy(true); setError(''); setPlaying(false); setMonth(0)
    try { setResult(await runSimulation({ shock_percent: shock, direction })) }
    catch (e) { setError(e.response?.data?.detail || '仿真失败') }
    finally { setBusy(false) }
  }
  useEffect(() => { run() }, [])
  useEffect(() => {
    if (!playing) return undefined
    const timer = setInterval(() => setMonth(value => value >= 24 ? 0 : value + 1), 650)
    return () => clearInterval(timer)
  }, [playing])

  const timelineOption = useMemo(() => result ? ({
    tooltip: { trigger: 'axis' }, legend: { bottom: 0 },
    grid: { left: 52, right: 20, top: 22, bottom: 55 },
    xAxis: { type: 'category', data: result.timeline.map(x => x.month), name: '冲击后月数' },
    yAxis: { type: 'value', min: 0, max: 100, name: '压力指数' },
    series: SERIES.map(([key, name], i) => ({ name, type: 'line', smooth: true, showSymbol: false, data: result.timeline.map(x => x[key]), lineStyle: { color: COLORS[i], width: 2 }, itemStyle: { color: COLORS[i] }, markLine: i === 0 ? { silent: true, symbol: 'none', lineStyle: { color: '#64748b', type: 'dashed' }, data: [{ xAxis: month }] } : undefined })),
  }) : null, [result, month])

  const impactOption = result ? {
    tooltip: { trigger: 'axis' }, grid: { left: 75, right: 35, top: 10, bottom: 25 },
    xAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    yAxis: { type: 'category', inverse: true, data: result.industry_impact.slice(0, 8).map(x => x.industry) },
    series: [{ type: 'bar', data: result.industry_impact.slice(0, 8).map(x => ({ value: x.impact_pct, itemStyle: { color: x.impact_pct < 0 ? '#ef4444' : '#22c55e' } })), label: { show: true, position: 'right', formatter: '{c}%' }, barMaxWidth: 18 }],
  } : null
  const current = result?.timeline[month]

  return (
    <div className="p-5 md:p-8 max-w-7xl mx-auto space-y-6">
      <header><h1 className="text-xl font-bold">动态传导仿真</h1><p className="text-xs text-slate-500 mt-1">房地产最终需求冲击的机制化时序压力测试</p></header>
      <section className="border-y border-slate-800 py-4 no-print">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_160px_120px] gap-4 items-end">
          <label className="text-xs text-slate-400">冲击幅度 {shock}%<input type="range" min="1" max="50" value={shock} onChange={e => setShock(Number(e.target.value))} className="w-full mt-3" /></label>
          <label className="text-xs text-slate-400">方向<select value={direction} onChange={e => setDirection(e.target.value)} className="input-glow w-full rounded-lg p-2 mt-2"><option>下降</option><option>上升</option></select></label>
          <button onClick={run} disabled={busy} className="rounded-lg bg-blue-600 px-4 py-2 text-sm disabled:opacity-50">{busy ? '计算中' : '重新计算'}</button>
        </div>
      </section>
      {error && <div role="alert" className="text-sm text-red-300">{error}</div>}
      {result && <>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><div className="text-sm text-slate-200">{result.scenario}</div><div className="text-xs text-slate-500 mt-1">{result.model_scope}</div></div>
          <div className="flex gap-2 no-print"><button onClick={() => setPlaying(v => !v)} className="w-9 h-9 rounded-lg border border-slate-700" title={playing ? '暂停' : '播放'}>{playing ? 'Ⅱ' : '▶'}</button><button onClick={() => { setPlaying(false); setMonth(0) }} className="w-9 h-9 rounded-lg border border-slate-700" title="重置">↺</button></div>
        </div>
        <section className="card !rounded-lg"><h2 className="section-label mb-2">传播节奏</h2><Chart option={timelineOption} height={360} />
          <label className="text-xs text-slate-500 no-print">冲击后第 {month} 个月<input type="range" min="0" max="24" value={month} onChange={e => { setPlaying(false); setMonth(Number(e.target.value)) }} className="w-full mt-2" /></label>
        </section>
        <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {SERIES.map(([key, label], i) => <div key={key} className="border border-slate-800 rounded-lg p-3"><div className="text-xs text-slate-500">{label}</div><div className="text-2xl font-semibold mt-2" style={{ color: COLORS[i] }}>{current?.[key] ?? 0}</div><div className="h-1 bg-slate-900 mt-2"><div className="h-full" style={{ width: `${current?.[key] ?? 0}%`, background: COLORS[i] }} /></div></div>)}
        </section>
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="card !rounded-lg"><h2 className="section-label mb-2">静态行业产出影响</h2><Chart option={impactOption} height={330} /></div>
          <div className="card !rounded-lg"><h2 className="section-label mb-4">关键时间窗</h2><div className="space-y-4">{result.milestones.map(item => <div key={item.id} className={`border-l-2 pl-3 ${month >= item.month ? 'border-cyan-400' : 'border-slate-700'}`}><div className="flex justify-between gap-2"><h3 className="text-sm text-slate-200">{item.title}</h3><span className="text-xs text-slate-500">{item.window}</span></div><p className="text-xs text-slate-400 leading-5 mt-1">{item.path.join(' → ')}</p></div>)}</div></div>
        </section>
      </>}
    </div>
  )
}

