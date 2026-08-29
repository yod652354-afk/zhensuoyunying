import axios from 'axios'
import router from '../router'

// R-03：浏览器只使用用户 JWT，不持有服务端 API Key。
// API Key 仅供诊所SaaS Connector / Webhook 管理程序等可信服务端。
const client = axios.create({
  baseURL: '/api/v1',
  timeout: 20000,
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('clinicos_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // 未登录时由路由守卫拦截跳转登录页；不再发送 X-API-Key
  return config
})

client.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    if (error.response?.status === 401) {
      // 令牌过期/无效：清理会话并跳转登录
      localStorage.removeItem('clinicos_token')
      localStorage.removeItem('clinicos_user')
      if (router.currentRoute.value.path !== '/login') {
        router.push('/login')
      }
    }
    const detail = error.response?.data?.error || {}
    const msg = detail.message || error.message || '请求失败'
    console.error('[RevOS API]', msg)
    throw new Error(msg)
  }
)

export const api = {
  get: (url, params) => client.get(url, { params }),
  post: (url, data, extra = {}) => client.post(url, data, extra),
  patch: (url, data) => client.patch(url, data),
  del: (url) => client.delete(url),
}

export const auth = {
  async login(username, password) {
    const r = await client.post('/auth/login', { username, password })
    localStorage.setItem('clinicos_token', r.data.access_token)
    localStorage.setItem('clinicos_user', JSON.stringify(r.data.user))
    return r.data.user
  },
  logout() {
    localStorage.removeItem('clinicos_token')
    localStorage.removeItem('clinicos_user')
  },
  currentUser() {
    try { return JSON.parse(localStorage.getItem('clinicos_user') || 'null') } catch { return null }
  },
}