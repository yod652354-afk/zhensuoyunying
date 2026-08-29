<template>
  <div>
    <el-tabs v-model="tab">
      <!-- ============ 漏损报表 ============ -->
      <el-tab-pane label="漏损报表" name="leak">
        <el-card shadow="never">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
            <b>漏损总览</b>
            <el-button type="primary" size="small" :loading="engineLoading" @click="triggerEngine">触发自动任务引擎（超期/No-show/疗程中断 → 任务）</el-button>
          </div>
          <el-row :gutter="16">
            <el-col :span="6"><el-statistic title="可追回收入" :value="leak.recoverable_revenue" :precision="0"><template #prefix>¥</template></el-statistic></el-col>
            <el-col :span="6"><el-statistic title="Recovery 池人数" :value="leak.recovery_pool_size" /></el-col>
            <el-col :span="6"><el-statistic title="高价值沉睡(≥¥500)" :value="leak.high_value_sleeping" /></el-col>
            <el-col :span="6"><el-statistic title="超期复诊" :value="leak.overdue_revisits" /></el-col>
          </el-row>
          <el-divider />
          <div style="display:flex;gap:24px">
            <div style="flex:1">
              <b>漏损节点（漏斗流失）</b>
              <el-table :data="leak.leak_by_node" size="small" style="margin-top:8px">
                <el-table-column prop="from" label="上游节点" />
                <el-table-column prop="to" label="下游节点" />
                <el-table-column prop="drop" label="流失人数" width="100" />
              </el-table>
            </div>
            <div style="flex:1">
              <b>按医生过程指标</b>
              <el-table :data="leak.by_doctor" size="small" style="margin-top:8px">
                <el-table-column prop="name" label="医生" width="90" />
                <el-table-column prop="total" label="到店" width="60" />
                <el-table-column prop="recommendation_rate" label="建议率%" width="80" />
                <el-table-column prop="fulfillment_rate" label="履约率%" width="80" />
                <el-table-column label="异常" width="70"><template #default="{row}"><el-tag v-if="row.flagged" type="danger" size="small">低</el-tag><span v-else>-</span></template></el-table-column>
              </el-table>
            </div>
          </div>
          <el-divider />
          <b>按项目大类</b>
          <el-table :data="leak.by_category" size="small" style="margin-top:8px">
            <el-table-column prop="category" label="项目大类" />
            <el-table-column prop="visits" label="到店次数" width="100" />
            <el-table-column label="近90天收入" width="140"><template #default="{row}">¥{{ Number(row.revenue).toLocaleString() }}</template></el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ============ 数据对账 ============ -->
      <el-tab-pane label="数据对账" name="recon">
        <el-card shadow="never">
          <div style="display:flex;gap:12px;margin-bottom:12px;align-items:center">
            <b>核对日期：</b>
            <el-date-picker v-model="reconDate" type="date" value-format="YYYY-MM-DD" />
            <el-button type="primary" @click="loadRecon">核对</el-button>
            <el-tag v-if="recon.balance_ok !== undefined" :type="recon.balance_ok ? 'success' : 'danger'">
              {{ recon.balance_ok ? '账目平衡' : `发现 ${recon.differences.length} 处差异` }}
            </el-tag>
          </div>
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="新增患者">{{ recon.counters?.new_patients }}</el-descriptions-item>
            <el-descriptions-item label="到店">{{ recon.counters?.visits }}</el-descriptions-item>
            <el-descriptions-item label="新预约">{{ recon.counters?.appointments_created }}</el-descriptions-item>
            <el-descriptions-item label="No-show">{{ recon.counters?.no_shows }}</el-descriptions-item>
            <el-descriptions-item label="订单金额">¥{{ recon.amounts?.orders_amount }}</el-descriptions-item>
            <el-descriptions-item label="支付金额">¥{{ recon.amounts?.payments_amount }}</el-descriptions-item>
            <el-descriptions-item label="退款">¥{{ recon.amounts?.refunds_amount }}</el-descriptions-item>
            <el-descriptions-item label="净收入">¥{{ recon.amounts?.net_revenue }}</el-descriptions-item>
          </el-descriptions>
          <el-table v-if="recon.differences?.length" :data="recon.differences" size="small" style="margin-top:12px" border>
            <el-table-column prop="type" label="差异类型" />
            <el-table-column prop="order_id" label="订单ID" min-width="180" />
            <el-table-column prop="order_amount" label="订单金额" />
            <el-table-column prop="paid_amount" label="已支付" />
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ============ 每周复盘 ============ -->
      <el-tab-pane label="每周复盘（经验沉淀）" name="review">
        <el-card shadow="never">
          <template #header>
            <div style="display:flex;justify-content:space-between">
              <b>动作→结果复盘（人工闭环）</b>
              <el-button type="primary" size="small" @click="reviewDialog = true">新建复盘</el-button>
            </div>
          </template>
          <el-timeline>
            <el-timeline-item v-for="r in reviews" :key="r.review_id" timestamp="周期性复盘" placement="top" type="primary">
              <el-card shadow="never">
                <b>{{ r.engine }} · {{ r.period_start?.slice(0,10) }} ~ {{ r.period_end?.slice(0,10) }}</b>
                <p>{{ r.summary }}</p>
                <el-space wrap>
                  <el-tag v-for="a in r.actions_kept" size="small" type="success">保留: {{ a }}</el-tag>
                  <el-tag v-for="a in r.actions_dropped" size="small" type="danger">淘汰: {{ a }}</el-tag>
                </el-space>
                <p v-if="r.next_week_plan" style="margin-top:8px"><b>下周计划：</b>{{ r.next_week_plan }}</p>
              </el-card>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="reviewDialog" title="新建每周复盘" width="560px">
      <el-form label-width="100px">
        <el-form-item label="周期开始"><el-date-picker v-model="revForm.period_start" type="date" value-format="YYYY-MM-DDT00:00:00+08:00" /></el-form-item>
        <el-form-item label="周期结束"><el-date-picker v-model="revForm.period_end" type="date" value-format="YYYY-MM-DDT00:00:00+08:00" /></el-form-item>
        <el-form-item label="引擎"><el-select v-model="revForm.engine"><el-option label="全部" value="all" /><el-option label="Recovery" value="recovery" /><el-option label="Retention" value="retention" /><el-option label="Growth" value="growth" /></el-select></el-form-item>
        <el-form-item label="总结"><el-input v-model="revForm.summary" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="保留动作"><el-input v-model="revForm.actions_kept" placeholder="逗号分隔" /></el-form-item>
        <el-form-item label="淘汰动作"><el-input v-model="revForm.actions_dropped" placeholder="逗号分隔" /></el-form-item>
        <el-form-item label="下周计划"><el-input v-model="revForm.next_week_plan" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewDialog = false">取消</el-button>
        <el-button type="primary" @click="createReview">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'

