<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b>客户唤醒池：沉睡/流失识别与优先级评分</b>
          <el-button type="primary" :loading="generating" @click="generateTasks">由池中前 50 人生成今日任务</el-button>
        </div>
      </template>
      <el-table :data="rows" stripe size="small">
        <el-table-column prop="priority" label="优先级" width="80"><template #default="{row}"><el-tag size="small" :type="prioTag(row.priority)" effect="dark">{{ row.priority }}</el-tag></template></el-table-column>
        <el-table-column prop="name" label="姓名" width="90" />
        <el-table-column prop="mobile" label="手机号" width="130" />
        <el-table-column prop="segment" label="分群" width="130"><template #default="{row}">{{ segmentLabel(row.segment) }}</template></el-table-column>
        <el-table-column label="距最近到店" width="100"><template #default="{row}">{{ row.days_since_last_visit }} 天</template></el-table-column>
        <el-table-column label="累计消费" width="110"><template #default="{row}">¥{{ Number(row.total_revenue).toLocaleString() }}</template></el-table-column>
        <el-table-column prop="package_remaining" label="套餐剩余" width="90" />
        <el-table-column prop="score" label="Score" width="80"><template #default="{row}"><el-progress :percentage="row.score" :stroke-width="12" :show-text="false" /><span style="font-size:12px">{{ row.score }}</span></template></el-table-column>
        <el-table-column label="原因" min-width="220"><template #default="{row}">{{ (row.reasons || []).join('；') }}</template></el-table-column>
        <el-table-column label="合规" width="90"><template #default="{row}"><el-tag v-if="row.dnc" size="small" type="danger">DNC</el-tag><span v-else>-</span></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const rows = ref([])
const generating = ref(false)
const prioTag = (p) => ({ S: 'danger', A: 'warning', B: 'primary', C: 'info' }[p] || 'info')
const segmentLabel = (s) => ({ first_visit_no_followup: '初诊未复诊', sleeping_30: '沉睡30天', sleeping_60: '沉睡60天', sleeping_90: '沉睡90天', lost_180: '流失180天+' }[s] || s)

async function load() {
  rows.value = (await api.get('/analytics/recovery-pool')).data
}
async function generateTasks() {
  generating.value = true
  try {
    const r = await api.post('/analytics/recovery-pool/tasks')
    const t = r.data.tasks[0]
    const hint = t ? `（示例：${t.patient_id.slice(0, 12)}… 渠道=${t.suggested_channel || '-'}，已挂话术模板）` : ''
    ElMessage.success(`已生成 ${r.data.created} 条 Recovery 任务 ${hint}`)
    await load()
  } finally {
    generating.value = false
  }
}
onMounted(load)
</script>