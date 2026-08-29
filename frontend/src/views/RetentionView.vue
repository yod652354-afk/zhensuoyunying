<template>
  <div>
    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header><b>诊后过程漏斗（建议 → 预约 → 履约 → 复诊）</b></template>
          <div ref="chart" style="height:320px"></div>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never">
          <template #header><b>漏损节点定位</b></template>
          <el-empty v-if="!leaks.length" description="窗口内暂无漏损" :image-size="60" />
          <el-table v-else :data="leaks" size="small" stripe>
            <el-table-column prop="from" label="上游" />
            <el-table-column prop="to" label="下游" />
            <el-table-column prop="drop" label="流失人数" width="90" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
    <el-row :gutter="16" style="margin-top:16px">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><b>今日应复诊（{{ dueToday.length }} 人）</b></template>
          <el-table :data="dueToday" size="small" max-height="280">
            <el-table-column prop="patient_id" label="患者ID" min-width="150" />
            <el-table-column prop="doctor_id" label="医生" width="110" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><b>超期复诊预警（{{ overdue.length }} 人）</b></template>
          <el-table :data="overdue" size="small" max-height="280">
            <el-table-column prop="patient_name" label="患者" width="100" />
            <el-table-column prop="overdue_days" label="超期天数" width="90"><template #default="{row}"><el-tag size="small" :type="row.overdue_days > 30 ? 'danger' : 'warning'">{{ row.overdue_days }}天</el-tag></template></el-table-column>
            <el-table-column prop="recommended_window" label="建议窗口" min-width="180"><template #default="{row}">{{ row.recommended_window.join(' ~ ') }}</template></el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { api } from '../api/client'

const chart = ref(null)
const leaks = ref([])
const dueToday = ref([])
const overdue = ref([])
let instance = null

onMounted(async () => {
  const [f, d, o] = await Promise.all([
    api.get('/analytics/retention-funnel'),
    api.get('/analytics/retention/due-today'),
    api.get('/analytics/retention/overdue'),
  ])
  const funnel = f.data.funnel || []
  leaks.value = f.data.leak_nodes || []
  dueToday.value = d.data
  overdue.value = o.data
  instance = echarts.init(chart.value)
  instance.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 30, top: 30, bottom: 40 },
    xAxis: { type: 'category', data: funnel.map((x) => x.node) },
    yAxis: { type: 'value' },
    series: [{
      type: 'bar', barWidth: '45%',
      itemStyle: { color: (p) => ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399'][p.dataIndex % 5] },
      label: { show: true, position: 'top', formatter: '{c}' },
      data: funnel.map((x) => x.count),
    }],
  })
})
onBeforeUnmount(() => instance && instance.dispose())
</script>