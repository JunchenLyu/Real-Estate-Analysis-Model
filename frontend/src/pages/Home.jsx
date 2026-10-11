import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { chat, riskColor, getHealth, getAgentMode, setAgentMode } from '../api.js'
import Chart from '../components/Chart.jsx'

const MODE_OPTIONS = [
  { value: 'auto', label: '自动（推荐）', desc: '配置了LLM则用LLM，失败自动降级' },
  { value: 'offline', label: '离线模式（数据零出网）', desc: '强制本地规则引擎，不上传任何数据' },
  { value: 'llm_only', label: '仅LLM（不降级）', desc: 'LLM失败直接报错，需已配置API' },
]

const SUGGESTIONS = [
  '分析房地产投资下降15%的影响',
  '房价下跌20%会对哪些行业造成冲击？',
  '房地产销售下滑对家电家具产业链的传导路径',
]

const PIPELINE = ['知识库检索', '投入产出模型测算', '风险评分', '历史案例对比']

export default function Home() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [health, setHealth] = useState(null)

  useEffect(() => { getHealth().then(setHealth).catch(() => {}) }, [])

  // Agent 运行模式选择（auto/offline/llm_only）
  const [modeInfo, setModeInfo] = useState(null)
  const [modeOpen, setModeOpen] = useState(false)
  useEffect(() => { getAgentMode().then(setModeInfo).catch(() => {}) }, [])

  const changeMode = async (mode) => {
    try {
      const r = await setAgentMode(mode)
      setModeInfo(prev => ({ ...prev, mode: r.mode, description: r.description }))
      getHealth().then(setHealth).catch(() => {})
      getAgentMode().then(setModeInfo).catch(() => {})
    } catch (e) {
      alert(e.response?.data?.detail || '切换失败')
    }
    setModeOpen(false)
  }

  // 删除单条对话（AI消息含报告时连报告一起删；user+ai 成对删除）
  const delMsg = (i) => {
    const m = messages[i]
    if (m?.report?.report_id) {
      fetch(`http://localhost:8000/api/report/${m.report.report_id}`, { method: 'DELETE' }).catch(() => {})
    }
    setMessages(msgs => {
      const out = [...msgs]
      let a = i, b = i
      if (m.role === 'user' && out[i + 1]?.role === 'ai') b = i + 1        // user → 连同紧随的ai
      if (m.role === 'ai' && out[i - 1]?.role === 'user') a = i - 1        // ai → 连同紧邻的user
      out.splice(a, b - a + 1)
      return out
    })
  }

  const clearAll = () => {
    if (!confirm(`清空全部 ${messages.length} 条对话？（已生成的报告仍可在报告中心删除）`)) return
    // 批量删除关联报告
    messages.filter(m => m.report?.report_id).forEach(m => {
      fetch(`http://localhost:8000/api/report/${m.report.report_id}`, { method: 'DELETE' }).catch(() => {})
    })
    setMessages([])
  }

  const send = async (q) => {
    const question = q || input
    if (!question.trim() || loading) return
    setInput('')
    setMessages(m => [...m, { role: 'user', text: question }])
    setLoading(true)
    // 流式：实时显示 Agent 工具调用轨迹（SSE）
    const traceKey = `t_${Date.now()}`
    setMessages(m => [...m, { role: 'ai', streaming: true, traceKey, events: [] }])
    try {
      const resp = await fetch(
        `http://localhost:8000/api/chat/stream?q=${encodeURIComponent(question)}`)
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n\n')
        buf = lines.pop()  // 末尾可能是不完整块
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6)
          if (payload === '[DONE]') continue
          let ev
          try { ev = JSON.parse(payload) } catch { continue }
          setMessages(m => m.map(msg =>
            msg.traceKey === traceKey
              ? (ev.type === 'tool'
                  ? { ...msg, events: [...msg.events, ev] }
                  : ev.type === 'error'
                    ? { ...msg, streaming: false, error: ev.message }
                    : { ...msg, report: ev.report, streaming: false })
              : msg))
        }
      }
    } catch (e) {
      setMessages(m => m.map(msg =>
        msg.traceKey === traceKey
          ? { ...msg, streaming: false, error: String(e.message || e) }
          : msg))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-full flex flex-col">
      <header className="px-8 py-5 border-b border-slate-800/70 flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl font-bold text-slate-100 tracking-tight">房地产产业链风险智能分析</h1>
          <div className="flex items-center gap-2 mt-1">
            <span className={`glow-dot ${health ? '' : '!bg-amber-400'}`} />
            <p className="text-xs text-slate-500">
              Agent 模式：<span className="text-slate-400">{health?.agent_mode || '检测中…'}</span>
              <span className="mx-1.5 text-slate-700">|</span>
              自动调用知识库 / 投入产出模型 / 风险评分 / 历史案例
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Agent 运行模式选择器 */}
          <div className="relative no-print">
            <button onClick={() => setModeOpen(o => !o)}
              className="text-xs px-3 py-2 rounded-lg border border-slate-700 text-slate-300 hover:border-blue-500/60 transition-colors flex items-center gap-2">
              <span className={`w-1.5 h-1.5 rounded-full ${modeInfo?.mode === 'offline' ? 'bg-emerald-400' : modeInfo?.mode === 'llm_only' ? 'bg-amber-400' : 'bg-blue-400'}`} />
              {MODE_OPTIONS.find(o => o.value === modeInfo?.mode)?.label || '自动（推荐）'}
              <span className="text-slate-600">▾</span>
            </button>
            {modeOpen && (
              <div className="absolute right-0 top-full mt-2 w-80 bg-slate-950/98 border border-slate-700 rounded-xl p-2 z-30 shadow-2xl backdrop-blur">
                {MODE_OPTIONS.map(o => {
                  const disabled = o.value === 'llm_only' && !modeInfo?.llm_available
                  const active = modeInfo?.mode === o.value
                  return (
                    <button key={o.value} disabled={disabled} onClick={() => changeMode(o.value)}
                      className={`w-full text-left px-3 py-2.5 rounded-lg transition-colors ${
                        active ? 'bg-blue-600/20 border border-blue-700/60'
                               : disabled ? 'opacity-40 cursor-not-allowed' : 'hover:bg-slate-800/70 border border-transparent'}`}>
                      <div className="flex items-center justify-between">
                        <span className={`text-sm ${active ? 'text-blue-300' : 'text-slate-200'}`}>{o.label}</span>
                        {active && <span className="text-[10px] text-blue-400">当前</span>}
                        {disabled && <span className="text-[10px] text-slate-600">未配置API</span>}
                      </div>
                      <div className="text-[11px] text-slate-500 mt-0.5">{o.desc}</div>
                    </button>
                  )
                })}
                <div className="border-t border-slate-800 mt-2 pt-2 px-3 text-[10px] text-slate-600 leading-4">
                  离线模式下上传数据与全部分析完全本地执行，适合敏感数据场景
                </div>
              </div>
            )}
          </div>
          {messages.length > 0 && (
            <button onClick={clearAll}
              className="text-xs px-3 py-2 rounded-lg border border-red-900/60 text-red-400 hover:bg-red-950/40 hover:border-red-700 transition-colors no-print">
              清空对话（{messages.length}）
            </button>
          )}
          <Link to="/dashboard"
            className="text-sm px-4 py-2 rounded-lg border border-slate-700 text-slate-300 hover:border-blue-500/60 hover:text-blue-300 hover:bg-blue-600/10 transition-all no-print">
            查看 Dashboard →
          </Link>
        </div>
      </header>

      <div className="flex-1 overflow-auto px-8 py-6">
        <div className="space-y-5 max-w-4xl w-full mx-auto">
          {messages.length === 0 && (
            <div className="card anim-fade-up overflow-hidden">
              <div className="absolute -top-16 -right-16 w-56 h-56 rounded-full bg-blue-600/10 blur-3xl pointer-events-none" />
              <div className="flex items-start gap-4">
                <div className="w-11 h-11 shrink-0 rounded-xl bg-gradient-to-br from-blue-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-blue-600/30">
                  <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-6 h-6">
                    <path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.2 2.2m8.4 8.4 2.2 2.2m0-12.8-2.2 2.2M7.8 16.2l-2.2 2.2" />
                    <circle cx="12" cy="12" r="3.2" />
                  </svg>
                </div>
                <div className="flex-1">
                  <h2 className="text-slate-100 font-semibold">您好，我是产业链风险分析智能体</h2>
                  <p className="text-slate-400 text-sm leading-7 mt-1.5">
                    输入房地产相关问题（如冲击情景），我将自动规划并调用
                    <span className="text-blue-400"> 知识库检索 </span>/
                    <span className="text-blue-400"> 投入产出模型 </span>/
                    <span className="text-blue-400"> 风险评分 </span>/
                    <span className="text-blue-400"> 历史案例 </span>
                    工具，生成结构化风险分析报告。
                  </p>
                </div>
              </div>
              <div className="mt-5 flex flex-wrap gap-2">
                {SUGGESTIONS.map(s => (
                  <button key={s} onClick={() => send(s)}
                    className="text-xs px-3.5 py-2 rounded-full border border-slate-700 bg-slate-900/50 text-slate-300 hover:border-blue-500/60 hover:text-blue-300 hover:bg-blue-600/10 hover:shadow-[0_0_14px_rgba(59,130,246,0.2)] transition-all">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => m.role === 'user' ? (
            <div key={i} className="group relative flex justify-end anim-fade-up">
              <div className="bg-gradient-to-br from-blue-600 to-blue-500 rounded-2xl rounded-br-sm px-4 py-2.5 max-w-xl text-sm shadow-lg shadow-blue-900/30">
                {m.text}
              </div>
              <button onClick={() => delMsg(i)} title="删除此对话"
                className="absolute -left-7 top-1/2 -translate-y-1/2 w-5 h-5 rounded flex items-center justify-center text-slate-700 hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-all">
                ✕
              </button>
            </div>
          ) : (
            <div key={i} className="group relative flex flex-col items-start gap-3 w-full anim-fade-up">
              {!m.streaming && (
                <button onClick={() => delMsg(i)} title="删除此对话"
                  className="absolute -left-7 top-1 w-5 h-5 rounded flex items-center justify-center text-slate-700 hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-all z-10">
                  ✕
                </button>
              )}
              {/* 流式：实时工具调用轨迹 */}
              {m.streaming && m.events?.length > 0 && (
                <div className="card max-w-3xl w-full py-4 space-y-2">
                  <div className="flex items-center gap-3 text-sm text-slate-300">
                    <div className="flex gap-1.5">
                      <span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" />
                    </div>
                    Agent 正在调用工具（{m.events.filter(e => e.status === 'done').length}/{m.events.length} 完成）…
                  </div>
                  <div className="loading-bar" />
                  <div className="space-y-1.5 font-mono text-[11px] pt-1">
                    {m.events.map((e, j) => e.status === 'start' ? (
                      <div key={j} className="flex items-center gap-2 text-slate-400">
                        <span className="text-blue-400">→</span>
                        <span className="text-blue-300">{e.tool}</span>
                        <span className="text-slate-600">{JSON.stringify(e.args).slice(0, 50)}</span>
                        <span className="text-amber-400 animate-pulse">执行中…</span>
                      </div>
                    ) : (
                      <div key={j} className="flex items-center gap-2 text-emerald-400/80">
                        <span>✓</span>
                        <span className="text-emerald-300">{e.tool}</span>
                        <span className="text-slate-600 truncate max-w-md">{e.result_preview?.slice(0, 60)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {m.error
                ? <div className="card !border-red-900/70 text-red-400 text-sm">{m.error}</div>
                : m.report && <ReportView report={m.report} />}
            </div>
          ))}

          {loading && (
            <div className="flex justify-start anim-fade-up">
              <div className="card max-w-3xl w-full py-4 space-y-3">
                <div className="flex items-center gap-3 text-sm text-slate-300">
                  <div className="flex gap-1.5">
                    <span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" />
                  </div>
                  Agent 正在规划工具调用…
                </div>
                <div className="loading-bar" />
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
                  {PIPELINE.map((p, i) => (
                    <span key={p} className="flex items-center gap-1.5">
                      <span className="text-blue-500/70">{i + 1}.</span>{p}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <footer className="px-8 pb-6 pt-2 max-w-4xl w-full mx-auto shrink-0 no-print">
        <div className="flex gap-3">
          <input value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && send()}
            placeholder="输入问题，例如：分析房地产投资下降15%的影响"
            className="input-glow flex-1 rounded-xl px-4 py-3 text-sm placeholder:text-slate-600" />
          <button onClick={() => send()} disabled={loading}
            className="bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-500 hover:to-cyan-500 disabled:opacity-50 disabled:hover:from-blue-600 rounded-xl px-7 text-sm font-medium shadow-lg shadow-blue-900/40 transition-all">
            分析
          </button>
        </div>
      </footer>
    </div>
  )
}

function ReportView({ report }) {
  const { summary, risk_level, risk_score, affected_industries, industry_scores,
          transmission_path, model_basis, data_basis, key_indicators, similar_cases, tool_trace, agent_mode, impact } = report
  const color = riskColor(risk_level)
  const impactChart = affected_industries?.length ? {
    tooltip: { trigger: 'axis' },
    grid: { left: 80, right: 40, top: 10, bottom: 30 },
    xAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    yAxis: { type: 'category', data: affected_industries.map(r => r.industry).reverse() },
    series: [{
      type: 'bar',
      data: affected_industries.map(r => ({ value: r.impact_pct, itemStyle: { color: r.impact_pct < 0 ? '#ef4444' : '#22c55e', borderRadius: 3 } })).reverse(),
      label: { show: true, position: 'right', formatter: '{c}%' },
      barMaxWidth: 18,
    }],
  } : null

  return (
    <div className="card max-w-3xl w-full space-y-6">
      <div className="flex items-start justify-between gap-4 pb-4 border-b border-slate-800/70">
        <div>
          <h3 className="text-gradient font-semibold text-lg">产业链波动分析报告</h3>
          <p className="text-[11px] text-slate-500 mt-1">由 Agent 自动生成 · 模式 {agent_mode || '-'}</p>
        </div>
        <div className="text-right shrink-0">
          <span className="text-3xl font-extrabold" style={{ color, textShadow: `0 0 24px ${color}55` }}>{risk_score ?? '-'}</span>
          <span className="text-xs text-slate-500"> / 100</span>
          <div className="mt-1">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-medium border"
              style={{ background: color + '18', color, borderColor: color + '45' }}>{risk_level}风险</span>
          </div>
        </div>
      </div>

      <p className="text-sm text-slate-300 leading-7">{summary}</p>

      {impactChart && (
        <div>
          <div className="section-label mb-2 flex items-center gap-2">
            行业影响（产出变动%，{              impact?.model?.startsWith('Ghosh') ? 'Ghosh 供给侧模型' : 'Leontief 需求侧模型'}测算）
            <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
              impact?.model?.startsWith('Ghosh')
                ? 'bg-amber-950/60 text-amber-300 border border-amber-800/60'
                : 'bg-blue-950/60 text-blue-300 border border-blue-800/60'}`}>
              {impact?.model?.startsWith('Ghosh') ? '供给侧冲击（供给约束）' : '需求侧冲击（最终需求）'}
            </span>
          </div>
          <Chart option={impactChart} height={260} />
        </div>
      )}

      {transmission_path?.length > 0 && (
        <div>
          <div className="section-label mb-3">风险传导路径</div>
          <div className="space-y-2">
            {transmission_path.map((t, i) => (
              <div key={i} className="flex items-start gap-3 text-sm">
                <span className="w-5 h-5 shrink-0 rounded-full bg-blue-600/15 border border-blue-500/40 text-[11px] flex items-center justify-center text-blue-300 mt-0.5">{i + 1}</span>
                <span className="text-slate-300 leading-6">{t}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {impact?.transmission_stages?.stages?.length > 0 && (
        <div>
          <div className="section-label mb-3">
            传导三阶段预判（{impact?.model?.startsWith('Ghosh') ? '供给约束传导框架' : '六案例归纳框架'}）
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {impact.transmission_stages.stages.map((s, i) => {
              const c = s.pressure >= 70 ? '#ef4444' : s.pressure >= 45 ? '#f97316' : '#22c55e'
              return (
                <div key={i} className="bg-slate-950/60 rounded-lg p-3.5 border border-slate-800/60 relative overflow-hidden">
                  <div className="absolute inset-x-0 bottom-0 h-1" style={{ background: c, opacity: 0.7, width: `${s.pressure}%` }} />
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-sm font-semibold text-slate-200">{i + 1}. {s.name}</span>
                    <span className="text-xs font-mono font-bold" style={{ color: c }}>{s.pressure}</span>
                  </div>
                  <div className="text-[11px] text-slate-500 mb-2">{s.window}</div>
                  <div className="text-xs text-slate-400 leading-5 mb-2">{s.mechanism}</div>
                  <div className="flex flex-wrap gap-1 mb-2">
                    {s.hit_industries.map(h => (
                      <span key={h} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800/70 text-slate-400 border border-slate-700/60">{h}</span>
                    ))}
                  </div>
                  <details className="text-[11px] text-slate-500">
                    <summary className="cursor-pointer hover:text-slate-400">验证指标与案例证据</summary>
                    <div className="mt-1.5 space-y-1">
                      <div>盯：{s.verify_indicators.slice(0, 3).join('、')}</div>
                      <div className="text-slate-600">{s.case_evidence?.slice(0, 60)}…</div>
                    </div>
                  </details>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {industry_scores?.length > 0 && (
        <div>
          <div className="section-label mb-2.5">行业风险评分（多指标加权模型）</div>
          <div className="flex flex-wrap gap-2">
            {industry_scores.map(s => {
              const c = riskColor(s.risk_level)
              return (
                <span key={s.industry} className="text-xs px-2.5 py-1.5 rounded-lg bg-slate-900/60 border"
                  style={{ color: c, borderColor: c + '35' }}>
                  {s.industry} <b>{s.risk_score}</b> · {s.risk_level}
                </span>
              )
            })}
          </div>
        </div>
      )}

      {similar_cases?.length > 0 && (
        <div>
          <div className="section-label mb-2.5">历史案例对比</div>
          <div className="space-y-2">
            {similar_cases.map((c, i) => (
              <div key={i} className="text-xs text-slate-400 border-l-2 border-amber-500/70 pl-3 py-1 bg-amber-500/[0.04] rounded-r-lg">
                <span className="text-amber-400 font-medium">{c.title}</span>：{c.peak_impact}
                <span className="text-slate-500"> — {c.lessons}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-xs">
        <div className="bg-slate-950/50 rounded-lg p-3.5 border border-slate-800/60">
          <div className="section-label mb-2">模型依据</div>
          <p className="text-slate-300 leading-6">{model_basis}</p>
        </div>
        <div className="bg-slate-950/50 rounded-lg p-3.5 border border-slate-800/60">
          <div className="section-label mb-2">数据依据（知识库检索）</div>
          <ul className="text-slate-400 space-y-1.5">
            {data_basis?.map((d, i) => <li key={i} className="leading-5">· {d}</li>)}
          </ul>
        </div>
      </div>

      {key_indicators?.length > 0 && (
        <div>
          <div className="section-label mb-2">建议关注指标</div>
          <div className="flex flex-wrap gap-1.5">
            {key_indicators.map(k => (
              <span key={k} className="text-xs px-2.5 py-1 rounded-md bg-slate-800/80 text-slate-300 border border-slate-700/80">{k}</span>
            ))}
          </div>
        </div>
      )}

      {tool_trace?.length > 0 && (
        <details className="text-xs text-slate-500 group">
          <summary className="cursor-pointer hover:text-slate-300 select-none flex items-center gap-2">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5 transition-transform group-open:rotate-90"><path d="m9 6 6 6-6 6" /></svg>
            Agent 工具调用轨迹（{tool_trace.length} 次）· 模式：{agent_mode}
          </summary>
          <div className="mt-2.5 space-y-1.5 font-mono">
            {tool_trace.map((t, i) => (
              <div key={i} className="bg-slate-950/70 border border-slate-800/60 rounded-lg p-2.5 leading-5">
                <span className="text-blue-400">{t.tool}</span>
                <span className="text-slate-500">({JSON.stringify(t.args)})</span>
                <span className="text-slate-600"> → </span>
                <span className="text-slate-400">{t.result_preview}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}
