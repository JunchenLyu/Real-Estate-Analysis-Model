import { useEffect, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { apiUrl, listReports, getReport, deleteReport, deleteAllReports } from '../api.js'

export default function Reports() {
  const [list, setList] = useState([])
  const [selected, setSelected] = useState(null)
  const [summaryOnly, setSummaryOnly] = useState(false)

  const load = () => listReports().then(r => setList(r.items)).catch(() => {})
  useEffect(() => { load() }, [])

  const open = async (rid) => {
    const r = await getReport(rid).catch(() => null)
    if (r) setSelected(r)
  }

  const del = async (rid) => {
    if (!confirm('删除这份报告？')) return
    await deleteReport(rid).catch(() => {})
    if (selected?.report_id === rid) setSelected(null)
    load()
  }

  const delAll = async () => {
    if (!confirm(`确定清空全部 ${list.length} 份报告？此操作不可恢复。`)) return
    await deleteAllReports().catch(() => {})
    setSelected(null)
    load()
  }

  return (
    <div className="p-5 md:p-8 space-y-6">
      <header className="flex items-center justify-between no-print">
        <div>
          <h1 className="text-xl font-bold tracking-tight">报告中心</h1>
          <p className="text-xs text-slate-500 mt-1">结构化金融分析报告（完整报告 / 精简摘要 / PDF 直下载）</p>
        </div>
        {list.length > 0 && (
          <button onClick={delAll}
            className="text-xs px-3.5 py-2 rounded-lg border border-red-900/60 text-red-400 hover:bg-red-950/40 hover:border-red-700 transition-colors">
            清空全部（{list.length}）
          </button>
        )}
      </header>

      {list.length === 0 ? (
        <div className="card text-sm text-slate-500 anim-fade-up">暂无报告 —— 在「智能问答」完成一次分析后自动生成。</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div className="flex gap-2 overflow-x-auto pb-2 lg:block lg:space-y-2 lg:overflow-visible lg:pb-0 no-print">
            {list.map((r, i) => (
              <div key={r.report_id}
                className={`group relative card card-hover !p-3.5 anim-fade-up cursor-pointer transition-colors w-72 shrink-0 lg:w-auto ${
                  selected?.report_id === r.report_id ? '!border-blue-500/60 shadow-[0_0_16px_rgba(59,130,246,0.15)]' : ''}`}
                style={{ animationDelay: `${i * 40}ms` }}
                onClick={() => open(r.report_id)}>
                <div className="text-sm text-slate-200 truncate pr-6">{r.question || '未命名分析'}</div>
                <div className="text-xs text-slate-500 mt-1.5">
                  {r.risk_score != null
                    ? <>风险 <span className="text-slate-300 font-medium">{r.risk_score}</span> · {r.risk_level}</>
                    : <span>{r.analysis_status_label || '定性分析'}</span>} · {r.created_at}
                </div>
                <button onClick={e => { e.stopPropagation(); del(r.report_id) }}
                  title="删除此报告"
                  className="absolute top-2.5 right-2.5 w-6 h-6 rounded-md flex items-center justify-center text-slate-600 hover:text-red-400 hover:bg-red-950/50 opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-all text-sm leading-none">
                  ✕
                </button>
              </div>
            ))}
          </div>
          <div className="lg:col-span-3 card report-body" id="reportArea">
            {selected ? (
              <>
                <div className="flex flex-wrap gap-3 mb-5 no-print">
                  <button onClick={() => setSummaryOnly(value => !value)}
                    className="text-xs px-3.5 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-200">
                    {summaryOnly ? '查看完整报告' : '查看精简摘要'}
                  </button>
                  <a href={apiUrl(`/api/report/${selected.report_id}/download`)}
                    className="text-xs px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 transition-colors">下载 Markdown</a>
                  <a href={apiUrl(`/api/report/${selected.report_id}/pdf?brief=${summaryOnly}`)}
                    className="text-xs px-3.5 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors">下载 {summaryOnly ? '摘要' : '完整'} PDF</a>
                </div>
                <div className="report-body text-sm text-slate-300 leading-7"
                  dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(marked.parse(summaryOnly ? _summary(selected) : _md(selected))) }} />
              </>
            ) : (
              <div className="text-sm text-slate-500 h-40 flex flex-col items-center justify-center gap-3">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="w-9 h-9 opacity-50">
                  <path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6" />
                </svg>
                选择左侧报告查看
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function _summary(report) {
  if (report.brief_markdown) return report.brief_markdown
  const indicators = (report.key_indicators || []).slice(0, 5).map(item => `- ${item}`).join('\n')
  const actions = (report.recommendations || []).slice(0, 3).map(item => `- ${item}`).join('\n')
  return `# 产业链分析精简摘要\n\n**问题：** ${report.question || '—'}\n\n${report.executive_summary || report.summary || '暂无摘要'}\n\n## 核心指标\n${indicators || '暂无量化指标'}\n\n## 建议\n${actions || '详见完整报告的分主体建议'}\n\n> 仅供研究参考。相关性不是因果关系，演示评分不是违约概率。`
}

// 前端直接渲染 Markdown（与后端生成的 backend/reports/{id}.md 同源同构）
function _md(report) {
  if (report.markdown) return report.markdown
  // 安全格式化：缺失字段给定性描述而非 undefined
  const num = v => (typeof v === 'number' ? v.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) : null)
  const pct = v => (typeof v === 'number' ? v.toFixed(2) : null)
  // 冲击方向定性描述（无亿元数据时用）
  const degree = p => {
    if (typeof p !== 'number') return '待测算'
    const a = Math.abs(p)
    if (a >= 10) return '重度冲击'
    if (a >= 5) return '显著冲击'
    if (a >= 2) return '中度冲击'
    return '轻度冲击'
  }
  const rows = (report.affected_industries || []).map(r => {
    const yi = num(r.delta_output_yi)
    const p = pct(r.impact_pct)
    return `| ${r.industry} | ${p !== null ? p + '%' : '—'} | ${yi !== null ? yi : degree(r.impact_pct)} | ${r.risk_score ?? '—'} |`
  }).join('\n')
  const scores = (report.industry_scores || []).map(s => `- **${s.industry}**：${s.risk_score ?? '—'}（${s.risk_level ?? '—'}）`).join('\n')
  const steps = (report.transmission_path || []).map((t, i) => `${i + 1}. ${t}`).join('\n')
  const stages = (report.impact || {}).transmission_stages || {}
  const stagesMd = stages.stages?.length ? '\n\n' + stages.stages.map(s =>
    `**${s.name}**（${s.window}，压力 ${s.pressure}/100）—— ${s.mechanism}（命中：${s.hit_industries.join('、')}）`
  ).join('\n\n') + (stages.cross_case_rules ? '\n\n> 跨案例规律：' + stages.cross_case_rules.join('；') : '') : ''
  const basis = (report.data_basis || []).map(d => `- ${d}`).join('\n')
  const cases = (report.similar_cases || []).map(c => `- **${c.title}**：${c.peak_impact ?? '详见历史案例库'}`).join('\n')
  const kpis = (report.key_indicators || []).map(k => `- ${k}`).join('\n')
  return `# 中国房地产产业链波动分析报告

> 分析问题：**${report.question}**  
> ${report.risk_score != null ? `综合风险评分：**${report.risk_score} / 100（${report.risk_level || '未分级'}）**` : `分析状态：**${report.analysis_status_label || '定性分析'}，未计算风险评分**`}  
> 生成时间：${report.created_at}

## 1. Executive Summary
${report.summary}

## 2. Risk Assessment
${scores || (report.risk_score != null ? '- 综合风险：' + report.risk_score + '（' + (report.risk_level || '未分级') + '）' : '- 未进行量化风险评分')}

## 3. Transmission Mechanism（传导机制）
${steps}${stagesMd}

## 4. Affected Industries（影响矩阵）

| 行业 | 产出变动% | 变动(亿元) | 风险评分 |
|---|---|---|---|
${rows}

${cases ? '### 历史对比\n' + cases : ''}
## 5. Model Explanation（模型依据）
${report.model_basis}

### 数据依据
${basis}

## 6. Conclusion（建议关注指标）
${kpis}

---
*本报告由中国房地产产业链波动分析金融智能体自动生成，仅供研究演示。*`
}
