<template>
  <div v-if="isLoginPage" class="login-shell">
    <router-view />
  </div>
  <el-container v-else class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">
        <el-icon :size="22"><DataLine /></el-icon>
        <span>RevOS 大健康经营智能平台</span>
      </div>
      <el-menu :default-active="$route.path" router background-color="#001529" text-color="#a6adb4" active-text-color="#ffffff">
        <el-menu-item v-for="r in menuRoutes" :key="r.path" :index="r.path">
          <el-icon><component :is="r.meta.icon" /></el-icon>
          <span>{{ r.meta.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="page-title">{{ $route.meta.title || '' }}</div>
        <div class="header-right">
          <el-tag v-if="user" size="small" effect="dark" :type="user.role === 'boss' ? 'warning' : 'primary'">
            {{ user.name }} · {{ roleLabel(user.role) }}
          </el-tag>
          <el-button v-if="user" size="small" text @click="logout">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from './stores/app'
import { auth } from './api/client'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const menuRoutes = computed(() => store.menuRoutes)
const user = computed(() => auth.currentUser())
const isLoginPage = computed(() => route.path === '/login')
const roleLabel = (r) => ({ boss: '老板端', staff: '员工端', admin: '管理员' }[r] || r)

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<style>
body { margin: 0; font-family: 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #f0f2f5; }
.layout { height: 100vh; }
.aside { background: #001529; }
.aside .logo { display: flex; align-items: center; gap: 8px; color: #fff; font-size: 18px; font-weight: 700; padding: 18px 20px; }
.aside .el-menu { border-right: none; }
.header { background: #fff; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #e8e8e8; }
.page-title { font-size: 17px; font-weight: 600; }
.main { overflow-y: auto; }
</style>