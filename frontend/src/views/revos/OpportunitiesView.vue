<template>
  <div>
    <el-card shadow="never">
      <el-form inline>
        <el-form-item label="三种钱">
          <el-select v-model="filters.money_type" clearable placeholder="全部" style="width:130px" @change="load">
            <el-option label="未来的钱" value="future" />
            <el-option label="现在的钱" value="current" />
            <el-option label="过去的钱" value="past" />
          </el-select>
        </el-form-item>
        <el-form-item label="场景">
          <el-select v-model="filters.scenario_type" clearable placeholder="全部" style="width:170px" @change="load">
            <el-option v-for="(v, k) in scenarioLabels" :key="k" :label="v" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width:130px" @change="load">
            <el-option v-for="s in statuses" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="detect">识别机会</el-button>
          <el-button @click="load">刷新</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="rows" size="small" stripe @row-click="openDetail" style="cursor:pointer">
        <el-table-column prop="opportunity_id" label="机会ID" width="180" />
        <el-table-column label="三种钱" width="90">
          <template #default="{row}">
            <el-tag :type="moneyTag(row.money_type)" size="small">{{ moneyLabel(row.money_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="场景" width="130">
          <template #default="{row}">{{ scenarioLabels[row.scenario_type] || row.scenario_type }}</template>
        </el-table-column>
        <el-table-column label="优先级" width="90">
          <template #default="{row}"><b>{{ row.priority_score }}</b></template>
        </el-table-column>
        <el-table-column prop="expected_revenue" label="预计收入" width="100">
          <template #default="{row}">¥{{ fmt(row.expected_revenue) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{row}"><el-tag size="small" :type="statusTag(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="原因" min-width="200">
          <template #default="{row}">
            <el-tag v-for="r in (row.reason_codes || []).slice(0, 3)" :key="r" size="small" style="margin-right:4px">{{ r }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="实验组" width="110">
          <template #default="{row}">
            <el-tag v-if="row.experiment_group" size="small" :type="row.experiment_group === 'control' ? 'info' : 'warning'">{{ row.experiment_group }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{row}">
            <el-button size="small" type="primary" link @click.stop="openDetail(row)">详情</el-button>
            <el-button size="small" type="warning" link @click.stop="suppress(row)">抑制</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../api/client'

const router = useRouter()
const rows = ref([])
const filters = reactive({ money_type: null, scenario_type: null, status: null })
const scenarioLabels = {
  dormant_recovery: '沉睡召回', overdue_revisit: '复诊超期', no_show: 'No-show',
  treatment_interruption: '疗程中断', new_customer: '新客转化', referral: '转介绍',
  package_renewal: '套餐续费', followup_care: '诊后关怀', other: '其他',
}
const statuses = ['candidate', 'qualified', 'approved', 'executing', 'won', 'lost', 'expired', 'suppressed']
const moneyLabel = (k) => ({ future: '未来', current: '现在', past: '过去' }[k] || k)
const moneyTag = (k) => ({ future: 'success', current: 'warning', past: 'danger' }[k] || 'info')
const statusTag = (s) => ({ candidate: 'info', qualified: 'primary', approved: 'success', executing: 'warning', won: 'success', lost: 'danger', expired: 'info', suppressed: 'info' }[s] || 'info')
const fmt = (v) => Number(v || 0).toLocaleString()

async function load() {
  const params = {}
  if (filters.money_type) params.money_type = filters.money_type
  if (filters.scenario_type) params.scenario_type = filters.scenario_type
  if (filters.status) params.status = filters.status
  const r = await api.get('/opportunities', params)
  rows.value = r.data || []
}

async function detect() {
  await api.post('/opportunities/detect/dormant-recovery')
  ElMessage.success('沉睡机会识别完成')
  await load()
}

async function suppress(row) {
  await ElMessageBox.confirm(`确认抑制机会 ${row.opportunity_id}？`, '提示')
  await api.patch(`/opportunities/${row.opportunity_id}/suppress`, { reason: '人工抑制' })
  ElMessage.success('已抑制')
  await load()
}

function openDetail(row) {
  router.push(`/revos/opportunities/${row.opportunity_id}`)
}

onMounted(load)
</script>
