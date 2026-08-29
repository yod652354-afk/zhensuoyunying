<template>
  <div>
    <el-alert type="info" :closable="false" show-icon title="RevOS 三种钱驾驶舱：数据统一来自 Opportunity / Outcome，不是三套独立计算。三种钱是机会分类，同一客户可有多个机会；同一运营周期仅一个主要外部计划。" style="margin-bottom:16px" />
    <el-row :gutter="16">
      <el-col :span="8" v-for="(g, key) in moneyGroups" :key="key">
        <el-card shadow="hover">
          <template #header>
            <b>{{ moneyLabel(key) }}</b>
            <el-tag size="small" style="float:right">{{ g.opportunity_count }} 个机会</el-tag>
          </template>
          <div class="kpi">¥{{ fmt(g.expected_amount) }}</div>
          <div class="kpi-label">机会预计金额（不等于已归因收入）</div>
          <el-divider />
          <div class="kpi-sub">机会客户数：<b>{{ g.opportunity_customers }}</b> 人</div>
          <div class="kpi-sub">待执行金额：<b>¥{{ fmt(g.pending_amount) }}</b></div>
          <div class="kpi-sub">执行中金额：<b>¥{{ fmt(g.executing_amount) }}</b></div>
          <div class="kpi-sub">已赢得增量收入：<b>¥{{ fmt(g.won_incremental) }}</b></div>
          <div class="kpi-sub" v-if="g.status_breakdown">
            状态分布：
            <el-tag v-for="(n, s) in g.status_breakdown" :key="s" size="small" style="margin-right:4px">{{ s }}:{{ n }}</el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin-top:16px">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header><b>结果转化漏斗（统一 Outcome）</b></template>
          <el-table :data="funnelRows" size="small">
            <el-table-column prop="label" label="节点" />
            <el-table-column prop="count" label="数量" width="100" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header><b>归因可信度</b></template>
          <el-alert :type="trustType" :closable="false" show-icon
                    :title="trustNote" style="margin-bottom:12px" />
          <el-text type="info" size="small">小样本只标记方向性结论，不宣称显著；增量口径 = Treatment − Control，不把全部收入相加。归因可信度：{{ data?.attribution_trust }}</el-text>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../../api/client'

const data = ref(null)

const moneyGroups = computed(() => data.value?.money_groups || {})
const funnel = computed(() => data.value?.conversion_funnel || {})
const funnelRows = computed(() => [
  { label: '回复 replied', count: funnel.value.replied || 0 },
  { label: '预约 appointment', count: funnel.value.appointment || 0 },
  { label: '到店 visited', count: funnel.value.visited || 0 },
  { label: '支付 paid', count: funnel.value.paid || 0 },
  { label: 'DNC', count: funnel.value.dnc || 0 },
  { label: '投诉 complaint', count: funnel.value.complaint || 0 },
])
const trustType = computed(() => (data.value?.attribution_trust === 'adequate' ? 'success' : 'warning'))
const trustNote = computed(() =>
  data.value?.attribution_trust === 'adequate'
    ? '样本充足，归因可作决策依据'
    : '当前样本不足，仅作方向性参考')

const moneyLabel = (k) => ({ future: '未来的钱 · 新客增长', current: '现在的钱 · 服务复购', past: '过去的钱 · 沉睡召回' }[k] || k)
const fmt = (v) => Number(v || 0).toLocaleString()

onMounted(async () => {
  const r = await api.get('/analytics/revos/cockpit')
  data.value = r.data
})
</script>

<style scoped>
.kpi { font-size: 26px; font-weight: 700; color: #303133; }
.kpi-label { color: #909399; font-size: 13px; margin-top: 4px; }
.kpi-sub { font-size: 13px; color: #606266; margin-top: 6px; }
</style>
