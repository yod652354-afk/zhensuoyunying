<template>
  <div>
    <el-alert type="warning" :closable="false" show-icon
              title="待人工归因队列（R-04）：有候选机会但无执行证据（主方案/Touch）的事实无法自动确定归属，必须人工确认，不自动广播到全部机会。" style="margin-bottom:16px" />

    <el-card shadow="never">
      <el-table :data="rows" size="small" stripe>
        <el-table-column prop="fact_id" label="事实" width="180" />
        <el-table-column prop="fact_type" label="类型" width="110" />
        <el-table-column prop="occurred_at" label="发生时间" width="180" />
        <el-table-column label="金额" width="110">
          <template #default="{row}">¥{{ row.revenue_amount || 0 }}</template>
        </el-table-column>
        <el-table-column prop="source_system" label="来源" width="120" />
        <el-table-column prop="source_event_id" label="源事件" width="150" />
        <el-table-column label="候选/原因" min-width="220" show-overflow-tooltip>
          <template #default="{row}">{{ JSON.stringify(row.match_reason || {}) }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!rows.length" description="当前无待人工归因事项" :image-size="60" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../../api/client'

const rows = ref([])

onMounted(async () => {
  const r = await api.get('/attribution/manual-review-queue')
  rows.value = r.data || []
})
</script>
