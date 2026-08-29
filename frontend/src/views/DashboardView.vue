<template>
  <div>
    <el-alert type="info" :closable="false" show-icon title="经营驾驶舱：过去的钱（客户唤醒）· 现在的钱（复诊留存）· 未来的钱（营销增长），一切以增量口径为准，不把自然回款算作系统功劳。" style="margin-bottom:16px" />
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header><b>过去的钱 · 客户唤醒</b></template>
          <div class="kpi">{{ fmt(past.recoverable_revenue) }}</div>
          <div class="kpi-label">可追回收入（前50高价值沉睡/流失）</div>
          <el-divider />
          <div class="kpi-sub">本月增量追回：<b>{{ fmt(past.incremental_recovered) }}</b></div>
          <div class="kpi-sub">Recovery ROI：<b>{{ past.recovery_roi }}x</b></div>
          <div class="kpi-sub">客户池规模：<b>{{ past.pool_size }}</b> 人</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header><b>现在的钱 · 复诊留存</b></template>
          <div class="kpi">{{ present.due_today }}<span class="unit">人</span></div>
          <div class="kpi-label">今日应复诊</div>
          <el-divider />
          <div class="kpi-sub">超期复诊：<b>{{ present.overdue }}</b> 人</div>
          <div class="kpi-sub">调整后复诊率：<b>{{ present.adjusted_retention_rate }}%</b></div>
          <div class="kpi-sub" v-if="present.funnel_leak_top">最大漏损：{{ present.funnel_leak_top.from }} → {{ present.funnel_leak_top.to }}（{{ present.funnel_leak_top.drop }}人）</div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <template #header><b>未来的钱 · 营销增长</b></template>
          <div class="kpi">{{ fmt(future.expected_growth_revenue) }}</div>
          <div class="kpi-label">预计增量收入（待执行 Growth 任务）</div>
          <el-divider />
          <div class="kpi-sub">进行中活动：<b>{{ future.running_campaigns }}</b> 个</div>
          <div class="kpi-sub">Growth 执行率：<b>{{ future.execution_rate }}%</b></div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin-top:16px">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header><b>本月总结果（Incremental Recovery + Retention + Growth）</b></template>
          <el-row :gutter="8" v-if="monthly.total_incremental !== undefined">
            <el-col :span="6" v-for="(v, k) in monthly" :key="k" style="text-align:center">
              <div class="kpi" :style="{ fontSize: '22px' }">¥{{ fmt(v) }}</div>
              <div class="kpi-label">{{ { recovery: 'Recovery', retention: 'Retention', growth: 'Growth', total_incremental: '总增量' }[k] }}</div>
            </el-col>
          </el-row>
          <el-divider />
          <b>员工激励（按增量价值）</b>
          <el-table :data="incentives" size="small" style="margin-top:8px">
            <el-table-column prop="name" label="员工" width="90" />
            <el-table-column prop="tasks_completed" label="完成" width="60" />
            <el-table-column prop="completion_rate" label="完成率" width="80"><template #default="{row}">{{ row.completion_rate }}%</template></el-table-column>
            <el-table-column label="增量价值" width="110"><template #default="{row}">¥{{ Number(row.incremental_value).toLocaleString() }}</template></el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header><b>复诊留存漏斗（近90天）</b></template>
          <div ref="funnelChart" style="height:300px"></div>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="hover">
          <template #header><b>异常预警</b></template>
          <el-empty v-if="!anomalies.length" description="暂无异常" :image-size="60" />
          <el-timeline v-else>
            <el-timeline-item v-for="(a, i) in anomalies" :key="i" :type="a.severity === 'high' ? 'danger' : a.severity === 'medium' ? 'warning' : 'info'">
              <b>{{ a.message }}</b>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="hover" style="margin-top:16px">
      <template #header><b>实验增量看板</b></template>
      <el-table :data="experiments" size="small" stripe>
        <el-table-column prop="name" label="实验" min-width="160" />
        <el-table-column prop="engine" label="引擎" width="90" />
        <el-table-column prop="status" label="状态" width="90" />
        <el-table-column label="对照组" width="120"><template #default="{row}">{{ row.control.n }} 人 / {{ row.control.visit_rate }}%</template></el-table-column>
        <el-table-column label="实验组" width="120"><template #default="{row}">{{ row.treatment.n }} 人 / {{ row.treatment.visit_rate }}%</template></el-table-column>
        <el-table-column prop="incremental_lift_pp" label="增量Lift" width="100"><template #default="{row}">{{ row.incremental_lift_pp }} pp</template></el-table-column>
        <el-table-column prop="incremental_revenue" label="增量收入"><template #default="{row}">¥{{ fmt(row.incremental_revenue) }}</template></el-table-column>
        <el-table-column prop="roi" label="ROI" width="90"><template #default="{row}">{{ row.roi ?? '-' }}x</template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
import * as echarts from 'echarts'
import { api } from '../api/client'

const past = ref({})
const present = ref({})
const future = ref({})
const monthly = ref({})
const incentives = ref([])
const anomalies = ref([])
const experiments = ref([])
const funnelChart = ref(null)
let chart = null

const fmt = (v) => (v === undefined || v === null ? '-' : '¥' + Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 }))

onMounted(async () => {
  const [dResp, funnelResp] = await Promise.all([
    api.get('/analytics/dashboard'),
    api.get('/analytics/retention-funnel'),
  ])
  const d = dResp.data
  past.value = d.past_money
  monthly.value = d.monthly_summary || {}
  incentives.value = d.staff_incentive || []
  present.value = d.present_money
  future.value = d.future_money
  anomalies.value = d.anomalies || []
  experiments.value = d.experiments || []
  chart = echarts.init(funnelChart.value)
  const funnel = funnelResp.data.funnel || []
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 30, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: funnel.map((f) => f.node) },
    yAxis: { type: 'value', name: '人数' },
    series: [{ type: 'bar', barWidth: '45%', itemStyle: { color: '#409eff' }, label: { show: true, position: 'top' }, data: funnel.map((f) => f.count) }],
  })
})

onBeforeUnmount(() => chart && chart.dispose())
</script>

<style scoped>
.kpi { font-size: 32px; font-weight: 700; color: #303133; }
.unit { font-size: 14px; color: #909399; margin-left: 4px; }
.kpi-label { color: #909399; font-size: 13px; margin-top: 4px; }
.kpi-sub { font-size: 13px; color: #606266; margin-top: 6px; }
</style>