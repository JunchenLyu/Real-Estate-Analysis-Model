import { useEffect, useState } from 'react'
import { uploadFile, riskColor, api, apiUrl } from '../api.js'

export default function Upload() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [uploads, setUploads] = useState([])

  const loadUploads = () => api.get('/api/uploads').then(r => setUploads(r.data.items)).catch(() => {})
  useEffect(() => { loadUploads() }, [])

  const onFile = async (file) => {
    if (!file) return
    setLoading(true); setError(null); setResult(null)
    try {
      const r = await uploadFile(file)
      setResult(r)
      loadUploads()
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setLoading(false)
    }
  }

  const viewFile = async (fid) => {
    const r = await api.get(`/api/upload/${fid}`).catch(() => null)
    if (r) setResult(r.data)
  }

  const risk = result?.risk_evaluation

  return (
    <div className="p-8 space-y-6 max-w-4xl">
      <header>
        <h1 className="text-xl font-bold tracking-tight">数据上传与分析</h1>
        <p className="text-xs text-slate-500 mt-1">支持 CSV / Excel，上传后自动进行统计分析与风险指标识别</p>
      </header>

      <div
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); onFile(e.dataTransfer.files[0]) }}
        className={`card text-center py-14 cursor-pointer transition-all anim-fade-up ${
          dragging
            ? '!border-blue-500 !border-solid shadow-[0_0_30px_rgba(59,130,246,0.25)] scale-[1.01]'
            : 'border-dashed !border-2 border-slate-700 hover:border-blue-600/70'}`}
        onClick={() => document.getElementById('fileInput').click()}>
        <input id="fileInput" type="file" accept=".csv,.xlsx,.xls" className="hidden"
          onChange={e => onFile(e.target.files[0])} />
        {loading ? (
          <div className="space-y-3 max-w-xs mx-auto">
            <div className="flex items-center justify-center gap-2.5 text-blue-400 text-sm">
              <div className="flex gap-1.5"><span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" /></div>
              正在分析数据…
            </div>
            <div className="loading-bar" />
          </div>
        ) : (
          <>
            <div className={`w-14 h-14 mx-auto rounded-2xl flex items-center justify-center transition-all ${
              dragging ? 'bg-blue-600/25 scale-110' : 'bg-slate-800/80'}`}>
              <svg viewBox="0 0 24 24" fill="none" stroke={dragging ? '#60a5fa' : '#64748b'} strokeWidth="1.7"
                strokeLinecap="round" strokeLinejoin="round" className="w-7 h-7">
                <path d="M12 16V6m0 0 4 4m-4-4-4 4" />
                <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
              </svg>
            </div>
            <p className="text-slate-300 text-sm mt-4">{dragging ? '松开鼠标开始分析' : '拖拽文件到此处，或点击选择'}</p>
            <p className="text-slate-600 text-xs mt-1.5">
              建议包含指标列：收入同比、资产负债率、现金流变化、市场需求变化 —— 系统将自动计算风险评分
            </p>
          </>
        )}
      </div>

      {error && <div className="card !border-red-900/70 text-red-400 text-sm anim-fade-up">{error}</div>}

      {result && (
        <div className="card space-y-5 anim-fade-up">
          <div className="flex items-center justify-between pb-4 border-b border-slate-800/70">
            <h3 className="font-medium text-blue-300 flex items-center gap-2">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" className="w-4 h-4">
                <path d="M7 3h7l5 5v13H7zM14 3v5h5" />
              </svg>
              {result.filename}
            </h3>
            <span className="text-xs text-slate-500">{result.shape[0]} 行 × {result.shape[1]} 列 · file_id: {result.file_id}</span>
          </div>

          <p className="text-sm text-slate-300 bg-slate-950/60 rounded-lg p-3.5 border border-slate-800/60 leading-6">{result.analysis_note}</p>

          {risk && (
            <div className="flex items-center gap-6 bg-slate-950/60 rounded-xl p-5 border border-slate-800/60">
              <div className="text-center shrink-0">
                <div className="text-4xl font-extrabold"
                  style={{ color: riskColor(risk.risk_level), textShadow: `0 0 22px ${riskColor(risk.risk_level)}55` }}>
                  {risk.risk_score}
                </div>
                <div className="text-xs mt-1.5 font-medium" style={{ color: riskColor(risk.risk_level) }}>{risk.risk_level}风险</div>
              </div>
              <div className="flex-1 grid grid-cols-2 gap-x-6 gap-y-3 text-xs">
                {Object.entries(risk.components).map(([k, v]) => (
                  <div key={k}>
                    <div className="flex justify-between text-slate-400"><span>{k}</span><span className="text-slate-200 font-medium">{v}</span></div>
                    <div className="h-1.5 bg-slate-800 rounded-full mt-1.5 overflow-hidden">
                      <div className="h-full bg-gradient-to-r from-blue-600 to-cyan-400 rounded-full transition-all duration-700" style={{ width: `${v}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <div className="section-label mb-2.5">数值列统计摘要</div>
            <div className="overflow-auto rounded-lg border border-slate-800/60">
              <table className="w-full text-xs">
                <thead><tr className="text-slate-400 bg-slate-950/70">
                  <th className="text-left py-2.5 px-4 font-medium">列名</th><th className="text-right px-3 font-medium">均值</th>
                  <th className="text-right px-3 font-medium">标准差</th><th className="text-right px-3 font-medium">最小值</th>
                  <th className="text-right px-3 font-medium">最大值</th><th className="text-right px-4 font-medium">最新值</th>
                </tr></thead>
                <tbody>
                  {Object.entries(result.describe).map(([col, s]) => (
                    <tr key={col} className="border-t border-slate-800/50 text-slate-300 hover:bg-slate-800/30 transition-colors">
                      <td className="py-2 px-4">{col}</td>
                      <td className="text-right px-3">{s.mean}</td><td className="text-right px-3">{s.std}</td>
                      <td className="text-right px-3">{s.min}</td><td className="text-right px-3">{s.max}</td>
                      <td className="text-right px-4 text-blue-400 font-medium">{s.latest ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* 已上传文件列表 */}
      <div className="card anim-fade-up">
        <div className="flex items-center justify-between mb-3">
          <div className="section-label">已上传文件（{uploads.length}）</div>
          <button onClick={loadUploads}
            className="text-xs text-slate-500 hover:text-blue-400 transition-colors">刷新</button>
        </div>
        {uploads.length === 0 ? (
          <div className="text-xs text-slate-600 py-4 text-center">暂无上传文件（服务重启后列表清空，原始文件保留在 backend/uploads/）</div>
        ) : (
          <div className="space-y-2">
            {uploads.map(u => (
              <div key={u.file_id}
                className="flex items-center gap-4 bg-slate-950/60 rounded-lg px-4 py-3 border border-slate-800/60 hover:border-slate-600 transition-colors">
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-slate-200 truncate">{u.filename}</div>
                  <div className="text-xs text-slate-500 mt-0.5 truncate">
                    {u.shape?.[0]} 行 × {u.shape?.[1]} 列 · {u.analysis_note?.slice(0, 50)}
                  </div>
                </div>
                {u.risk_score != null && (
                  <span className="text-sm font-bold shrink-0" style={{ color: riskColor(u.risk_level) }}>
                    {u.risk_score} · {u.risk_level}
                  </span>
                )}
                <a href={apiUrl(`/api/upload/${u.file_id}/raw`)} target="_blank" rel="noreferrer"
                  className="text-xs px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 shrink-0 no-underline">
                  原文
                </a>
                <button onClick={() => viewFile(u.file_id)}
                  className="text-xs px-2.5 py-1 rounded-md bg-blue-600/80 hover:bg-blue-500 text-white shrink-0">
                  查看
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