const tab = ref('leak')
const leak = ref({})
const recon = ref({})
const reconDate = ref(new Date().toISOString().slice(0, 10))
const reviews = ref([])
const reviewDialog = ref(false)
const revForm = reactive({ period_start: '', period_end: '', engine: 'all', summary: '', actions_kept: '', actions_dropped: '', next_week_plan: '' })

async function loadLeak() {
  leak.value = (await api.get('/analytics/revenue-leakage-report', { days: 90 })).data
}
async function loadRecon() {
  recon.value = (await api.get('/analytics/reconciliation', { date: reconDate.value })).data
}
async function loadReviews() {
  reviews.value = (await api.get('/reviews')).data
}
const engineLoading = ref(false)
async function triggerEngine() {
  engineLoading.value = true
  try {
    const r = await api.post('/analytics/engine/retention-tasks')
    ElMessage.success(`已生成 ${r.data.created} 条任务（超期复诊/No-show挽回/疗程中断）`)
    loadLeak()
  } finally {
    engineLoading.value = false
  }
}
async function createReview() {
  const payload = { ...revForm }
  payload.actions_kept = revForm.actions_kept ? revForm.actions_kept.split(',').map((s) => s.trim()) : []
  payload.actions_dropped = revForm.actions_dropped ? revForm.actions_dropped.split(',').map((s) => s.trim()) : []
  await api.post('/reviews', payload)
  ElMessage.success('复盘已保存')
  reviewDialog.value = false
  loadReviews()
}
onMounted(() => { loadLeak(); loadRecon(); loadReviews() })
</script>