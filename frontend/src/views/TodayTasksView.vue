<template>
  <el-card shadow="never">
    <el-tabs v-model="tab">
      <!-- ============ 我的任务 ============ -->
      <el-tab-pane :label="`我的任务（${myTasks.length}）`" name="mine">
        <div style="display:flex;gap:12px;margin-bottom:12px">
          <el-select v-model="statusFilter" placeholder="状态" clearable style="width:140px" @change="loadMine">
            <el-option label="待处理" value="pending" />
            <el-option label="进行中" value="in_progress" />
            <el-option label="已完成" value="completed" />
          </el-select>
          <el-tag type="info" effect="plain">每日 09:00 系统自动生成当日任务，按"谁看诊谁负责"分配</el-tag>
        </div>
        <el-table :data="myTasks" stripe size="small">
          <el-table-column prop="task_type" label="类型" width="100"><template #default="{row}"><el-tag size="small" :type="typeTag(row.task_type)">{{ typeLabel(row.task_type) }}</el-tag></template></el-table-column>
          <el-table-column prop="priority" label="优先级" width="70"><template #default="{row}"><el-tag size="small" :type="prioTag(row.priority)" effect="dark">{{ row.priority }}</el-tag></template></el-table-column>
          <el-table-column prop="reason" label="原因" min-width="180" show-overflow-tooltip />
          <el-table-column label="建议渠道" width="100"><template #default="{row}">{{ channelLabel(row.suggested_channel) }}</template></el-table-column>
          <el-table-column label="预计价值" width="95"><template #default="{row}">¥{{ Number(row.expected_value || 0).toLocaleString() }}</template></el-table-column>
          <el-table-column label="截止" width="150"><template #default="{row}">{{ fmt(row.due_at) }}</template></el-table-column>
          <el-table-column prop="status" label="状态" width="90"><template #default="{row}"><el-tag size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{row}">
              <el-button v-if="row.status === 'pending'" size="small" @click="startTask(row)">开始</el-button>
              <el-button v-if="['pending','in_progress'].includes(row.status)" size="small" type="success" @click="openComplete(row)">完成并反馈</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============ 任务审核（老板） ============ -->
      <el-tab-pane :label="`待审核（${pendingReviews.length}）`" name="review">
        <el-alert type="info" :closable="false" show-icon title="员工完成任务后进入待审核；通过即归档，退回则任务回到「进行中」并顺延截止时间（自动催办）。" style="margin-bottom:12px" />
        <el-table :data="pendingReviews" stripe size="small">
          <el-table-column prop="task_type" label="类型" width="90"><template #default="{row}">{{ typeLabel(row.task_type) }}</template></el-table-column>
          <el-table-column prop="reason" label="任务原因" min-width="160" show-overflow-tooltip />
          <el-table-column prop="assigned_to_id" label="执行人" width="110" />
          <el-table-column prop="feedback_note" label="执行反馈" min-width="180" show-overflow-tooltip />
          <el-table-column label="反馈图片" width="120"><template #default="{row}">
            <el-image v-for="img in (row.feedback_images || []).slice(0, 2)" :key="img" :src="img" :preview-src-list="row.feedback_images" preview-teleported style="width:36px;height:36px;margin-right:4px;border-radius:4px" fit="cover" />
            <span v-if="!(row.feedback_images || []).length">-</span>
          </template></el-table-column>
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{row}">
              <el-button size="small" type="success" @click="review(row, true)">通过</el-button>
              <el-button size="small" type="danger" @click="review(row, false)">退回</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 完成反馈弹窗 -->
    <el-dialog v-model="completeDialog" title="完成任务并上传反馈" width="520px">
      <el-form label-width="90px">
        <el-form-item label="执行反馈"><el-input v-model="feedback.note" type="textarea" :rows="3" placeholder="客户反应、是否约到店、沟通结果…" /></el-form-item>
        <el-form-item label="反馈图片">
          <el-upload
            action="/api/v1/upload"
            :headers="uploadHeaders"
            :show-file-list="false"
            accept="image/*"
            :on-success="onUploadSuccess"
            :on-error="() => $message?.error('上传失败')"
          >
            <el-button size="small">上传图片</el-button>
          </el-upload>
          <div style="margin-top:8px">
            <el-image v-for="(img, i) in feedback.images" :key="img" :src="img" :preview-src-list="feedback.images" preview-teleported style="width:64px;height:64px;margin-right:6px;border-radius:6px" fit="cover" @click="removeImage(i)" />
          </div>
          <div style="color:#909399;font-size:12px;margin-top:4px">点击缩略图可移除；支持 jpg/png 等图片，单张 ≤8MB</div>
        </el-form-item>
        <el-form-item label="结果标记">
          <el-select v-model="feedback.outcome">
            <el-option label="已联系（有意向）" value="interested" />
            <el-option label="已创建预约" value="appointment_created" />
            <el-option label="已到店" value="visited" />
            <el-option label="已成交" value="converted" />
            <el-option label="无回应" value="no_answer" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="completeDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitComplete">提交（进入待审核）</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const tab = ref('mine')
