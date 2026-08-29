<template>
  <div>
    <el-alert type="warning" :closable="false" show-icon
              title="审核对象是完整 ExecutionPlan（不只文案）：需确认机会原因、三种钱分类、预计价值、内容版本、自动检查结果、Consent/DNC/近期触达、发送员工与时间、实验组别。批准版本不可修改；修改需重新审核。" style="margin-bottom:16px" />

    <el-card shadow="never">
      <el-form inline>
        <el-form-item label="状态">
          <el-select v-model="status" clearable placeholder="全部" style="width:160px" @change="load">
            <el-option label="草稿" value="draft" />
            <el-option label="待审核" value="pending_review" />
            <el-option label="检查未过" value="check_failed" />
            <el-option label="已批准" value="approved" />
            <el-option label="已驳回" value="rejected" />
          </el-select>
        </el-form-item>
        <el-form-item><el-button type="primary" @click="load">刷新</el-button></el-form-item>
      </el-form>

      <el-table :data="rows" size="small" stripe>
        <el-table-column prop="content_draft_id" label="草稿ID" width="170" />
        <el-table-column prop="title" label="标题" width="140" />
        <el-table-column label="版本" width="70"><template #default="{row}">v{{ row.version }}</template></el-table-column>
        <el-table-column label="生成方式" width="90"><template #default="{row}"><el-tag size="small">{{ row.generation_mode }}</el-tag></template></el-table-column>
        <el-table-column prop="strategy_code" label="策略" width="130" />
        <el-table-column label="正文" min-width="220" show-overflow-tooltip>
          <template #default="{row}">{{ row.wecom_text }}</template>
        </el-table-column>
        <el-table-column label="风险" width="160">
          <template #default="{row}">
            <el-tag v-for="f in (row.risk_flags || []).slice(0, 2)" :key="f" size="small" type="danger" style="margin-right:4px">{{ f }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{row}"><el-tag size="small" :type="statusTag(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{row}">
            <el-button size="small" type="primary" link @click="machineCheck(row)">机器检查</el-button>
            <el-button size="small" type="success" link @click="review(row, 'approved')">批准</el-button>
            <el-button size="small" type="warning" link @click="review(row, 'changes_requested')">要求修改</el-button>
            <el-button size="small" type="danger" link @click="review(row, 'rejected')">驳回</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../../api/client'

const rows = ref([])
const status = ref(null)
const statusTag = (s) => ({ draft: 'info', pending_review: 'warning', check_failed: 'danger', approved: 'success', rejected: 'danger', superseded: 'info' }[s] || 'info')

async function load() {
  const params = {}
  if (status.value) params.status = status.value
  const r = await api.get('/content-drafts', params)
  rows.value = r.data || []
}

async function machineCheck(row) {
  const r = await api.post(`/content-drafts/${row.content_draft_id}/machine-check`)
  ElMessage.info(`风险等级: ${r.data.risk_level}`)
  await load()
}

async function review(row, decision) {
  const note = decision === 'approved' ? '' : await ElMessageBox.prompt('审核意见', '审核', { inputValue: '' }).then(r => r.value).catch(() => null)
  if (note === null && decision !== 'approved') return
  try {
    const r = await api.post(`/content-drafts/${row.content_draft_id}/review`, {
      decision, review_note: note || null,
    })
    ElMessage.success(`审核完成: ${r.data.decision}`)
  } catch (e) {
    if (e.message.includes('409') || e.message.includes('CONTENT_CHANGED') || e.message.includes('修改')) {
      ElMessage.error('内容已被修改，请重新审核最新版本（409）')
    } else {
      ElMessage.error(e.message)
    }
  }
  await load()
}

onMounted(load)
</script>
