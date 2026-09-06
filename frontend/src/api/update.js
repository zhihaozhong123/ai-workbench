import api from './client'

/** 检查远端是否有新版本（返回当前版本/最新版本/更新说明/下载地址） */
export const checkUpdate = () => api.get('/update/check')
