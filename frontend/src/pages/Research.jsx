import { useEffect, useState } from 'react'
import { api } from '../api.js'
import Chart from '../components/Chart.jsx'

const defaults = { reference: '房屋新开工面积当月同比', target: '水泥产量当月同比', rho: 0.5, max_lag: 12, window: 24 }

function exportResult(data) {
  const text = `# 产业关联研究结果\n\n> ${data.scope}\n\n来源：${data.metadata.source_file}\n\n口径：${data.metadata.processing}\n\n## 分析参数\n\n${JSON.stringify(data.parameters)}\n\n## 灰色关联排序\n\n|指标|关联度|\n|---|---|\n${data.grey.ranking.map(r => `|${r.name}|${r.grade}|`).join('\n')}\n\n共同样本：${data.grey.sample_count}，${data.grey.start} 至 ${data.grey.end}\n\n## 时差相关\n\n${data.lag.lag_definition}\n\n|时差（月）|相关系数|有效样本|\n|---|---|---|\n${data.lag.lags.map(r => `|${r.lag_months}|${r.correlation ?? '不可计算'}|${r.sample_count}|`).join('\n')}\n\n## 北京子网络中心性\n\n来源：${JSON.stringify(data.network.source)}\n\n|行业|入强度|出强度|PageRank|\n|---|---|---|---|\n${data.network.ranking.map(r => `|${r.name}|${r.in_strength}|${r.out_strength}|${r.pagerank}|`).join('\n')}\n\n## 方法与局限\n\n${[data.grey.method, data.lag.method, data.network.method, ...data.metadata.warnings, ...data.grey.warnings, ...data.lag.warnings, ...data.network.warnings].map(w => `- ${w}`).join('\n')}\n\n数据校验指纹：${data.metadata.sha256}\n`
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = '产业关联研究结果.md'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function Research() {
  const [catalog, setCatalog] = useState(null)
  const [form, setForm] = useState(defaults)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let active = true
    api.get('/api/research/catalog').then(r => {
      if (active) {
        setCatalog(r.data)
        setForm(prev => ({ ...prev, start: r.data.start, end: r.data.end }))
      }
    }).catch(e => { if (active) setError(e.response?.data?.detail || e.message) })
    return () => { active = false }
  }, [])
  const update = (key, value) => {
    setForm(prev => ({ ...prev, [key]: value }))
    setResult(null)
  }
  const run = async e => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const response = await api.post('/api/research/analyze', form)
      setResult(response.data)
    } catch (e) {
      const detail = e.response?.data?.detail
      setError(typeof detail === 'string' ? detail : '分析失败，请检查参数或后端连接')
    } finally { setBusy(false) }
  }
  const chartBase = { tooltip: { trigger: 'axis' }, grid: { left: 55, right: 25, top: 30, bottom: 65 } }
  return (
    <div className="research-page p-8 space-y-6 max-w-7xl mx-auto">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-xl font-bold">产业关联研究</h1><p className="text-xs text-slate-500 mt-2">V2 实验模块 · 灰色关联 / 投入产出网络 / 动态时差</p></div>
        {result && <div className="flex gap-3 no-print"><button className="text-sm text-blue-300" onClick={() => exportResult(result)}>导出研究结果</button><button className="text-sm text-blue-300" onClick={() => window.print()}>打印 / 另存 PDF</button></div>}
      </header>
      <div className="card text-sm text-amber-200 leading-6">本页为描述性研究，不参与风险评分。全国月度指标与北京13部门子网络分别展示，不混合计算；相关性、灰色关联度和中心性均不代表因果传导。</div>
      {error && <div role="alert" className="card text-red-300">{error}</div>}
      {!catalog && !error && <p className="text-slate-400">正在读取研究数据…</p>}
      {catalog && <>
        <form onSubmit={run} className="card grid grid-cols-1 md:grid-cols-3 gap-4 no-print">
          <fieldset disabled={busy} className="contents">
            {['reference', 'target'].map((key, i) => <label key={key} className="text-xs text-slate-400">{i === 0 ? '参考指标 X' : '时差目标 Y'}<select value={form[key]} onChange={e => update(key, e.target.value)} className="input-glow w-full mt-2 rounded-lg p-2 text-slate-200">{catalog.fields.map(f => <option key={f.name}>{f.name}</option>)}</select></label>)}
            <label className="text-xs text-slate-400">灰色分辨系数<input type="number" required min="0.01" max="1" step="0.01" value={form.rho} onChange={e => update('rho', Number(e.target.value))} className="input-glow w-full mt-2 rounded-lg p-2" /></label>
            {['start', 'end'].map((key, i) => <label key={key} className="text-xs text-slate-400">{i === 0 ? '开始月份' : '结束月份'}<input type="month" required min={catalog.start} max={catalog.end} value={form[key]} onChange={e => update(key, e.target.value)} className="input-glow w-full mt-2 rounded-lg p-2" /></label>)}
            <div className="flex gap-3">{[['max_lag', '最大时差', 0, 24], ['window', '滚动窗口', 12, 60]].map(([key, label, min, max]) => <label key={key} className="text-xs text-slate-400">{label}（月）<input type="number" required min={min} max={max} step="1" value={form[key]} onChange={e => update(key, Number(e.target.value))} className="input-glow w-full mt-2 rounded-lg p-2" /></label>)}</div>
            <button disabled={form.reference === form.target} className="rounded-lg bg-blue-600 px-4 py-2 text-sm disabled:opacity-40">{busy ? '计算中…' : '运行关联研究'}</button>
          </fieldset>
        </form>
        <details className="card text-xs text-slate-400 leading-6"><summary className="cursor-pointer text-slate-200">数据来源与加工口径（{catalog.start} — {catalog.end}）</summary><p>{catalog.metadata.source_file} · {catalog.metadata.region} · {catalog.metadata.verification}</p><p>{catalog.metadata.processing}</p>{catalog.metadata.warnings.map(w => <p key={w}>{w}</p>)}<table className="w-full mt-3 text-left"><thead><tr><th>指标</th><th>有效月份</th><th>原表</th></tr></thead><tbody>{catalog.fields.map(f => <tr key={f.name}><td>{f.name}</td><td>{f.sample_count}</td><td>{f.sheet}</td></tr>)}</tbody></table></details>
      </>}
      {result && <>
        <p className="text-xs text-slate-400">参考：{result.parameters.reference}；目标：{result.parameters.target}；区间：{result.parameters.start} — {result.parameters.end}；ρ={result.parameters.rho}；最大时差±{result.parameters.max_lag}月；滚动窗口{result.parameters.window}月</p>
        <div className="card"><h2 className="section-label mb-3">全国当月同比趋势（% · 缺失月份不连线）</h2><Chart option={{ ...chartBase, legend: { bottom: 0 }, xAxis: { type: 'category', data: (() => { const out = []; let [y, m] = result.plot.dates[0].split('-').map(Number); const end = result.plot.dates.at(-1); while (`${y}-${String(m).padStart(2, '0')}` <= end) { out.push(`${y}-${String(m).padStart(2, '0')}`); if (++m > 12) { m = 1; y++ } } return out })(), axisLabel: { rotate: 40 } }, yAxis: { type: 'value' }, series: ['reference', 'target'].map((key, i) => ({ name: i === 0 ? result.parameters.reference : result.parameters.target, type: 'line', connectNulls: false, showSymbol: false, data: (() => { const map = Object.fromEntries(result.plot.dates.map((d, j) => [d, result.plot[key][j]])); const out = []; let [y, m] = result.plot.dates[0].split('-').map(Number); while (`${y}-${String(m).padStart(2, '0')}` <= result.plot.dates.at(-1)) { out.push(map[`${y}-${String(m).padStart(2, '0')}`] ?? null); if (++m > 12) { m = 1; y++ } } return out })() })) }} /></div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="card"><h2 className="section-label">灰色关联排序 · 共同样本 {result.grey.sample_count}</h2><p className="text-xs text-slate-500 mt-2">{result.grey.start} — {result.grey.end}；不是因果强度</p><Chart option={{ ...chartBase, grid: { left: 160, right: 35, top: 20, bottom: 30 }, xAxis: { type: 'value', min: 0, max: 1 }, yAxis: { type: 'category', inverse: true, data: result.grey.ranking.map(r => r.name) }, series: [{ type: 'bar', data: result.grey.ranking.map(r => r.grade), label: { show: true, position: 'right' }, itemStyle: { color: '#38bdf8' } }] }} /></div>
          <div className="card"><h2 className="section-label">时差相关扫描 · 不自动确认传导时滞</h2><p className="text-xs text-slate-500 mt-2">{result.lag.lag_definition}</p><Chart option={{ ...chartBase, xAxis: { type: 'category', data: result.lag.lags.map(r => r.lag_months), name: '月' }, yAxis: { type: 'value', min: -1, max: 1 }, series: [{ name: 'Pearson相关系数', type: 'line', data: result.lag.lags.map(r => r.correlation), connectNulls: false }] }} /><p className="text-xs text-slate-400">样本内最大绝对相关：{result.lag.strongest_absolute_correlation ? `${result.lag.strongest_absolute_correlation.lag_months}月，r=${result.lag.strongest_absolute_correlation.correlation}，n=${result.lag.strongest_absolute_correlation.sample_count}` : '样本不足或序列恒定'}</p></div>
        </div>
        <div className="card"><h2 className="section-label">同步滚动相关（{result.lag.window_months}个日历月窗口）</h2><Chart option={{ ...chartBase, xAxis: { type: 'category', data: result.lag.rolling.map(r => r.month), axisLabel: { rotate: 40 } }, yAxis: { type: 'value', min: -1, max: 1 }, series: [{ type: 'line', data: result.lag.rolling.map(r => r.correlation), connectNulls: false, showSymbol: false }] }} /></div>
        <div className="card"><h2 className="section-label">北京投入产出子网络 · {result.network.node_count}节点 / {result.network.edge_count}条非零边</h2><p className="text-xs text-slate-400 my-3">{result.network.edge_direction}。PageRank反映该方向的网络中心性，不是风险概率。</p><p className="text-xs text-slate-500 mb-3">来源：{result.network.source.source} · {result.network.source.year}；{result.network.source.note}</p><table className="w-full text-sm text-left"><thead className="text-slate-500"><tr><th>行业</th><th>入强度</th><th>出强度</th><th>PageRank</th></tr></thead><tbody>{result.network.ranking.map(r => <tr key={r.name} className="border-t border-slate-800"><td className="py-2">{r.name}</td><td>{r.in_strength}</td><td>{r.out_strength}</td><td className="text-cyan-300">{r.pagerank}</td></tr>)}</tbody></table></div>
        <div className="card text-xs text-slate-400 leading-6"><h2 className="section-label mb-3">方法与解释边界</h2>{[result.grey.method, result.lag.method, result.network.method, ...result.grey.warnings, ...result.lag.warnings, ...result.network.warnings].map(w => <p key={w}>{w}</p>)}</div>
      </>}
    </div>
  )
}
