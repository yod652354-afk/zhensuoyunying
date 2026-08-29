import { createRouter, createWebHistory } from 'vue-router'
import { auth } from '../api/client'

const routes = [
  { path: '/login', component: () => import('../views/LoginView.vue'), meta: { title: '登录', public: true } },
  { path: '/', redirect: '/dashboard' },
  // RevOS 一级导航（三种钱驾驶舱 → 机会 → 执行 → 审核 → 客户 → 实验 → 数据 → 合规 → 配置）
  { path: '/revos/cockpit', component: () => import('../views/revos/CockpitView.vue'), meta: { title: '三种钱驾驶舱', icon: 'DataLine' } },
  { path: '/revos/opportunities', component: () => import('../views/revos/OpportunitiesView.vue'), meta: { title: '经营机会池', icon: 'Lightning' } },
  { path: '/revos/opportunities/:opportunity_id', component: () => import('../views/revos/OpportunityDetailView.vue'), meta: { title: '机会详情' } },
  { path: '/revos/execution', component: () => import('../views/revos/StaffExecutionView.vue'), meta: { title: '今日执行', icon: 'Checked' } },
  { path: '/revos/review', component: () => import('../views/revos/ReviewCenterView.vue'), meta: { title: '内容审核中心', icon: 'Stamp' } },
  { path: '/revos/customers', component: () => import('../views/revos/CustomersView.vue'), meta: { title: '客户经营档案', icon: 'User' } },
  { path: '/revos/experiments', component: () => import('../views/revos/ExperimentsRevView.vue'), meta: { title: '实验与增量归因', icon: 'DataAnalysis' } },
  { path: '/revos/strategy', component: () => import('../views/revos/StrategyView.vue'), meta: { title: '策略注册中心', icon: 'SetUp' } },
  { path: '/revos/ops-center', component: () => import('../views/revos/OpsCenterView.vue'), meta: { title: '自动运营运行中心', icon: 'Monitor', roles: ['boss', 'admin'] } },
  { path: '/revos/attribution-queue', component: () => import('../views/revos/AttributionQueueView.vue'), meta: { title: '待人工归因', icon: 'QuestionFilled', roles: ['boss', 'admin'] } },
  { path: '/revos/connectors', component: () => import('../views/revos/ConnectorsView.vue'), meta: { title: '数据连接（Connector）', icon: 'Connection', roles: ['boss', 'admin'] } },
  // 兼容既有页面（保留原路由）
  { path: '/dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '经营驾驶舱（兼容）', icon: 'Odometer' } },
  { path: '/patients', component: () => import('../views/PatientsView.vue'), meta: { title: '患者档案', icon: 'User' } },
  { path: '/recovery', component: () => import('../views/RecoveryPoolView.vue'), meta: { title: '客户唤醒池（Recovery）', icon: 'RefreshLeft' } },
  { path: '/tasks', component: () => import('../views/TodayTasksView.vue'), meta: { title: '今日经营任务', icon: 'Checked' } },
  { path: '/retention', component: () => import('../views/RetentionView.vue'), meta: { title: '复诊留存漏斗（Retention）', icon: 'TrendCharts' } },
  { path: '/growth', component: () => import('../views/GrowthView.vue'), meta: { title: '营销增长计划（Growth）', icon: 'Promotion' } },
  { path: '/experiments', component: () => import('../views/ExperimentsView.vue'), meta: { title: '实验与增量归因（兼容）', icon: 'DataAnalysis' } },
  { path: '/reports', component: () => import('../views/ReportCenterView.vue'), meta: { title: '经营报表', icon: 'Document' } },
  { path: '/data-quality', component: () => import('../views/DataQualityView.vue'), meta: { title: '数据导入与质量', icon: 'Upload' } },
  { path: '/compliance', component: () => import('../views/ComplianceView.vue'), meta: { title: '合规审计', icon: 'Lock' } },
  { path: '/settings', component: () => import('../views/SettingsView.vue'), meta: { title: '系统设置', icon: 'Setting' } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const user = auth.currentUser()
  // R-03：未登录统一进入登录页（不发送 API Key）
  if (!to.meta.public && !user) {
    return '/login'
  }
  // R-10：路由按角色控制（不能只隐藏菜单）
  if (to.meta.roles && user && !to.meta.roles.includes(user.role)) {
    return '/revos/cockpit'
  }
  return true
})

export default router
export { routes }