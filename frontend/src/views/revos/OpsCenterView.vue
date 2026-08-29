<template>
  <div>
    <el-alert type="info" :closable="false" show-icon
              title="自动运营运行中心（R-10）：每租户同步/状态计算/机会/待审核/执行/失败与死信。任务由持久 Job 队列执行（租约/重试/死信/人工重放），重启不丢失。" style="margin-bottom:16px" />

    <el-card shadow="never">
      <template #header>
        <b>Job 队列</b>
        <el-button size="small" type="primary" style="margin-left:12px" @click="enqueueDaily">触发每日运营链</el-button>
        <el-button size="small" @click="load">刷新</el-button>
      </template>
      <el-table :data="jobs" size="small" stripe>
        <el-table-column prop="job_id" label="Job" width="180" />
        <el-table-column prop="job_type" label="类型" width="150" />
        <el-table-column label="状态" width="110">
          <template #default="{row}"><el-tag size="small" :type="statusTag(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="attempt" label="重试" width="70">
          <template #default="{row}">{{ row.attempt }}/{{ row.max_attempts }}</template>
        </el-table-column>
        <el-table-column prop="last_error" label="错误" min-width="200" show-overflow-tooltip />
        <el-table-column prop="requeued_by" label="重放人" width="90" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{row}">
            <el-button v-if="row.status === 'dead' || row.status === 'failed'" size="small" type="warning" link @click="requeue(row)">人工重放</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" style="margin-top:16px">
      <template #header><b>Outbox（待发布事件）</b></template>
      <el-button size="small" @click="pollOutbox">手动触发发布</el-button>
      <el-text type="info" size="small" style="margin-left:8px">后台 worker 每 10 秒自动轮询，事务提交后最终发布到事件流 + Webhook。</el-text>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../../api/client'

const jobs = ref([])
const statusTag = (s) => ({ pending: 'info', leased: 'warning', done: 'success', failed: 'danger', dead: 'danger' }[s] || 'info')

async function load() {
  const r = await api.get('/jobs?limit=50')
  jobs.value = r.data || []
}

async function enqueueDaily() {
  const r = await api.post('/jobs', { job_type: 'daily_ops' })
  ElMessage.success(`已入队: ${r.data.job_id}`)
  await load()
}

async function requeue(row) {
  await api.post(`/jobs/${row.job_id}/requeue`)
  ElMessage.success('已重新入队（保留审计）')
  await load()
}

async function pollOutbox() {
  const r = await api.post('/outbox/poll')
  ElMessage.success(`已发布 ${r.data.published} 条`)
}

onMounted(load)
</script>
