import axios from 'axios'

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')
export const apiUrl = path => `${API_BASE}${path}`
export const api = axios.create({ baseURL: API_BASE })

export const chat = (question) => api.post('/api/chat', { question }).then(r => r.data)
export const uploadFile = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/api/upload', fd).then(r => r.data)
}
export const getDashboard = () => api.get('/api/dashboard').then(r => r.data)
export const listReports = () => api.get('/api/reports').then(r => r.data)
export const getReport = (rid) => api.get(`/api/report/${rid}`).then(r => r.data)
export const deleteReport = (rid) => api.delete(`/api/report/${rid}`).then(r => r.data)
export const deleteAllReports = () => api.delete('/api/reports').then(r => r.data)
export const kbSearch = (q) => api.get('/api/kb/search', { params: { q } }).then(r => r.data)
export const getHealth = () => api.get('/api/health').then(r => r.data)
export const getAgentMode = () => api.get('/api/agent/mode').then(r => r.data)
export const setAgentMode = (mode) => api.post('/api/agent/mode', { mode }).then(r => r.data)
export const getV2Overview = () => api.get('/api/v2/overview').then(r => r.data)
export const getV2Cases = () => api.get('/api/v2/cases').then(r => r.data)
export const getV2Strategies = (stakeholder) => api.get('/api/v2/strategies', { params: stakeholder ? { stakeholder } : {} }).then(r => r.data)
export const runSimulation = (payload) => api.post('/api/v2/simulate', payload).then(r => r.data)

export const riskColor = (level) => ({
  '低': '#22c55e', '关注': '#eab308', '中': '#f97316', '高': '#ef4444', '极高': '#b91c1c', '-': '#64748b',
}[level] || '#64748b')
