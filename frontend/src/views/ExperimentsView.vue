<template>
  <el-card shadow="never">
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <b>实验与增量归因中心（对照组 vs 实验组）</b>
        <el-button type="primary" @click="dialog = true">新建实验</el-button>
      </div>
    </template>
    <el-table :data="rows" stripe size="small">
      <el-table-column prop="name" label="实验" min-width="170" />
      <el-table-column prop="engine" label="引擎" width="90" />
      <el-table-column prop="status" label="状态" width="90"><template #default="{row}"><el-tag size="small" :type="row.status === 'running' ? 'success' : 'info'">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
      <el-table-column prop="hypothesis" label="假设" min-width="200" show-overflow-tooltip />
      <el-table-column prop="primary_metric" label="主指标" width="120" />
      <el-table-column label="对照组/实验组" width="130"><template #default="{row}">{{ row.control.n }} / {{ row.treatment.n }}</template></el-table-column>
      <el-table-column prop="incremental_lift_pp" label="增量Lift" width="100"><template #default="{row}">{{ row.incremental_lift_pp }} pp</template></el-table-column>
      <el-table-column label="增量收入" width="110"><template #default="{row}">¥{{ Number(row.incremental_revenue || 0).toLocaleString() }}</template></el-table-column>
      <el-table-column prop="roi" label="ROI" width="90"><template #default="{row}">{{ row.roi ?? '-' }}x</template></el-table-column>
      <el-table-column label="显著性" width="110" fixed="right"><template #default="{row}">
        <el-tag size="small" :type="sigTag(row.significance?.conclusion)">{{ sigLabel(row.significance?.conclusion) }}</el-tag>
      </template></el-table-column>
      <el-table-column label="p值" width="90" fixed="right"><template #default="{row}">{{ row.significance?.p_value ?? '-' }}</template></el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="新建实验" width="520px">
      <el-form label-width="100px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="引擎"><el-select v-model="form.engine"><el-option label="Recovery" value="recovery" /><el-option label="Retention" value="retention" /><el-option label="Growth" value="growth" /></el-select></el-form-item>
        <el-form-item label="假设"><el-input v-model="form.hypothesis" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="主指标"><el-input v-model="form.primary_metric" placeholder="如 visit_rate_28d" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="create">创建</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const rows = ref([])
const dialog = ref(false)
const form = reactive({ name: '', engine: 'recovery', hypothesis: '', primary_metric: 'visit_rate_28d' })
const statusLabel = (s) => ({ draft: '草稿', running: '进行中', completed: '已完成', cancelled: '已取消' }[s] || s)
const sigLabel = (s) => ({ significant: '显著', marginal: '边缘显著', not_significant: '不显著', directional: '方向性' }[s] || s || '-')
const sigTag = (s) => ({ significant: 'success', marginal: 'warning', not_significant: 'info', directional: 'primary' }[s] || 'info')

async function load() {
  rows.value = (await api.get('/analytics/experiments/summary')).data
}
async function create() {
  await api.post('/experiments', { ...form })
  ElMessage.success('实验已创建')
  dialog.value = false
  load()
}
onMounted(load)
</script>