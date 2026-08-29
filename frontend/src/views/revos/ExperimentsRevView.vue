<template>
  <div>
    <el-alert type="info" :closable="false" show-icon
              title="实验与增量归因：Treatment/Holdout 在内容生成前入组；对照组不得触达；增量 = Treatment − Control；不得将 Treatment 组全部收入相加作为增量收入。样本不足只标记方向性。" style="margin-bottom:16px" />

    <el-card shadow="never">
      <el-form inline>
        <el-form-item><el-button type="primary" @click="load">加载实验</el-button></el-form-item>
      </el-form>
      <el-table :data="experiments" size="small" stripe @row-click="selectExp" style="cursor:pointer">
        <el-table-column prop="experiment_id" label="实验ID" width="170" />
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column prop="engine" label="引擎" width="110" />
        <el-table-column prop="status" label="状态" width="100" />
      </el-table>
    </el-card>

    <el-card v-if="metrics" shadow="never" style="margin-top:16px">
      <template #header><b>实验指标：{{ metrics.experiment_id }}</b></template>
      <el-row :gutter="16">
        <el-col :span="8">
          <div class="kpi">{{ metrics.rates.incremental_rate }}<span class="unit">pp</span></div>
          <div class="kpi-label">增量率（Treatment − Control）</div>
          <div class="kpi-sub">Treatment 支付率：{{ metrics.rates.treatment_paid_rate }}%</div>
          <div class="kpi-sub">Control 支付率：{{ metrics.rates.control_paid_rate }}%</div>
        </el-col>
        <el-col :span="8">
          <div class="kpi">¥{{ fmt(metrics.revenue.incremental_revenue) }}</div>
          <div class="kpi-label">增量收入（合格人群 × 增量率 × 均值）</div>
          <div class="kpi-sub">Treatment 总收入：¥{{ fmt(metrics.revenue.gross_revenue_treatment) }}</div>
          <div class="kpi-sub">增量贡献：¥{{ fmt(metrics.revenue.incremental_contribution) }}</div>
          <div class="kpi-sub">ROI：{{ metrics.revenue.roi }}</div>
        </el-col>
        <el-col :span="8">
          <div class="kpi">{{ metrics.sample.treatment }} / {{ metrics.sample.control }}</div>
          <div class="kpi-label">样本（Treatment / Control）</div>
          <el-alert :type="metrics.directional_only ? 'warning' : 'success'" :closable="false" show-icon
                    :title="metrics.directional_only ? '样本不足，仅方向性结论' : '样本充足'" style="margin-top:8px" />
          <div class="kpi-sub">护栏：DNC {{ metrics.guardrails.dnc_treatment }} · 投诉 {{ metrics.guardrails.complaint_treatment }}</div>
        </el-col>
      </el-row>
      <el-button type="primary" size="small" style="margin-top:12px" @click="recalc">重新计算</el-button>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../../api/client'

const experiments = ref([])
const metrics = ref(null)
const fmt = (v) => Number(v || 0).toLocaleString()

async function load() {
  const r = await api.get('/experiments?limit=50')
  experiments.value = r.data || []
}

async function selectExp(row) {
  const r = await api.post(`/experiments/${row.experiment_id}/calculate`)
  metrics.value = r.data
}

async function recalc() {
  if (metrics.value) await selectExp({ experiment_id: metrics.value.experiment_id })
}

onMounted(load)
</script>

<style scoped>
.kpi { font-size: 24px; font-weight: 700; }
.kpi-label { color: #909399; font-size: 13px; margin-top: 4px; }
.kpi-sub { font-size: 13px; color: #606266; margin-top: 6px; }
.unit { font-size: 14px; font-weight: 400; color: #909399; }
</style>
