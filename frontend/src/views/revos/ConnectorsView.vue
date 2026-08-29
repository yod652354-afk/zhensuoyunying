<template>
  <div>
    <el-alert type="info" :closable="false" show-icon
              title="数据连接（R-09）：诊所SaaS 自动接入。全量首导 / updated_since+cursor 增量 / Webhook 实时 / 丢失补偿 / 每日对账。密钥经环境变量注入，不存明文。" style="margin-bottom:16px" />

    <el-card shadow="never">
      <template #header><b>Connector 配置</b></template>
      <el-form inline>
        <el-form-item label="名称"><el-input v-model="form.name" style="width:150px" /></el-form-item>
        <el-form-item label="Base URL"><el-input v-model="form.base_url" style="width:260px" placeholder="http://saas.example.com" /></el-form-item>
        <el-form-item label="API Key 环境变量"><el-input v-model="form.api_key_ref" style="width:180px" placeholder="CLINIC_SaaS_API_KEY" /></el-form-item>
        <el-form-item><el-button type="primary" @click="create">创建</el-button></el-form-item>
      </el-form>
      <el-table :data="connectors" size="small" stripe>
        <el-table-column prop="connector_id" label="ID" width="170" />
        <el-table-column prop="name" label="名称" width="130" />
        <el-table-column prop="kind" label="类型" width="120" />
        <el-table-column prop="base_url" label="Base URL" min-width="180" />
        <el-table-column prop="api_key_ref" label="密钥引用" width="160" />
        <el-table-column label="启用" width="80">
          <template #default="{row}">{{ row.enabled ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{row}">
            <el-button size="small" type="primary" link @click="sync(row, 'full')">全量同步</el-button>
            <el-button size="small" type="warning" link @click="sync(row, 'incremental')">增量同步</el-button>
            <el-button size="small" link @click="runs(row)">运行记录</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="runRows.length" shadow="never" style="margin-top:16px">
      <template #header><b>同步运行记录</b></template>
      <el-table :data="runRows" size="small">
        <el-table-column prop="entity" label="实体" width="110" />
        <el-table-column prop="sync_mode" label="模式" width="110" />
        <el-table-column label="状态" width="100">
          <template #default="{row}"><el-tag size="small" :type="row.status === 'done' ? 'success' : 'danger'">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="pulled" label="拉取" width="70" />
        <el-table-column prop="inserted" label="写入" width="70" />
        <el-table-column prop="skipped" label="跳过" width="70" />
        <el-table-column prop="error" label="错误" min-width="200" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card shadow="never" style="margin-top:16px">
      <template #header><b>对账差异（每日患者/到店/订单/支付/退款）</b></template>
      <el-table :data="diffs" size="small">
        <el-table-column prop="diff_date" label="日期" width="110" />
        <el-table-column prop="entity" label="实体" width="110" />
        <el-table-column prop="field" label="字段" width="130" />
        <el-table-column prop="entity_id" label="ID" width="170" />
        <el-table-column prop="source_value" label="源值" min-width="120" show-overflow-tooltip />
        <el-table-column prop="revos_value" label="RevOS 值" min-width="120" show-overflow-tooltip />
      </el-table>
      <el-empty v-if="!diffs.length" description="暂无对账差异" :image-size="50" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../../api/client'

const connectors = ref([])
const runRows = ref([])
const diffs = ref([])
const form = reactive({ name: '', base_url: '', api_key_ref: '' })

async function load() {
  const r = await api.get('/connectors')
  connectors.value = r.data || []
  const d = await api.get('/reconciliation/diffs')
  diffs.value = d.data || []
}

async function create() {
  if (!form.name) return ElMessage.warning('请输入名称')
  await api.post('/connectors', { name: form.name, base_url: form.base_url || null, api_key_ref: form.api_key_ref || null })
  ElMessage.success('已创建（同步经持久 Job 队列执行）')
  form.name = ''
  await load()
}

async function sync(row, mode) {
  const r = await api.post(`/connectors/${row.connector_id}/sync?mode=${mode}`)
  ElMessage.success(`同步已入队: ${r.data.job_id}`)
}

async function runs(row) {
  const r = await api.get(`/connectors/${row.connector_id}/runs`)
  runRows.value = r.data || []
}

onMounted(load)
</script>
