<template>
  <div>
    <el-tabs v-model="tab">
      <el-tab-pane label="授权与免打扰 · 事件流 · 投递日志" name="overview">
        <el-row :gutter="16">
          <el-col :span="8">
            <el-card shadow="never">
              <template #header><b>授权与免打扰（授权 + 免打扰名单）</b></template>
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="已授权客户">{{ stats.granted }}</el-descriptions-item>
                <el-descriptions-item label="DNC（免打扰）">{{ stats.dnc }}</el-descriptions-item>
                <el-descriptions-item label="历史投诉">{{ stats.complaint }}</el-descriptions-item>
                <el-descriptions-item label="无效联系方式">{{ stats.invalid }}</el-descriptions-item>
              </el-descriptions>
              <el-alert type="warning" :closable="false" style="margin-top:12px" title="DNC/投诉/无效号码不会进入 Recovery 营销队列（已自动排除）。" />
            </el-card>
          </el-col>
          <el-col :span="8">
            <el-card shadow="never">
              <template #header>
                <div style="display:flex;justify-content:space-between">
                  <b>事件流（最近 30 条）</b>
                  <el-button size="small" @click="replay">补偿重放</el-button>
                </div>
              </template>
              <el-table :data="events" size="small" max-height="300">
                <el-table-column prop="event_type" label="事件" width="200" />
                <el-table-column prop="trace_id" label="Trace ID" min-width="140" />
                <el-table-column label="时间" width="150"><template #default="{row}">{{ fmt(row.occurred_at) }}</template></el-table-column>
              </el-table>
            </el-card>
          </el-col>
          <el-col :span="8">
            <el-card shadow="never">
              <template #header><b>Webhook 投递日志</b></template>
              <el-table :data="deliveries" size="small" max-height="300">
                <el-table-column prop="event_type" label="事件" width="190" />
                <el-table-column prop="status" label="状态" width="80"><template #default="{row}"><el-tag size="small" :type="row.status === 'success' ? 'success' : 'danger'">{{ row.status }}</el-tag></template></el-table-column>
                <el-table-column prop="attempt" label="次数" width="60" />
                <el-table-column prop="error" label="错误" min-width="120" show-overflow-tooltip />
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="营销内容审批" name="content">
        <el-card shadow="never">
          <template #header>
            <div style="display:flex;gap:12px;align-items:center;justify-content:space-between">
              <b>内容合规：生成 → 风险扫描 → 人工审批 → 发布留痕</b>
              <el-button type="primary" size="small" @click="submitDialog = true">提交内容审批</el-button>
            </div>
          </template>
          <el-table :data="reviews" stripe size="small">
            <el-table-column prop="content_text" label="内容" min-width="220" show-overflow-tooltip />
            <el-table-column prop="channel" label="渠道" width="90" />
            <el-table-column label="风险分" width="80"><template #default="{row}">
              <el-tag size="small" :type="row.risk_score >= 5 ? 'danger' : row.risk_score > 0 ? 'warning' : 'success'">{{ row.risk_score }}</el-tag>
            </template></el-table-column>
            <el-table-column label="命中规则" min-width="180"><template #default="{row}">{{ (row.risk_flags || []).map((f) => f.rule).join('；') || '无' }}</template></el-table-column>
            <el-table-column prop="status" label="状态" width="90"><template #default="{row}">
              <el-tag size="small" :type="{ pending: 'warning', approved: 'success', rejected: 'danger' }[row.status]">{{ { pending: '待审', approved: '已通过', rejected: '已驳回' }[row.status] }}</el-tag>
            </template></el-table-column>
            <el-table-column prop="review_note" label="审批意见" min-width="120" />
            <el-table-column label="操作" width="170" fixed="right">
              <template #default="{row}">
                <template v-if="row.status === 'pending'">
                  <el-button size="small" type="success" @click="approve(row, true)">通过</el-button>
                  <el-button size="small" type="danger" @click="approve(row, false)">驳回</el-button>
                </template>
                <span v-else>-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="submitDialog" title="提交内容审批（自动风险扫描）" width="520px">
      <el-form label-width="80px">
        <el-form-item label="渠道"><el-select v-model="submitForm.channel"><el-option label="企微" value="enterprise_wechat" /><el-option label="微信" value="wechat" /><el-option label="短信" value="sms" /><el-option label="电话" value="phone" /></el-select></el-form-item>
        <el-form-item label="内容"><el-input v-model="submitForm.content" type="textarea" :rows="5" /></el-form-item>
      </el-form>
      <el-alert v-if="scanResult" :type="scanResult.safe ? 'success' : 'warning'" :closable="false" style="margin-bottom:10px">
        <div>风险分：{{ scanResult.risk_score }}</div>
        <div v-if="scanResult.flags.length">命中：{{ scanResult.flags.map((f) => `${f.rule}(${f.matched})`).join('、') }}</div>
      </el-alert>
      <template #footer>
        <el-button @click="submitDialog = false">取消</el-button>
        <el-button type="primary" @click="doScan">扫描</el-button>
        <el-button type="success" @click="submitReview">提交审批</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const tab = ref('overview')
const stats = ref({ granted: 0, dnc: 0, complaint: 0, invalid: 0 })
const events = ref([])
const deliveries = ref([])
const reviews = ref([])
const submitDialog = ref(false)
const scanResult = ref(null)
const submitForm = reactive({ channel: 'enterprise_wechat', content: '' })
const fmt = (s) => (s ? new Date(s).toLocaleString('zh-CN') : '-')

async function loadOverview() {
  const [patients, evts, dels] = await Promise.all([
    api.get('/patients', { limit: 500 }),
    api.get('/events', { limit: 30 }),
    api.get('/webhooks/deliveries', { limit: 30 }),
  ])
  const rows = patients.data
  stats.value = {
    granted: rows.filter((p) => p.consent_status === 'granted').length,
    dnc: rows.filter((p) => p.dnc).length,
    complaint: rows.filter((p) => p.complaint_flag).length,
    invalid: rows.filter((p) => p.contact_status === 'invalid').length,
  }
  events.value = evts.data
  deliveries.value = dels.data
}
async function loadReviews() {
  reviews.value = (await api.get('/compliance/reviews')).data
}
async function replay() {
  const r = await api.get('/events/replay', { limit: 20 })
  ElMessage.success(`已重放 ${r.data.replayed} 条事件`)
}
async function doScan() {
  scanResult.value = (await api.post('/compliance/scan', { content: submitForm.content, channel: submitForm.channel })).data
}
async function submitReview() {
  await api.post('/compliance/reviews', { content: submitForm.content, channel: submitForm.channel })
  ElMessage.success('已提交审批（留痕）')
  submitDialog.value = false
  loadReviews()
}
async function approve(row, ok) {
  await api.post(`/compliance/reviews/${row.content_review_id}/approve`, { approved: ok, note: ok ? '合规，可发' : '命中风险词，驳回修改' })
  ElMessage.success(ok ? '已通过' : '已驳回')
  loadReviews()
}
onMounted(() => { loadOverview(); loadReviews() })
</script>