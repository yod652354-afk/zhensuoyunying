<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <div class="brand">
        <el-icon :size="30" color="#409eff"><DataLine /></el-icon>
        <h2>RevOS 大健康经营智能平台</h2>
        <p>诊所 SaaS 数据底座 · 三种钱经营模型 · 人工审核的 AI 执行引擎 · 增量归因与学习</p>
      </div>
      <el-form @submit.prevent="doLogin">
        <el-form-item>
          <el-input v-model="username" placeholder="用户名" size="large" :prefix-icon="User" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="password" type="password" placeholder="密码" size="large" show-password :prefix-icon="Lock" @keyup.enter="doLogin" />
        </el-form-item>
        <el-button type="primary" size="large" style="width:100%" :loading="loading" @click="doLogin">登 录</el-button>
      </el-form>
      <el-alert type="info" :closable="false" style="margin-top:14px" title="演示账号：boss / boss123（老板端）、staff / staff123（员工端）" />
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { auth } from '../api/client'

const router = useRouter()
const username = ref('boss')
const password = ref('boss123')
const loading = ref(false)

async function doLogin() {
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    ElMessage.success('登录成功')
    router.push('/dashboard')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap { height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #001529 0%, #1f3b57 100%); }
.login-card { width: 380px; padding: 10px 16px; }
.brand { text-align: center; margin-bottom: 20px; }
.brand h2 { margin: 8px 0 4px; }
.brand p { color: #909399; font-size: 13px; margin: 0; }
</style>