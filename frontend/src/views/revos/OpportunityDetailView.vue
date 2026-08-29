<template>
  <div v-if="opp">
    <el-page-header @back="$router.back()" :content="`机会 ${opp.opportunity_id}`" style="margin-bottom:16px" />

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><b>机会信息</b></template>
          <el-descriptions :column="2" size="small">
            <el-descriptions-item label="三种钱"><el-tag :type="moneyTag(opp.money_type)" size="small">{{ opp.money_type }}</el-tag></el-descriptions-item>
            <el-descriptions-item label="场景">{{ opp.scenario_type }}</el-descriptions-item>
            <el-descriptions-item label="状态"><el-tag size="small">{{ opp.status }}</el-tag></el-descriptions-item>
            <el-descriptions-item label="优先级">{{ opp.priority_score }}</el-descriptions-item>
            <el-descriptions-item label="预计收入">¥{{ opp.expected_revenue }}</el-descriptions-item>
            <el-descriptions-item label="概率">{{ opp.probability }}</el-descriptions-item>
            <el-descriptions-item label="预计成本">¥{{ opp.expected_cost }}</el-descriptions-item>
            <el-descriptions-item label="实验组">{{ opp.experiment_group || '—' }}</el-descriptions-item>
            <el-descriptions-item label="检测版本">{{ opp.detector_version }}</el-descriptions-item>
            <el-descriptions-item label="评分版本">{{ opp.scoring_version }}</el-descriptions-item>
            <el-descriptions-item label="工作流">{{ opp.workflow_code }}</el-descriptions-item>
            <el-descriptions-item label="过期时间">{{ opp.expires_at }}</el-descriptions-item>
          </el-descriptions>
          <el-divider />
          <b>判断原因（reason_codes）</b>
          <div style="margin-top:8px">
            <el-tag v-for="r in (opp.reason_codes || [])" :key="r" size="small" style="margin-right:6px">{{ r }}</el-tag>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><b>操作</b></template>
          <el-space wrap>
            <el-button type="primary" @click="qualify">合格化</el-button>
            <el-button type="warning" @click="arbitrate">仲裁</el-button>
            <el-button type="success" @click="decide">生成决策</el-button>
            <el-button type="primary" plain @click="createPlan">创建执行方案</el-button>
            <el-button type="primary" @click="generateContent">生成内容</el-button>
            <el-button type="danger" plain @click="suppress">抑制</el-button>
          </el-space>
          <el-divider />
          <el-text type="info" size="small">对照组不得生成内容/任务/触达；内容生成后需自动检查 + 人工审核才能进入发送。</el-text>
        </el-card>
        <el-card shadow="never" style="margin-top:16px">
          <template #header><b>证据链（Attribution Trace）</b></template>
          <el-button size="small" @click="loadTrace">查看完整追溯</el-button>
          <pre v-if="trace" class="trace">{{ trace }}</pre>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../../api/client'

const route = useRoute()
const opp = ref(null)
const trace = ref(null)
const oppId = route.params.opportunity_id
const moneyTag = (k) => ({ future: 'success', current: 'warning', past: 'danger' }[k] || 'info')

async function load() {
  const r = await api.get(`/opportunities/${oppId}`)
  opp.value = r.data
}
async function qualify() { await api.post(`/opportunities/${oppId}/qualify`); ElMessage.success('已合格化'); load() }
async function arbitrate() { await api.post(`/opportunities/${oppId}/arbitrate`); ElMessage.success('仲裁完成'); load() }
async function decide() { await api.post(`/opportunities/${oppId}/decide`); ElMessage.success('决策已生成'); load() }
async function createPlan() { await api.post(`/opportunities/${oppId}/execution-plan`); ElMessage.success('执行方案已创建'); load() }
async function generateContent() {
  const r = await api.post(`/opportunities/${oppId}/generate-content`)
  ElMessage.success(`内容已生成: ${r.data.content_draft_id}`)
}
async function suppress() { await api.patch(`/opportunities/${oppId}/suppress`, { reason: '人工抑制' }); ElMessage.success('已抑制'); load() }
async function loadTrace() {
  const r = await api.get(`/attributions/${oppId}/trace`)
  trace.value = JSON.stringify(r.data, null, 2)
}

onMounted(load)
</script>

<style scoped>
.trace { background: #f6f8fa; padding: 12px; border-radius: 6px; font-size: 12px; max-height: 320px; overflow: auto; }
</style>
