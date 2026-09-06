import api from './client'

// ---- 技能源管理 ----
export const fetchSources = () => api.get('/skills/sources')
export const addSource = (input, label = '') => api.post('/skills/sources', { input, label })
export const patchSource = (id, data) => api.patch(`/skills/sources/${id}`, data)
export const removeSource = (id) => api.delete(`/skills/sources/${id}`)
export const syncAll = () => api.post('/skills/sync')

// ---- 技能市场 ----
export const fetchMarket = (params = {}) => api.get('/skills/market', { params })
export const fetchCategories = () => api.get('/skills/categories')
export const fetchInstalled = () => api.get('/skills/installed')
export const installSkill = (slug) => api.post(`/skills/${slug}/install`)
export const uninstallSkill = (slug) => api.post(`/skills/${slug}/uninstall`)
