<template>
  <div>
    <el-alert type="info" :closable="false" show-icon
              title="员工端今日执行：内容为审核通过的固定版本（只读，不可编辑）；需确认发送后在企微实际发送并回填结果。发送前系统会再次校验 DNC/投诉/授权/频控。" style="margin-bottom:16px" />

    <el-card shadow="never">
      <el-table :data="rows" size="small" stripe>
        <el-table-column prop="task_id" label="任务ID" width="190" />
        <el-table-column prop="patient_id" label="客户" width="170" />
        <el-table-column label="状态" width="170">
          <template #default="{row}"><el-tag size="small" :type="statusTag(row.send_status)">{{ row.send_status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="失败原因" min-width="140">
          <template #default="{row}">
            <el-text v-if="row.failure_code" type="danger" size="small">{{ row.failure_code }}: {{ row.failure_message }}</el-text>
          </template>
        </el-table-column>
        <el-table-column label="外部消息ID" width="160">
          <template #default="{row}">{{ row.external_message_id || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="340" fixed="right">
          <template #default="{row}">
            <el-button size="small" type="primary" link @click="showContent(row)">查看内容</el-button>
            <el-button size="small" type="warning" link @click="prepare(row)">准备发送</el-button>
            <el-button size="small" type="success" link @click="confirmSent(row)">确认已发送</el-button>
            <el-button size="small" type="danger" link @click="markFailed(row)">不适合联系</el-button>
            <el-button size="small" link @click="recordResponse(row)">记录回复</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="contentVisible" title="审核通过的内容（只读）" width="560">
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="标题">{{ content.title }}</el-descriptions-item>
        <el-descriptions-item label="正文">{{ content.wecom_text }}</el-descriptions-item>
        <el-descriptions-item label="图片">
          <el-image v-if="content.image_url" :src="content.image_url" style="width:120px" />
        </el-descriptions-item>
        <el-descriptions-item label="小程序卡片">
          {{ content.mini_program_config?.card_title }}（{{ content.mini_program_config?.page_code }}）
        </el-descriptions-item>
        <el-descriptions-item label="内容哈希">{{ content.content_hash }}</el-descriptions-item>
      </el-descriptions>
      <el-text type="danger" size="small">员工不得编辑已批准正文；如需修改，须创建新版本并重新审核。</el-text>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../api/client'

const rows = ref([])
const contentVisible = ref(false)
const content = ref({})
const statusTag = (s) => ({ content_approved: 'primary', waiting_member_confirmation: 'warning', sent: 'success', delivered: 'success', failed: 'danger', unknown: 'info', responded: 'success', pending: 'info' }[s] || 'info')

async function load() {
  const r = await api.get('/send-tasks')
  rows.value = r.data || []
}

async function showContent(row) {
  const r = await api.get(`/content-drafts/${row.content_draft_id}`)
  content.value = r.data
  contentVisible.value = true
}

async function prepare(row) {
  const r = await api.post(`/send-tasks/${row.task_id}/prepare-wecom`)
  if (r.data.ok) {
    ElMessage.success(`已就绪，external_userid: ${r.data.external_userid}`)
  } else {
    ElMessage.error(`准备失败: ${r.data.code}`)
  }
  await load()
}

async function confirmSent(row) {
  const r = await api.post(`/send-tasks/${row.task_id}/confirm-sent`)
  ElMessage.success(`已确认：${r.data.send_status}`)
  await load()
}

async function markFailed(row) {
  const reason = await ElMessageBox.prompt('失败原因（如：客户无好友关系/已拒绝/号码无效）', '标记失败', { inputValue: 'staff_reported' }).then(r => r.value).catch(() => null)
  if (reason === null) return
  await api.post(`/send-tasks/${row.task_id}/mark-failed`, { failure_code: 'staff_reported', failure_message: reason })
  ElMessage.success('已标记')
  await load()
}

async function recordResponse(row) {
  const type = await ElMessageBox.prompt('回复结果（replied/interested/rejected/no_response）', '记录回复', { inputValue: 'replied' }).then(r => r.value).catch(() => null)
  if (!type) return
  await api.post(`/send-tasks/${row.task_id}/record-response`, { outcome_type: type })
  ElMessage.success('已记录')
  await load()
}

onMounted(load)
</script>
