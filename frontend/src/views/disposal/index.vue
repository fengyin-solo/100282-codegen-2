<template>
  <section class="page" data-module="disposal">
    <header class="page-head">
      <div>
        <h2>绿化废弃物处置</h2>
        <p class="page-desc">每次过磅一张过磅单，按车牌归拢同一车多张单；同一批单重复导入只认第一次，空重量或超载单张退回；整批过账、整批撤下，中途关页面再进来可领回草稿。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="busy" @click="ensureDraft">开启 / 领回批次</button>
        <button class="btn" type="button" :disabled="busy" @click="loadLedger">刷新处置台账</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">本批过磅单</span>
        <strong class="stat-value">{{ currentDetail?.summary['合计']['条数'] ?? 0 }} 张</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">本批合计净重</span>
        <strong class="stat-value">{{ fmtKg(currentDetail?.summary['合计']['重量kg']) }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">粉碎还田</span>
        <strong class="stat-value">{{ fmtKg(currentDetail?.summary['分栏']['粉碎还田']['重量kg']) }}（{{ currentDetail?.summary['分栏']['粉碎还田']['条数'] ?? 0 }}张）</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">外部转运</span>
        <strong class="stat-value">{{ fmtKg(currentDetail?.summary['分栏']['外部转运']['重量kg']) }}（{{ currentDetail?.summary['分栏']['外部转运']['条数'] ?? 0 }}张）</strong>
      </article>
    </div>

    <p v-if="message" :class="['banner', messageOk ? 'ok' : 'error-text']">{{ message }}</p>

    <!-- 当前批次与流转 -->
    <div class="panel">
      <div class="panel-head">
        <h3>当前批次
          <span :class="['badge', badgeClass(currentBatch?.['状态'])]">{{ currentBatch?.['状态'] ?? '无' }}</span>
          <span class="muted">{{ currentBatch?.['批次号'] ?? '尚未开启批次' }}</span>
        </h3>
        <div v-if="currentBatch" class="panel-actions">
          <button class="btn primary" type="button" :disabled="busy || currentBatch['状态'] !== '草稿'" @click="postBatch">整批过账</button>
          <button class="btn danger" type="button" :disabled="busy" @click="withdrawBatch">整批撤下</button>
          <button class="btn" type="button" :disabled="busy" @click="openStatement">随车对账单（一车一行）</button>
        </div>
      </div>
      <p v-if="currentBatch" class="muted small">
        创建：{{ currentBatch['创建时间'] }} ｜ 过账：{{ currentBatch['过账时间'] ?? '—' }} ｜ 撤下：{{ currentBatch['撤下时间'] ?? '—' }}
      </p>
    </div>

    <!-- 导入磅单 -->
    <div v-if="currentBatch && currentBatch['状态'] === '草稿'" class="panel">
      <div class="panel-head"><h3>导入磅单（同一批单重复导入只认第一次）</h3></div>
      <textarea
        v-model="rawText"
        class="paste-box"
        rows="7"
        placeholder="粘贴磅单文本，制表符或逗号分隔，首行可带表头。列序：磅单号 车牌号 毛重kg 皮重kg 处置方式(粉碎还田/外部转运) 过磅时间&#10;示例：&#10;WD-2001	沪A·D3126	2500	400	粉碎还田	2026-09-30 08:10"
      ></textarea>
      <div class="panel-actions">
        <button class="btn primary" type="button" :disabled="busy" @click="importTickets">按批导入</button>
        <button class="btn ghost" type="button" @click="rawText = ''">清空文本</button>
        <span class="muted small">空重量、净重超核定载重、车牌未登记、处置方式不对的单张退回，其余照认。</span>
      </div>

      <div v-if="rejected.length" class="sub-block">
        <h4 class="reject-title">退回 {{ rejected.length }} 张（写明了是哪一车哪一条）</h4>
        <table class="data-table">
          <thead><tr><th>位置</th><th>车牌号</th><th>磅单号</th><th>退回原因</th></tr></thead>
          <tbody>
            <tr v-for="(item, idx) in rejected" :key="`r-${idx}`" class="row-reject">
              <td>{{ item['位置'] }}</td><td>{{ item['车牌号'] }}</td><td>{{ item['磅单号'] }}</td><td>{{ item['退回原因'] }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="duplicated.length" class="sub-block">
        <h4 class="dup-title">重复跳过 {{ duplicated.length }} 张（只认第一次的过磅单）</h4>
        <table class="data-table">
          <thead><tr><th>位置</th><th>车牌号</th><th>磅单号</th><th>说明</th></tr></thead>
          <tbody>
            <tr v-for="(item, idx) in duplicated" :key="`d-${idx}`" class="row-dup">
              <td>{{ item['位置'] }}</td><td>{{ item['车牌号'] }}</td><td>{{ item['磅单号'] }}</td><td>{{ item['重复原因'] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 本批过磅单 -->
    <div class="panel">
      <div class="panel-head"><h3>本批过磅单（{{ currentDetail?.tickets.length ?? 0 }} 张）</h3></div>
      <table class="data-table">
        <thead>
          <tr><th>磅单号</th><th>车牌号</th><th>毛重kg</th><th>皮重kg</th><th>净重kg</th><th>处置方式</th><th>过磅时间</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in currentDetail?.tickets ?? []" :key="t.id">
            <td>{{ t['磅单号'] }}</td><td>{{ t['车牌号'] }}</td>
            <td>{{ t['毛重kg'] }}</td><td>{{ t['皮重kg'] }}</td>
            <td><strong>{{ t['净重kg'] }}</strong></td>
            <td><span :class="['tag', t['处置方式'] === '粉碎还田' ? 'tag-plow' : 'tag-transfer']">{{ t['处置方式'] }}</span></td>
            <td>{{ t['过磅时间'] }}</td><td>{{ t['状态'] }}</td>
          </tr>
          <tr v-if="!(currentDetail?.tickets.length)"><td colspan="8" class="empty-state">本批还没有过磅单</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 按车归拢 -->
    <div class="panel">
      <div class="panel-head"><h3>按车归拢（一车一行，与随车对账单同一份数据）</h3></div>
      <table class="data-table">
        <thead>
          <tr>
            <th>车牌号</th><th>车辆单位</th><th>核定载重kg</th><th>条数</th>
            <th class="col-plow">粉碎还田(张/kg)</th><th class="col-transfer">外部转运(张/kg)</th>
            <th>总净重kg</th><th>磅单号</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="g in currentDetail?.groups ?? []" :key="g['车牌号']">
            <td>{{ g['车牌号'] }}</td><td>{{ g['车辆单位'] }}</td><td>{{ g['核定载重kg'] }}</td>
            <td><strong>{{ g['条数'] }}</strong></td>
            <td class="col-plow">{{ g['粉碎还田']['条数'] }} / {{ g['粉碎还田']['重量kg'] }}</td>
            <td class="col-transfer">{{ g['外部转运']['条数'] }} / {{ g['外部转运']['重量kg'] }}</td>
            <td>{{ g['总净重kg'] }}</td>
            <td class="muted small">{{ g['磅单号列表'].join('、') }}</td>
          </tr>
          <tr v-if="!(currentDetail?.groups?.length)"><td colspan="8" class="empty-state">暂无按车归拢结果</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 处置汇总：随过磅单重算 -->
    <div class="panel">
      <div class="panel-head"><h3>处置汇总（已过账，合计随过磅单一起重算）</h3></div>
      <table class="data-table sum-table">
        <thead><tr><th>处置方式</th><th>过磅单条数</th><th>合计重量kg</th></tr></thead>
        <tbody>
          <tr><td class="col-plow">粉碎还田</td><td>{{ ledgerSummary['分栏']?.['粉碎还田']?.['条数'] ?? 0 }}</td><td>{{ fmtKg(ledgerSummary['分栏']?.['粉碎还田']?.['重量kg']) }}</td></tr>
          <tr><td class="col-transfer">外部转运</td><td>{{ ledgerSummary['分栏']?.['外部转运']?.['条数'] ?? 0 }}</td><td>{{ fmtKg(ledgerSummary['分栏']?.['外部转运']?.['重量kg']) }}</td></tr>
          <tr class="sum-total"><td>合计（{{ ledgerSummary['批次数'] ?? 0 }} 个已过账批次）</td><td>{{ ledgerSummary['合计']?.['条数'] ?? 0 }}</td><td>{{ fmtKg(ledgerSummary['合计']?.['重量kg']) }}</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 处置台账 -->
    <div class="panel">
      <div class="panel-head"><h3>处置台账（磅单即台账，撤下批次自动退出）</h3></div>
      <table class="data-table">
        <thead>
          <tr><th>磅单号</th><th>批次号</th><th>车牌号</th><th>净重kg</th><th>处置方式</th><th>过账时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in ledger" :key="t.id">
            <td>{{ t['磅单号'] }}</td><td>{{ t['批次号'] }}</td><td>{{ t['车牌号'] }}</td>
            <td>{{ t['净重kg'] }}</td><td>{{ t['处置方式'] }}</td><td>{{ t['过账时间'] }}</td>
          </tr>
          <tr v-if="!ledger.length"><td colspan="6" class="empty-state">暂无已过账记录</td></tr>
        </tbody>
      </table>
    </div>

    <!-- 批次痕迹 -->
    <div class="panel">
      <div class="panel-head"><h3>批次记录</h3></div>
      <table class="data-table">
        <thead><tr><th>批次号</th><th>状态</th><th>条数</th><th>合计重量kg</th><th>创建时间</th><th>过账时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="b in batches" :key="b.id">
            <td>{{ b['批次号'] }}</td>
            <td><span :class="['badge', badgeClass(b['状态'])]">{{ b['状态'] }}</span></td>
            <td>{{ b['票据条数'] }}</td><td>{{ b['合计重量kg'] ?? '—' }}</td>
            <td>{{ b['创建时间'] }}</td><td>{{ b['过账时间'] ?? '—' }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="loadBatch(b.id)">查看</button>
              <button class="link" type="button" :disabled="b['状态'] === '已撤下'" @click="loadStatement(b.id)">对账单</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 随车对账单弹层 -->
    <div v-if="statement" class="modal-mask" @click.self="statement = null">
      <div class="modal">
        <div class="panel-head">
          <h3>随车对账单｜{{ statement['批次号'] }}（{{ statement['状态'] }}）</h3>
          <div class="panel-actions">
            <button class="btn" type="button" @click="printStatement">打印</button>
            <button class="btn ghost" type="button" @click="statement = null">关闭</button>
          </div>
        </div>
        <p class="muted small">一车一行；本单 {{ statement['车辆行数'] }} 行、{{ statement['summary']['合计']['条数'] }} 条，与页面按车归拢完全一致。生成时间：{{ statement['生成时间'] }}</p>
        <table class="data-table" id="statement-table">
          <thead>
            <tr><th>序号</th><th>车牌号</th><th>车辆单位</th><th>条数</th><th class="col-plow">粉碎还田kg</th><th class="col-transfer">外部转运kg</th><th>总净重kg</th><th>磅单号</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in statement.rows" :key="r['车牌号']">
              <td>{{ idx + 1 }}</td><td>{{ r['车牌号'] }}</td><td>{{ r['车辆单位'] }}</td><td>{{ r['条数'] }}</td>
              <td class="col-plow">{{ r['粉碎还田']['重量kg'] }}（{{ r['粉碎还田']['条数'] }}张）</td>
              <td class="col-transfer">{{ r['外部转运']['重量kg'] }}（{{ r['外部转运']['条数'] }}张）</td>
              <td><strong>{{ r['总净重kg'] }}</strong></td>
              <td class="small">{{ r['磅单号列表'].join('、') }}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr class="sum-total">
              <td colspan="3">合计（{{ statement['车辆行数'] }} 车 / {{ statement['summary']['合计']['条数'] }} 条）</td>
              <td>{{ statement['summary']['合计']['条数'] }}</td>
              <td class="col-plow">{{ statement['summary']['分栏']['粉碎还田']['重量kg'] }}</td>
              <td class="col-transfer">{{ statement['summary']['分栏']['外部转运']['重量kg'] }}</td>
              <td>{{ statement['summary']['合计']['重量kg'] }}</td>
              <td></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Bucket = { 条数: number; '重量kg': number }
type Summary = {
  分栏: { 粉碎还田: Bucket; 外部转运: Bucket }
  合计: { 条数: number; '重量kg': number }
  批次数?: number
}
type Ticket = {
  id: number
  磅单号: string
  车牌号: string
  '毛重kg': number
  '皮重kg': number
  '净重kg': number
  处置方式: string
  过磅时间: string
  状态: string
  批次号?: string
  过账时间?: string
}
type VehicleGroup = {
  车牌号: string
  车辆单位: string
  '核定载重kg': number | null
  条数: number
  '总净重kg': number
  粉碎还田: Bucket
  外部转运: Bucket
  磅单号列表: string[]
}
type BatchDetail = {
  batch: Record<string, string | number | null>
  tickets: Ticket[]
  groups: VehicleGroup[]
  summary: Summary
}
type BatchRow = Record<string, string | number | null> & { id: number; 票据条数: number }
type RejectRow = { 位置: string; 车牌号: string; 磅单号: string; 退回原因?: string; 重复原因?: string }
type Statement = {
  批次号: string
  状态: string
  生成时间: string
  车辆行数: number
  rows: VehicleGroup[]
  summary: Summary
}

const ENDPOINT = '/api/disposal'

const busy = ref(false)
const message = ref('')
const messageOk = ref(true)
const rawText = ref('')

const currentDetail = ref<BatchDetail | null>(null)
const batches = ref<BatchRow[]>([])
const rejected = ref<RejectRow[]>([])
const duplicated = ref<RejectRow[]>([])
const ledger = ref<Ticket[]>([])
const ledgerSummary = ref<Partial<Summary>>({})
const statement = ref<Statement | null>(null)

const currentBatch = computed(() => currentDetail.value?.batch as BatchRow | undefined)

function fmtKg(value: number | null | undefined): string {
  if (value === null || value === undefined) return '0 kg'
  return `${Number(value).toLocaleString()} kg`
}

function badgeClass(status: string | number | null | undefined): string {
  const text = String(status ?? '')
  if (text === '已过账') return 'badge-posted'
  if (text === '已撤下') return 'badge-withdrawn'
  return 'badge-draft'
}

function notify(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const response = await request(`${ENDPOINT}${path}`, {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
  })
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，操作未生效`)
  }
  return (await response.json()) as T
}

async function getJson<T>(path: string): Promise<T> {
  const response = await request(`${ENDPOINT}${path}`)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

type BatchActionResponse = { ok: boolean; message: string; detail: BatchDetail | null }
type ImportResponse = BatchActionResponse & { rejected: RejectRow[]; duplicated: RejectRow[] }

async function loadBatchList() {
  const payload = await getJson<{ items: BatchRow[] }>('/batches')
  batches.value = payload.items
}

async function loadBatch(batchId: number) {
  const payload = await getJson<BatchActionResponse>(`/batches/${batchId}`)
  currentDetail.value = payload.detail
}

async function loadLedger() {
  const [list, sum] = await Promise.all([
    getJson<{ total: number; items: Ticket[] }>('/ledger'),
    getJson<Summary>('/summary'),
  ])
  ledger.value = list.items
  ledgerSummary.value = sum
}

async function refreshAll(activeId?: number) {
  await Promise.all([loadBatchList(), loadLedger()])
  const batchId = activeId ?? Number(currentDetail.value?.batch.id ?? batches.value.find((b) => b['状态'] === '草稿')?.id)
  if (batchId) {
    await loadBatch(batchId)
  } else {
    currentDetail.value = null
  }
}

async function ensureDraft() {
  busy.value = true
  try {
    const payload = await post<BatchActionResponse>('/batches/open')
    notify(payload.message, true)
    await refreshAll(Number(payload.detail?.batch.id))
  } catch (error) {
    notify(error instanceof Error ? error.message : '开启批次失败', false)
  } finally {
    busy.value = false
  }
}

async function importTickets() {
  if (!rawText.value.trim() || !currentBatch.value) return
  busy.value = true
  rejected.value = []
  duplicated.value = []
  try {
    const payload = await post<ImportResponse>(`/batches/${currentBatch.value.id}/import`, {
      raw_text: rawText.value,
    })
    rejected.value = payload.rejected
    duplicated.value = payload.duplicated
    if (payload.detail) currentDetail.value = payload.detail
    notify(payload.message, payload.ok)
    await Promise.all([loadBatchList(), loadLedger()])
  } catch (error) {
    notify(error instanceof Error ? error.message : '磅单导入失败', false)
  } finally {
    busy.value = false
  }
}

async function postBatch() {
  if (!currentBatch.value) return
  if (!window.confirm('整批过账后处置台账与汇总将按这批过磅单重算，确认过账？')) return
  busy.value = true
  try {
    const payload = await post<BatchActionResponse>(`/batches/${currentBatch.value.id}/post`)
    notify(payload.message, payload.ok)
    if (!payload.ok) throw new Error(payload.message)
    await refreshAll(payload.detail ? Number(payload.detail.batch.id) : undefined)
  } catch (error) {
    notify(error instanceof Error ? error.message : '过账失败', false)
  } finally {
    busy.value = false
  }
}

async function withdrawBatch() {
  if (!currentBatch.value) return
  const draft = currentBatch.value['状态'] === '草稿'
  if (!window.confirm(draft
    ? '整批撤下会丢弃当前草稿及其全部过磅单（不留半批），确认撤下？'
    : '整批撤下后这批过磅单将全部退出处置台账、汇总同步重算，确认撤下？')) return
  busy.value = true
  try {
    const payload = await post<BatchActionResponse>(`/batches/${currentBatch.value.id}/withdraw`)
    notify(payload.message, payload.ok)
    if (!payload.ok) throw new Error(payload.message)
    currentDetail.value = null
    await refreshAll()
  } catch (error) {
    notify(error instanceof Error ? error.message : '撤下失败', false)
  } finally {
    busy.value = false
  }
}

async function loadStatement(batchId: number) {
  statement.value = await getJson<Statement>(`/batches/${batchId}/statement`)
}

async function openStatement() {
  if (!currentBatch.value) return
  await loadStatement(Number(currentBatch.value.id))
}

function printStatement() {
  if (!statement.value) return
  const table = document.getElementById('statement-table')?.outerHTML ?? ''
  const win = window.open('', '_blank')
  if (!win) {
    notify('浏览器拦截了打印窗口，请允许弹窗后重试', false)
    return
  }
  win.document.write(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>随车对账单-${statement.value['批次号']}</title>
  <style>
    body{font-family:'PingFang SC','Microsoft YaHei',sans-serif;padding:24px;color:#1f2937}
    h2{margin:0 0 4px} .muted{color:#64748b;font-size:12px;margin:4px 0 12px}
    table{width:100%;border-collapse:collapse} th,td{border:1px solid #94a3b8;padding:6px 8px;font-size:13px;text-align:left}
    tfoot td{font-weight:700;background:#f1f5f9}
  </style></head><body>
  <h2>绿化废弃物随车对账单</h2>
  <div class="muted">批次：${statement.value['批次号']}（${statement.value['状态']}）｜一车一行，共 ${statement.value['车辆行数']} 行 / ${statement.value['summary']['合计']['条数']} 条｜生成时间：${statement.value['生成时间']}</div>
  ${table.replace(/<tfoot>[\s\S]*?<\/tfoot>/, '')}
  </body></html>`)
  win.document.close()
  win.focus()
  win.print()
}

onMounted(async () => {
  // 中途关页面再进来：直接领回未过账草稿，不会留下半批
  try {
    await Promise.all([loadBatchList(), loadLedger()])
    const payload = await post<BatchActionResponse>('/batches/open')
    if (payload.detail) currentDetail.value = payload.detail
    notify(payload.message)
  } catch (error) {
    notify(error instanceof Error ? error.message : '处置数据加载失败', false)
  }
})
</script>
