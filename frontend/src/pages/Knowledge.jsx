import { useEffect, useState } from 'react'
import { getV2Cases, getV2Overview, kbSearch } from '../api.js'

export default function Knowledge() {
  const [overview, setOverview] = useState(null)
  const [cases, setCases] = useState([])
  const [query, setQuery] = useState('贸易信用与房地产产业链风险')
  const [results, setResults] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([getV2Overview(), getV2Cases()])
      .then(([meta, caseData]) => { setOverview(meta); setCases(caseData.items) })
      .catch(e => setError(e.response?.data?.detail || e.message))
  }, [])

  const search = async e => {
    e.preventDefault()
    if (!query.trim()) return
    setBusy(true); setError('')
    try { setResults((await kbSearch(query)).results || []) }
    catch (e) { setError(e.response?.data?.detail || '检索失败') }
    finally { setBusy(false) }
  }

  return (
    <div className="p-5 md:p-8 max-w-7xl mx-auto space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold">传导知识库</h1>
          <p className="text-xs text-slate-500 mt-1">理论模型、研究文献、数据口径与典型案例</p>
        </div>
        {overview && <div className="text-xs text-slate-400 flex gap-5">
          <span><b className="text-slate-100">{overview.knowledge_document_count}</b> 篇文档</span>
          <span><b className="text-slate-100">{overview.case_count}</b> 个案例</span>
          <span><b className="text-slate-100">{overview.models.length}</b> 类模型</span>
        </div>}
      </header>

      <form onSubmit={search} className="flex gap-2 max-w-3xl">
        <input value={query} onChange={e => setQuery(e.target.value)} aria-label="知识库检索词"
          className="input-glow flex-1 rounded-lg px-3 py-2.5 text-sm" />
        <button disabled={busy} className="rounded-lg bg-blue-600 px-4 py-2 text-sm disabled:opacity-50">
          {busy ? '检索中' : '检索'}
        </button>
      </form>
      {error && <div role="alert" className="text-sm text-red-300">{error}</div>}
      {results.length > 0 && <section className="border-y border-slate-800 py-4 space-y-3">
        <h2 className="section-label">检索结果</h2>
        {results.map((item, index) => <article key={`${item.source}-${index}`} className="border-l-2 border-cyan-700 pl-3">
          <div className="text-xs text-cyan-300">{item.category} · {item.source}</div>
          <p className="text-sm text-slate-300 leading-6 mt-1">{item.text}</p>
        </article>)}
      </section>}

      {overview && <>
        <section>
          <h2 className="text-base font-semibold mb-3">模型与运行状态</h2>
          <div className="overflow-x-auto border border-slate-800 rounded-lg">
            <table className="w-full text-sm text-left min-w-[760px]">
              <thead className="bg-slate-900 text-slate-400"><tr><th>模型</th><th>状态</th><th>用途</th><th>边界</th></tr></thead>
              <tbody>{overview.models.map(model => <tr key={model.id} className="border-t border-slate-800">
                <td className="p-3 text-slate-100">{model.name}<div className="text-[11px] text-slate-500 mt-1">{model.formula}</div></td>
                <td className="p-3"><span className={model.status === '可运行' ? 'text-emerald-300' : 'text-amber-300'}>{model.status}</span></td>
                <td className="p-3 text-slate-300">{model.purpose}</td>
                <td className="p-3 text-slate-500">{model.boundary}</td>
              </tr>)}</tbody>
            </table>
          </div>
        </section>

        <section>
          <h2 className="text-base font-semibold mb-3">理论条目</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {overview.theories.map(item => <article id={item.id} key={item.id} className="card !rounded-lg scroll-mt-6">
              <h3 className="text-sm font-semibold text-slate-100">{item.title}</h3>
              <p className="text-sm text-slate-300 leading-6 mt-2">{item.summary}</p>
              <dl className="text-xs mt-3 grid grid-cols-[54px_1fr] gap-y-1.5">
                <dt className="text-slate-600">证据</dt><dd className="text-slate-400">{item.evidence}</dd>
                <dt className="text-slate-600">边界</dt><dd className="text-amber-200/80">{item.boundary}</dd>
              </dl>
            </article>)}
          </div>
        </section>
      </>}

      <section>
        <h2 className="text-base font-semibold mb-1">典型负面案例与研究线索</h2>
        <p className="text-xs text-slate-500 mb-3">带“待核验”标记的条目只作为机制线索，不作为事实或因果证据。</p>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {cases.map(item => <details key={item.id} className="card !rounded-lg">
            <summary className="cursor-pointer list-none flex items-start justify-between gap-3">
              <span className="text-sm text-slate-100">{item.title}</span>
              <span className={`text-[10px] shrink-0 ${item.evidence_status ? 'text-amber-300' : 'text-emerald-300'}`}>
                {item.evidence_status ? '待核验' : '案例库'}
              </span>
            </summary>
            <p className="text-xs text-slate-400 leading-5 mt-3">{item.trigger}</p>
            <ol className="text-xs text-slate-400 mt-2 space-y-1">{item.transmission.map((step, i) => <li key={step}>{i + 1}. {step}</li>)}</ol>
            <p className="text-xs text-slate-500 mt-2">证据状态：{item.evidence_status || '沿用既有案例库口径，关键数值仍应回查原始来源'}</p>
          </details>)}
        </div>
      </section>
    </div>
  )
}

