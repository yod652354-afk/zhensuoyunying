<template>
  <div>
    <el-alert type="info" :closable="false" show-icon
              title="客户经营档案：稳定 customer_id（手机号可变更不改变 ID）、生命周期时间轴、三种钱迁移历史、机会/方案/结果/归因时间线。诊所SaaS仍是患者资料事实主系统，本页为经营聚合视图。" style="margin-bottom:16px" />

    <el-card shadow="never">
      <el-form inline>
        <el-form-item label="生命周期">
          <el-select v-model="filters.lifecycle_state" clearable placeholder="全部" style="width:140px" @change="load">
            <el-option v-for="s in lifecycles" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="三种钱">
          <el-select v-model="filters.money_state" clearable placeholder="全部" style="width:130px" @change="load">
            <el-option label="未来" value="future" />
            <el-option label="现在" value="current" />
            <el-option label="过去" value="past" />
          </el-select>
        </el-form-item>
        <el-form-item><el-button type="primary" @click="load">刷新</el-button></el-form-item>
      </el-form>

      <el-table :data="rows" size="small" stripe @row-click="showProfile" style="cursor:pointer">
        <el-table-column prop="customer_id" label="客户ID" width="180" />
        <el-table-column prop="display_name" label="显示名" width="100" />
        <el-table-column label="生命周期" width="110">
          <template #default="{row}"><el-tag size="small">{{ row.lifecycle_state }}</el-tag></template>
        </el-table-column>
        <el-table-column label="三种钱" width="90">
          <template #default="{row}">
            <el-tag size="small" :type="moneyTag(row.money_state)">{{ row.money_state }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="价值等级" width="90">
          <template #default="{row}"><b>{{ row.value_tier }}</b></template>
        </el-table-column>
        <el-table-column prop="total_visits" label="到店" width="70" />
        <el-table-column label="累计消费" width="110">
          <template #default="{row}">¥{{ fmt(row.total_revenue) }}</template>
        </el-table-column>
        <el-table-column prop="last_visit_date" label="最近到店" width="170" />
        <el-table-column label="合规" width="140">
          <template #default="{row}">
            <el-tag v-if="row.dnc" size="small" type="danger">DNC</el-tag>
            <el-tag v-if="row.complaint_flag" size="small" type="danger">投诉</el-tag>
            <el-tag v-if="row.consent_status === 'granted'" size="small" type="success">已授权</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-drawer v-model="profileVisible" title="客户经营档案" size="46%">
      <template v-if="profile">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="客户ID">{{ profile.customer_id }}</el-descriptions-item>
          <el-descriptions-item label="生命周期">{{ profile.lifecycle_state }}</el-descriptions-item>
          <el-descriptions-item label="三种钱">{{ profile.money_state }}</el-descriptions-item>
          <el-descriptions-item label="价值等级">{{ profile.value_tier }}</el-descriptions-item>
          <el-descriptions-item label="到店次数">{{ profile.total_visits }}</el-descriptions-item>
          <el-descriptions-item label="累计消费">¥{{ fmt(profile.total_revenue) }}</el-descriptions-item>
        </el-descriptions>
        <el-divider />
        <b>状态迁移历史（含触发原因与规则版本）</b>
        <el-timeline style="margin-top:12px">
          <el-timeline-item v-for="(s, i) in profile.state_history" :key="i" type="primary">
            <div>{{ s.lifecycle_from || '—' }} → <b>{{ s.lifecycle_to }}</b>（{{ s.money_from || '—' }} → {{ s.money_to }}）</div>
            <div class="tl-sub">{{ (s.reason_codes || []).join(' / ') }} · {{ s.rule_version }}</div>
            <div class="tl-sub">{{ s.effective_from }}</div>
          </el-timeline-item>
        </el-timeline>
        <el-divider />
        <b>机会时间线</b>
        <el-table :data="profile.opportunities" size="small" style="margin-top:8px">
          <el-table-column prop="opportunity_id" label="机会" width="170" />
          <el-table-column prop="money_type" label="钱" width="70" />
          <el-table-column prop="scenario_type" label="场景" width="130" />
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column label="预计" width="90"><template #default="{row}">¥{{ row.expected_revenue }}</template></el-table-column>
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../../api/client'

const rows = ref([])
const profile = ref(null)
const profileVisible = ref(false)
const filters = reactive({ lifecycle_state: null, money_state: null })
const lifecycles = ['lead', 'engaged', 'booked', 'visited', 'converted', 'in_service', 'active', 'at_risk', 'dormant', 'lost', 'reactivated']
const moneyTag = (k) => ({ future: 'success', current: 'warning', past: 'danger' }[k] || 'info')
const fmt = (v) => Number(v || 0).toLocaleString()

async function load() {
  const params = {}
  if (filters.lifecycle_state) params.lifecycle_state = filters.lifecycle_state
  if (filters.money_state) params.money_state = filters.money_state
  const r = await api.get('/customers', params)
  rows.value = r.data || []
}

async function showProfile(row) {
  const r = await api.get(`/customers/${row.customer_id}/revenue-profile`)
  profile.value = r.data
  profileVisible.value = true
}

onMounted(load)
</script>

<style scoped>
.tl-sub { color: #909399; font-size: 12px; }
</style>
