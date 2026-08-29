<template>
  <el-card shadow="never">
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <b>患者档案（Recovery/Retention/Growth 共同客户主体）</b>
        <el-input v-model="q" placeholder="按姓名搜索" clearable style="width:240px" @input="load(1)" />
      </div>
    </template>
    <el-table :data="rows" stripe size="small">
      <el-table-column prop="name" label="姓名" width="100" />
      <el-table-column prop="mobile" label="手机号" width="130" />
      <el-table-column prop="customer_status" label="状态" width="90"><template #default="{row}"><el-tag size="small" :type="statusTag(row.customer_status)">{{ statusLabel(row.customer_status) }}</el-tag></template></el-table-column>
      <el-table-column prop="customer_stage" label="阶段" width="100" />
      <el-table-column prop="total_visits" label="累计到店" width="90" />
      <el-table-column label="累计收入" width="110"><template #default="{row}">¥{{ Number(row.total_revenue).toLocaleString() }}</template></el-table-column>
      <el-table-column label="最近到店" width="170"><template #default="{row}">{{ fmtDate(row.last_visit_date) }}</template></el-table-column>
      <el-table-column prop="primary_doctor_id" label="主诊医生" min-width="110" />
      <el-table-column label="合规" width="130"><template #default="{row}">
        <el-tag v-if="row.dnc" size="small" type="danger">DNC</el-tag>
        <el-tag v-if="row.complaint_flag" size="small" type="warning">投诉</el-tag>
        <el-tag v-if="row.consent_status === 'granted'" size="small" type="success">已授权</el-tag>
      </template></el-table-column>
    </el-table>
    <el-pagination style="margin-top:12px" layout="total, prev, pager, next" :total="total" :page-size="limit" :current-page="page" @current-change="load" />
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api/client'

const rows = ref([])
const total = ref(0)
const page = ref(1)
const limit = 20
const q = ref('')

const fmtDate = (s) => (s ? new Date(s).toLocaleDateString('zh-CN') : '-')
const statusLabel = (s) => ({ active: '活跃', sleeping: '沉睡', lost: '流失', new: '新客', blocked: '免打扰' }[s] || s)
const statusTag = (s) => ({ active: 'success', sleeping: 'warning', lost: 'danger', new: 'info', blocked: 'danger' }[s] || 'info')

async function load(p) {
  page.value = p || 1
  const params = { limit, page: undefined }
  if (q.value) params.name = q.value
  const resp = await api.get('/patients', { limit, name: q.value || undefined })
  rows.value = resp.data
  total.value = resp.meta?.total ?? rows.value.length
}
onMounted(() => load(1))
</script>