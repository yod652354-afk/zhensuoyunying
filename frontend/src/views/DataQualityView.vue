<template>
  <div>
    <el-card shadow="never">
      <template #header><b>数据质量评分（完整性 / 一致性 / 时效性 / 授权）</b></template>
      <el-row :gutter="24" v-if="report.total_score !== undefined">
        <el-col :span="8">
          <div class="score-big">{{ report.total_score }}</div>
          <div class="score-label">{{ report.conclusion }}</div>
          <el-progress :percentage="report.total_score" :stroke-width="14" :show-text="false" :color="report.total_score >= 80 ? '#67c23a' : report.total_score >= 60 ? '#e6a23c' : '#f56c6c'" />
        </el-col>
        <el-col :span="16">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="患者总数">{{ report.patients_count }}</el-descriptions-item>
            <el-descriptions-item label="完整性">{{ report.completeness.score }}</el-descriptions-item>
            <el-descriptions-item label="一致性">{{ report.consistency.score }}</el-descriptions-item>
            <el-descriptions-item label="时效性">{{ report.timeliness.score }}</el-descriptions-item>
            <el-descriptions-item label="授权率">{{ report.authorization.consent_granted_rate }}%</el-descriptions-item>
            <el-descriptions-item label="DNC 人数">{{ report.authorization.dnc_count }}</el-descriptions-item>
          </el-descriptions>
        </el-col>
      </el-row>
      <el-table v-if="report.completeness?.details" :data="report.completeness.details" size="small" style="margin-top:16px" border>
        <el-table-column prop="field" label="关键字段" />
        <el-table-column prop="missing_rate" label="缺失率 %" />
      </el-table>
    </el-card>

    <el-card shadow="never" style="margin-top:16px">
      <template #header><b>CSV 导入（患者 / 到店 / 订单）</b></template>
      <el-space>
        <el-radio-group v-model="importType">
          <el-radio-button label="patients">患者</el-radio-button>
          <el-radio-button label="visits">到店</el-radio-button>
          <el-radio-button label="orders">订单</el-radio-button>
        </el-radio-group>
        <input ref="fileInput" type="file" accept=".csv" style="display:none" @change="doImport" />
        <el-button type="primary" @click="fileInput.click()">选择 CSV 并导入</el-button>
        <el-button @click="downloadTemplate">下载模板</el-button>
      </el-space>
      <el-alert type="success" :closable="false" v-if="lastResult" :title="`已导入 ${lastResult.imported} 条`" style="margin-top:12px" :description="(lastResult.errors || []).join('；') || '无错误'" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const report = ref({})
const importType = ref('patients')
const fileInput = ref(null)
const lastResult = ref(null)

const TEMPLATES = {
  patients: 'name,mobile,gender,first_visit_date,last_visit_date,total_visits,total_revenue,contact_status,consent_status,dnc\n张三,13800000001,male,2025-01-01T10:00:00+08:00,2026-01-01T10:00:00+08:00,5,1800,valid,granted,0',
  visits: 'patient_id,visit_at,doctor_id,service_category,visit_type,first_visit_flag\npat_xxx,2026-01-01T10:00:00+08:00,doc_xxx,针灸,followup,0',
  orders: 'patient_id,paid_at,final_amount,original_amount,discount_amount,service_id\npat_xxx,2026-01-01T10:00:00+08:00,860,1000,140,svc_xxx',
}

onMounted(async () => {
  report.value = (await api.get('/analytics/quality')).data
})

function downloadTemplate() {
  const blob = new Blob(['\ufeff' + TEMPLATES[importType.value]], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `clinicos_${importType.value}_template.csv`
  a.click()
}

async function doImport(e) {
  const file = e.target.files[0]
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  const url = `/import/${importType.value}`
  // R-03：导入只使用用户 JWT（未登录由路由守卫拦截）
  const token = localStorage.getItem('clinicos_token')
  const raw = await fetch(url, { method: 'POST', body: form, headers: token ? { Authorization: `Bearer ${token}` } : {} })
  const json = await raw.json()
  lastResult.value = json.data
  ElMessage.success(`导入完成：${json.data.imported} 条`)
  report.value = (await api.get('/analytics/quality')).data
  e.target.value = ''
}
</script>

<style scoped>
.score-big { font-size: 48px; font-weight: 700; color: #409eff; }
.score-label { color: #909399; margin: 4px 0 12px; }
</style>