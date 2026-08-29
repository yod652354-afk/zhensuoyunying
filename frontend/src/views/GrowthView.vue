<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b>营销增长计划（日常轻运营 + 节点活动）</b>
          <el-button type="primary" @click="dialogVisible = true">新建活动</el-button>
        </div>
      </template>
      <el-table :data="rows" stripe size="small">
        <el-table-column prop="name" label="活动名称" min-width="160" />
        <el-table-column prop="type" label="类型" width="110"><template #default="{row}">{{ typeLabel(row.type) }}</template></el-table-column>
        <el-table-column prop="objective" label="目标" width="110"><template #default="{row}">{{ objLabel(row.objective) }}</template></el-table-column>
        <el-table-column prop="status" label="状态" width="90"><template #default="{row}"><el-tag size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="预算" width="100"><template #default="{row}">¥{{ Number(row.budget || 0).toLocaleString() }}</template></el-table-column>
        <el-table-column label="时间" min-width="200"><template #default="{row}">{{ fmt(row.start_at) }} ~ {{ fmt(row.end_at) }}</template></el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{row}">
            <el-button size="small" @click="openAudience(row)">添加受众</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新建营销活动" width="480px">
      <el-form label-width="90px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type"><el-option label="日常轻运营" value="always_on" /><el-option label="节气/节日" value="seasonal" /><el-option label="节日" value="holiday" /><el-option label="新项目" value="new_service" /><el-option label="唤醒" value="reactivation" /></el-select>
        </el-form-item>
        <el-form-item label="目标">
          <el-select v-model="form.objective"><el-option label="新客" value="new_customer" /><el-option label="唤醒" value="reactivation" /><el-option label="留存" value="retention" /><el-option label="套餐销售" value="package_sales" /></el-select>
        </el-form-item>
        <el-form-item label="预算"><el-input-number v-model="form.budget" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="create">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="audDialog" :title="`添加受众：${current.name || ''}`" width="480px">
      <el-form label-width="90px">
        <el-form-item label="患者ID列表"><el-input v-model="audForm.patient_ids" type="textarea" :rows="4" placeholder="每行一个 patient_id" /></el-form-item>
        <el-form-item label="实验分组">
          <el-select v-model="audForm.experiment_group"><el-option label="对照 Control" value="control" /><el-option label="实验A" value="treatment_a" /><el-option label="实验B" value="treatment_b" /><el-option label="不分组" value="none" /></el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="audDialog = false">取消</el-button>
        <el-button type="primary" @click="addAudience">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const rows = ref([])
const dialogVisible = ref(false)
const audDialog = ref(false)
const current = ref({})
const form = reactive({ name: '', type: 'always_on', objective: 'reactivation', budget: 1000 })
const audForm = reactive({ patient_ids: '', experiment_group: 'control' })
const fmt = (s) => (s ? new Date(s).toLocaleDateString('zh-CN') : '-')
const typeLabel = (t) => ({ always_on: '日常轻运营', seasonal: '节气/季节', holiday: '节日', new_service: '新项目', reactivation: '老客唤醒' }[t] || t)
const objLabel = (o) => ({ new_customer: '拉新', reactivation: '唤醒', retention: '留存', package_sales: '套餐销售' }[o] || o)
const statusLabel = (s) => ({ draft: '草稿', running: '进行中', paused: '已暂停', completed: '已完成' }[s] || s)
const statusTag = (s) => ({ draft: 'info', running: 'success', paused: 'warning', completed: 'primary' }[s] || 'info')

async function load() {
  rows.value = (await api.get('/campaigns', { limit: 100 })).data
}
async function create() {
  await api.post('/campaigns', { ...form })
  ElMessage.success('活动已创建')
  dialogVisible.value = false
  load()
}
function openAudience(row) {
  current.value = row
  audForm.patient_ids = ''
  audDialog.value = true
}
async function addAudience() {
  const ids = audForm.patient_ids.split('\n').map((s) => s.trim()).filter(Boolean)
  await api.post(`/campaigns/${current.value.campaign_id}/audience`, {
    patient_ids: ids, experiment_group: audForm.experiment_group,
  })
  ElMessage.success(`已添加 ${ids.length} 名受众`)
  audDialog.value = false
}
onMounted(load)
</script>