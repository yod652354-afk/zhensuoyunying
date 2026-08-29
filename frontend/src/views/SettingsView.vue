<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b>Webhook 订阅（事件推送 · 签名 · 重试）</b>
          <el-button type="primary" @click="dialog = true">新建订阅</el-button>
        </div>
      </template>
      <el-table :data="subs" stripe size="small">
        <el-table-column prop="url" label="目标 URL" min-width="220" />
        <el-table-column prop="event_types" label="事件类型" min-width="140"><template #default="{row}">{{ row.event_types ? row.event_types.join(', ') : '全部' }}</template></el-table-column>
        <el-table-column prop="enabled" label="启用" width="80"><template #default="{row}"><el-switch :model-value="row.enabled" @change="(v) => toggle(row, v)" /></template></el-table-column>
        <el-table-column label="创建时间" width="170"><template #default="{row}">{{ fmt(row.created_at) }}</template></el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{row}">
            <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top:12px">
        <el-button @click="sendTest">发送测试事件</el-button>
        <el-alert type="info" :closable="false" style="margin-top:12px"
          title="投递模式为 log（开发默认）：事件仅记录日志不真实外发；切换到 .env 的 WEBHOOK_DELIVERY_MODE=http 后，将按 HMAC-SHA256 签名并投递，失败按指数退避重试。" />
      </div>
    </el-card>

    <el-card shadow="never" style="margin-top:16px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b>话术模板库（建议渠道 × 话术 × 版本）</b>
          <el-button type="primary" size="small" @click="tplDialog = true">新建模板</el-button>
        </div>
      </template>
      <el-table :data="templates" stripe size="small">
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="task_type" label="任务类型" width="100"><template #default="{row}">{{ typeLabel(row.task_type) }}</template></el-table-column>
        <el-table-column prop="channel" label="渠道" width="100" />
        <el-table-column prop="content" label="话术内容" min-width="260" show-overflow-tooltip />
        <el-table-column prop="version" label="版本" width="70" />
      </el-table>
    </el-card>

    <el-dialog v-model="tplDialog" title="新建话术模板" width="520px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="tplForm.name" /></el-form-item>
        <el-form-item label="任务类型"><el-select v-model="tplForm.task_type"><el-option label="Recovery" value="recovery" /><el-option label="Retention" value="retention" /><el-option label="Growth" value="growth" /></el-select></el-form-item>
        <el-form-item label="渠道"><el-select v-model="tplForm.channel"><el-option label="企微" value="enterprise_wechat" /><el-option label="微信" value="wechat" /><el-option label="短信" value="sms" /><el-option label="电话" value="phone" /></el-select></el-form-item>
        <el-form-item label="内容"><el-input v-model="tplForm.content" type="textarea" :rows="4" placeholder="支持变量：{患者姓名} {医生} {门店}" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tplDialog = false">取消</el-button>
        <el-button type="primary" @click="createTpl">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dialog" title="新建 Webhook 订阅" width="480px">
      <el-form label-width="90px">
        <el-form-item label="目标 URL"><el-input v-model="form.url" placeholder="https://clinicos.example.cn/webhooks/clinic-saas" /></el-form-item>
        <el-form-item label="事件类型"><el-input v-model="form.event_types" placeholder="留空=全部；逗号分隔，如 appointment.created,payment.completed" /></el-form-item>
        <el-form-item label="签名密钥"><el-input v-model="form.secret" placeholder="留空则用全局 WEBHOOK_SECRET" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="create">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const subs = ref([])
const dialog = ref(false)
const form = reactive({ url: '', event_types: '', secret: '' })
const templates = ref([])
const tplDialog = ref(false)
const tplForm = reactive({ name: '', task_type: 'recovery', channel: 'wechat', content: '' })
const typeLabel = (t) => ({ recovery: 'Recovery', retention: 'Retention', growth: 'Growth' }[t] || t)

async function loadTemplates() {
  templates.value = (await api.get('/message-templates')).data
}
async function createTpl() {
  await api.post('/message-templates', { ...tplForm })
  ElMessage.success('模板已创建')
  tplDialog.value = false
  loadTemplates()
}
const fmt = (s) => (s ? new Date(s).toLocaleString('zh-CN') : '-')

async function load() {
  subs.value = (await api.get('/webhook-subscriptions')).data
}
async function create() {
  const payload = { url: form.url, secret: form.secret || undefined }
  if (form.event_types.trim()) payload.event_types = form.event_types.split(',').map((s) => s.trim())
  await api.post('/webhook-subscriptions', payload)
  ElMessage.success('订阅已创建')
  dialog.value = false
  load()
}
async function toggle(row, v) {
  await api.patch(`/webhook-subscriptions/${row.subscription_id}`, { enabled: v })
  ElMessage.success(v ? '已启用' : '已停用')
}
async function remove(row) {
  await api.del(`/webhook-subscriptions/${row.subscription_id}`)
  ElMessage.success('已删除')
  load()
}
async function sendTest() {
  await api.post('/webhooks/test')
  ElMessage.success('测试事件已发送（投递到订阅，见投递日志）')
}
onMounted(() => { load(); loadTemplates() })
</script>