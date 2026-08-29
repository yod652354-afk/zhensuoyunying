<template>
  <div>
    <el-alert type="warning" :closable="false" show-icon
              title="策略注册中心：版本化 detector/scoring/decision/workflow/psychology/prompt/channel/timing。状态：draft → offline_validated → shadow → experiment → limited_release → active → retired/rolled_back。合规/决策/渠道策略进入生产必须人工批准；新策略先影子运行；样本不足只标记方向性。" style="margin-bottom:16px" />

    <el-card shadow="never">
      <el-form inline>
        <el-form-item label="类别">
          <el-select v-model="filters.category" clearable placeholder="全部" style="width:180px" @change="load">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width:170px" @change="load">
            <el-option v-for="s in statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item><el-button type="primary" @click="load">刷新</el-button></el-form-item>
      </el-form>

      <el-table :data="rows" size="small" stripe>
        <el-table-column prop="category" label="类别" width="170" />
        <el-table-column prop="code" label="策略代码" width="170" />
        <el-table-column label="版本" width="70"><template #default="{row}">v{{ row.version }}</template></el-table-column>
        <el-table-column label="状态" width="140">
          <template #default="{row}"><el-tag size="small" :type="statusTag(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="change_reason" label="变更原因" min-width="160" show-overflow-tooltip />
        <el-table-column prop="owner" label="负责人" width="110" />
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{row}">
            <el-button size="small" type="primary" link @click="transition(row, 'offline_validated')">离线验证</el-button>
            <el-button size="small" type="warning" link @click="transition(row, 'shadow')">影子运行</el-button>
            <el-button size="small" type="warning" link @click="transition(row, 'experiment')">实验</el-button>
            <el-button size="small" type="success" link @click="transition(row, 'limited_release')">小流量</el-button>
            <el-button size="small" type="success" link @click="transition(row, 'active')">发布</el-button>
            <el-button size="small" type="danger" link @click="rollback(row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" style="margin-top:16px">
      <template #header><b>注册新策略版本</b></template>
      <el-form inline>
        <el-form-item label="类别">
          <el-select v-model="newForm.category" style="width:180px">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="代码"><el-input v-model="newForm.code" style="width:170px" placeholder="如 dormant_score" /></el-form-item>
        <el-form-item label="变更原因"><el-input v-model="newForm.change_reason" style="width:220px" /></el-form-item>
        <el-form-item><el-button type="primary" @click="register">注册</el-button></el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../api/client'

const rows = ref([])
const filters = reactive({ category: null, status: null })
const newForm = reactive({ category: 'detector_rule', code: '', change_reason: '' })
const categories = ['detector_rule', 'scoring_formula', 'decision_policy', 'workflow_definition',
                    'content_strategy', 'prompt_template', 'message_template', 'timing_policy',
                    'channel_policy', 'prediction_model']
const statuses = ['draft', 'offline_validated', 'shadow', 'experiment', 'limited_release', 'active', 'retired', 'rolled_back']
const statusTag = (s) => ({ active: 'success', shadow: 'warning', experiment: 'warning', limited_release: 'primary', draft: 'info', retired: 'info', rolled_back: 'danger', offline_validated: 'primary' }[s] || 'info')

async function load() {
  const params = {}
  if (filters.category) params.category = filters.category
  if (filters.status) params.status = filters.status
  const r = await api.get('/strategy-versions', params)
  rows.value = r.data || []
}

async function transition(row, target) {
  const reason = await ElMessageBox.prompt('流转原因', '状态流转', { inputValue: target }).then(r => r.value).catch(() => null)
  if (reason === null) return
  await api.post(`/strategy-versions/${row.strategy_version_id}/transition`, { target, reason })
  ElMessage.success(`已流转到 ${target}`)
  await load()
}

async function rollback(row) {
  await ElMessageBox.confirm(`确认回滚策略 ${row.code} v${row.version}？`, '回滚')
  await api.post(`/strategy-versions/${row.strategy_version_id}/rollback`, { reason: '人工回滚' })
  ElMessage.success('已回滚')
  await load()
}

async function register() {
  if (!newForm.code) return ElMessage.warning('请输入策略代码')
  await api.post('/strategy-versions', {
    category: newForm.category, code: newForm.code,
    definition: { version_note: newForm.change_reason || 'v1' },
    change_reason: newForm.change_reason,
  })
  ElMessage.success('已注册新版本')
  newForm.code = ''
  await load()
}

onMounted(load)
</script>