const myTasks = ref([])
const pendingReviews = ref([])
const statusFilter = ref('')
const completeDialog = ref(false)
const submitting = ref(false)
const currentTask = ref(null)
const feedback = reactive({ note: '', images: [], outcome: 'appointment_created' })
const $message = ElMessage

const token = localStorage.getItem('clinicos_token')
// R-03：上传只使用用户 JWT
const uploadHeaders = computed(() => (token ? { Authorization: `Bearer ${token}` } : {}))

const fmt = (s) => (s ? new Date(s).toLocaleString('zh-CN') : '-')
const typeLabel = (t) => ({ recovery: '客户唤醒', retention: '复诊留存', growth: '营销增长', appointment: '预约', followup: '回访', manager_review: '老板复盘', doctor_action: '医生动作' }[t] || t)
const typeTag = (t) => ({ recovery: 'danger', retention: 'warning', growth: 'success' }[t] || 'info')
const statusLabel = (s) => ({ pending: '待处理', in_progress: '进行中', completed: '已完成', cancelled: '已取消', failed: '失败' }[s] || s)
const statusTag = (s) => ({ pending: 'info', in_progress: 'primary', completed: 'success', cancelled: 'danger', failed: 'danger' }[s] || 'info')
const prioTag = (p) => ({ S: 'danger', A: 'warning', B: 'primary', C: 'info' }[p] || 'info')
const channelLabel = (ch) => ({ phone: '电话', sms: '短信', wechat: '微信', enterprise_wechat: '企微', official_account: '公众号', manual: '人工' }[ch] || ch || '-')

async function loadMine() {
  const params = { limit: 200 }
  if (statusFilter.value) params.status = statusFilter.value
  myTasks.value = (await api.get('/tasks', params)).data
}
async function loadReviews() {
  pendingReviews.value = (await api.get('/tasks', { limit: 100, status: 'completed', review_status: 'pending' })).data
}
async function startTask(row) {
  await api.patch(`/tasks/${row.task_id}`, { status: 'in_progress' })
  ElMessage.success('已开始')
  loadMine()
}
function openComplete(row) {
  currentTask.value = row
  feedback.note = ''
  feedback.images = []
  feedback.outcome = 'appointment_created'
  completeDialog.value = true
}
function onUploadSuccess(resp) {
  if (resp.data?.url) {
    feedback.images.push(resp.data.url)
    ElMessage.success('图片已上传')
  }
}
function removeImage(i) {
  feedback.images.splice(i, 1)
}
async function submitComplete() {
  submitting.value = true
  try {
    await api.patch(`/tasks/${currentTask.value.task_id}`, {
      status: 'completed',
      feedback_note: feedback.note || undefined,
      feedback_images: feedback.images.length ? feedback.images : undefined,
      result: { outcome: feedback.outcome },
    })
    ElMessage.success('已提交，等待老板审核')
    completeDialog.value = false
    loadMine()
    loadReviews()
  } finally {
    submitting.value = false
  }
}
async function review(row, approved) {
  await api.patch(`/tasks/${row.task_id}/review`, {
    approved,
    note: approved ? '确认完成' : '执行反馈不完整，退回重做',
  })
  ElMessage.success(approved ? '已通过归档' : '已退回并催办')
  loadReviews()
}
onMounted(() => { loadMine(); loadReviews() })
</script>