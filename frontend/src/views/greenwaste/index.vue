<template>
  <section class="page greenwaste-page">
    <header class="page-head">
      <div>
        <h2>园林废弃物处置</h2>
        <p class="page-desc">过磅单按批入账、按车归拢；空重和超载逐张退回，整批过账后才进入处置台账。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="createBatch">新建批次</button>
        <button class="btn" type="button" @click="reload">刷新批次</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in overviewCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="gw-layout">
      <section class="gw-panel">
        <h3>处置批次</h3>
        <form class="filter-bar" @submit.prevent="reload">
          <label class="filter-item">
            <span>批次/车牌/单号</span>
            <input v-model="filters.keyword" placeholder="输入关键字" />
          </label>
          <label class="filter-item">
            <span>批次状态</span>
            <select v-model="filters.status">
              <option value="">全部</option>
              <option v-for="status in batchStatuses" :key="status" :value="status">{{ status }}</option>
            </select>
          </label>
          <button class="btn" type="submit">查询</button>
          <button class="btn ghost" type="button" @click="resetFilters">重置</button>
        </form>

        <table class="data-table batch-table">
          <thead>
            <tr>
              <th>批次号</th>
              <th>状态</th>
              <th>车次</th>
              <th>单据</th>
              <th>粉碎还田(kg)</th>
              <th>外部转运(kg)</th>
              <th>合计(kg)</th>
              <th>建批时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="batch in batches" :key="batch.id" :class="{ selected: selectedId === batch.id }">
              <td>
                <button class="link" type="button" @click="selectBatch(batch.id)">{{ batch.batch_no }}</button>
              </td>
              <td><span :class="['status-badge', statusClass(batch.status)]">{{ batch.status }}</span></td>
              <td>{{ batch.summary.vehicle_count }}</td>
              <td>{{ batch.summary.ticket_count }}</td>
              <td>{{ batch.summary.modes['粉碎还田'].weight }}</td>
              <td>{{ batch.summary.modes['外部转运'].weight }}</td>
              <td>{{ batch.summary.total_weight }}</td>
              <td>{{ batch.created_at }}</td>
              <td class="row-actions">
                <button class="link" type="button" @click="selectBatch(batch.id)">明细</button>
                <button
                  v-if="batch.status === '待过账'"
                  class="link"
                  type="button"
                  :disabled="batch.summary.ticket_count === 0"
                  @click="postBatch(batch.id)"
                >整批过账</button>
                <button
                  v-if="batch.status !== '已撤下'"
                  class="link danger"
                  type="button"
                  @click="cancelBatch(batch.id)"
                >整批撤下</button>
              </td>
            </tr>
            <tr v-if="!batches.length">
              <td colspan="9" class="empty-state">暂无批次，可先新建一批待过账单</td>
            </tr>
          </tbody>
        </table>
        <footer class="page-foot">
          <span>共 {{ total }} 个批次</span>
          <span>服务端保留待过账批次，刷新或关闭页面不会留下半批台账</span>
        </footer>
      </section>

      <section v-if="selected" class="gw-panel detail-panel">
        <div class="panel-head">
          <div>
            <h3>{{ selected.batch_no }}</h3>
            <p class="page-desc">{{ selected.status }} · {{ selected.remark || '未填写批次备注' }}</p>
          </div>
          <div v-if="selected.status === '待过账'" class="batch-actions">
            <button class="btn primary" type="button" :disabled="!selected.summary.ticket_count" @click="postBatch(selected.id)">
              整批过账（{{ selected.summary.ticket_count }} 单）
            </button>
          </div>
        </div>

        <form v-if="selected.status === '待过账'" class="import-form" @submit.prevent="submitSingleTicket">
          <h4>新增一张过磅单</h4>
          <div class="form-grid">
            <label>
              <span>过磅单号 *</span>
              <input v-model="ticketForm.ticket_no" placeholder="PB-..." />
            </label>
            <label>
              <span>车牌 *</span>
              <input v-model="ticketForm.plate" placeholder="粤A12345" list="vehicle-options" @change="fillRatedLoad" />
              <datalist id="vehicle-options">
                <option v-for="vehicle in vehicles" :key="vehicle.plate" :value="vehicle.plate"></option>
              </datalist>
            </label>
            <label>
              <span>核定载重(kg) *</span>
              <input v-model="ticketForm.rated_load" type="number" min="0" step="0.01" />
            </label>
            <label>
              <span>净重(kg) *</span>
              <input v-model="ticketForm.weight" type="number" min="0" step="0.01" />
            </label>
            <label>
              <span>处置方式 *</span>
              <select v-model="ticketForm.mode">
                <option value="">请选择</option>
                <option value="粉碎还田">粉碎还田</option>
                <option value="外部转运">外部转运</option>
              </select>
            </label>
            <label>
              <span>来源绿地</span>
              <input v-model="ticketForm.origin" placeholder="如：滨河公园" />
            </label>
            <label>
              <span>过磅日期</span>
              <input v-model="ticketForm.weigh_date" type="date" />
            </label>
          </div>
          <div class="form-actions">
            <button class="btn primary" type="submit">校验并加入批次</button>
            <button class="btn ghost" type="button" @click="resetTicketForm">清空</button>
          </div>
        </form>

        <form v-if="selected.status === '待过账'" class="csv-box" @submit.prevent="submitCsv">
          <h4>批量粘贴导入</h4>
          <p class="hint">首行支持：过磅单号,车牌,核定载重,净重,处置方式,来源绿地,过磅日期。退回会标明数据行、车牌和单号。</p>
          <textarea v-model="csvContent" rows="6" :placeholder="csvTemplate"></textarea>
          <div class="form-actions">
            <button class="btn primary" type="submit">导入所选批次</button>
            <button class="btn ghost" type="button" @click="csvContent = ''">清空文本</button>
          </div>
        </form>

        <div v-if="importMessage" class="notice" :class="importRejected.length ? 'warn' : 'ok'">
          {{ importMessage }}
        </div>
        <table v-if="importRejected.length" class="data-table reject-table">
          <thead>
            <tr><th>数据行</th><th>车牌</th><th>单号</th><th>退回原因</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in importRejected" :key="`${item.row}-${item.ticket_no}-${item.reason}`">
              <td>第 {{ item.row }} 行</td>
              <td>{{ item.plate || '—' }}</td>
              <td>{{ item.ticket_no || '—' }}</td>
              <td>{{ item.reason }}</td>
            </tr>
          </tbody>
        </table>

        <div class="summary-strip">
          <span>车辆：{{ selected.summary.vehicle_count }} 车</span>
          <span>单据：{{ selected.summary.ticket_count }} 张</span>
          <span>粉碎还田：{{ selected.summary.modes['粉碎还田'].ticket_count }} 单 / {{ selected.summary.modes['粉碎还田'].weight }}kg</span>
          <span>外部转运：{{ selected.summary.modes['外部转运'].ticket_count }} 单 / {{ selected.summary.modes['外部转运'].weight }}kg</span>
          <strong>合计：{{ selected.summary.total_weight }}kg</strong>
        </div>

        <h4>过磅单明细</h4>
        <table class="data-table ticket-table">
          <thead>
            <tr>
              <th>车序</th>
              <th>过磅单号</th>
              <th>车牌</th>
              <th>净重(kg)</th>
              <th>核定载重(kg)</th>
              <th>处置方式</th>
              <th>来源绿地</th>
              <th>过磅日期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="ticket in selected.tickets" :key="ticket.id">
              <td>{{ ticket.sequence }}</td>
              <td>{{ ticket.ticket_no }}</td>
              <td>{{ ticket.plate }}</td>
              <td>{{ ticket.weight }}</td>
              <td>{{ ticket.rated_load }}</td>
              <td>{{ ticket.mode }}</td>
              <td>{{ ticket.origin }}</td>
              <td>{{ ticket.weigh_date }}</td>
            </tr>
            <tr v-if="!selected.tickets.length">
              <td colspan="8" class="empty-state">本批还没有有效过磅单</td>
            </tr>
          </tbody>
        </table>

        <h4>随车对账单（一车一行）</h4>
        <table class="data-table reconciliation-table">
          <thead>
            <tr>
              <th>车牌</th>
              <th>核定载重(kg)</th>
              <th>条数</th>
              <th>粉碎还田(kg)</th>
              <th>外部转运(kg)</th>
              <th>本车合计(kg)</th>
              <th>单号</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="vehicle in selected.reconciliation" :key="vehicle.plate">
              <td>{{ vehicle.plate }}</td>
              <td>{{ vehicle.rated_load }}</td>
              <td>{{ vehicle.ticket_count }}</td>
              <td>{{ vehicle.recycled_weight }}</td>
              <td>{{ vehicle.external_weight }}</td>
              <td>{{ vehicle.total_weight }}</td>
              <td class="ticket-nos">{{ vehicle.ticket_nos.join('、') }}</td>
            </tr>
            <tr v-if="!selected.reconciliation.length">
              <td colspan="7" class="empty-state">暂无随车对账行</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <section class="gw-panel ledger-panel">
      <div class="panel-head">
        <div>
          <h3>处置台账（仅已过账）</h3>
          <p class="page-desc">撤下批次会整体移出；粉碎还田与外部转运按列登记。</p>
        </div>
        <form class="filter-bar ledger-filters" @submit.prevent="reloadLedger">
          <label class="filter-item">
            <span>月份</span>
            <input v-model="ledgerFilters.month" placeholder="2026-09" />
          </label>
          <label class="filter-item">
            <span>车牌</span>
            <input v-model="ledgerFilters.plate" />
          </label>
          <label class="filter-item">
            <span>处置方式</span>
            <select v-model="ledgerFilters.mode">
              <option value="">全部</option>
              <option value="粉碎还田">粉碎还田</option>
              <option value="外部转运">外部转运</option>
            </select>
          </label>
          <button class="btn" type="submit">查询</button>
        </form>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>批次号</th>
            <th>过磅单号</th>
            <th>车牌</th>
            <th>来源绿地</th>
            <th>过磅日期</th>
            <th>粉碎还田(kg)</th>
            <th>外部转运(kg)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledgerItems" :key="`${row.batch_id}-${row.id}`">
            <td>{{ row.batch_no }}</td>
            <td>{{ row.ticket_no }}</td>
            <td>{{ row.plate }}</td>
            <td>{{ row.origin }}</td>
            <td>{{ row.weigh_date }}</td>
            <td>{{ row.mode === '粉碎还田' ? row.weight : '' }}</td>
            <td>{{ row.mode === '外部转运' ? row.weight : '' }}</td>
          </tr>
          <tr v-if="!ledgerItems.length">
            <td colspan="7" class="empty-state">当前筛选下没有已过账台账记录</td>
          </tr>
        </tbody>
      </table>
      <footer class="ledger-summary">
        <span>共 {{ ledgerSummary.ticket_count }} 单</span>
        <span>{{ ledgerSummary.vehicle_count }} 车</span>
        <span>粉碎还田：{{ ledgerSummary.modes['粉碎还田'].weight }}kg</span>
        <span>外部转运：{{ ledgerSummary.modes['外部转运'].weight }}kg</span>
        <strong>合计：{{ ledgerSummary.total_weight }}kg</strong>
      </footer>
    </section>

    <footer class="page-foot">
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else>同一单号重复导入只认第一次；正式口径随整批动作原子切换。</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Mode = '粉碎还田' | '外部转运'
type BatchStatus = '待过账' | '已过账' | '已撤下'

interface ModeSummary {
  ticket_count: number
  weight: number
}

interface BatchSummary {
  ticket_count: number
  vehicle_count: number
  total_weight: number
  modes: Record<Mode, ModeSummary>
}

interface Ticket {
  id: number
  ticket_no: string
  plate: string
  sequence: number
  weight: number
  rated_load: number
  mode: Mode
  origin: string
  weigh_date: string
}

interface ReconciliationRow {
  plate: string
  rated_load: number
  ticket_count: number
  recycled_weight: number
  external_weight: number
  total_weight: number
  ticket_nos: string[]
}

interface Batch {
  id: number
  batch_no: string
  status: BatchStatus
  remark: string
  created_at: string
  posted_at: string | null
  cancelled_at: string | null
  summary: BatchSummary
  tickets: Ticket[]
  reconciliation: ReconciliationRow[]
}

interface RejectedTicket {
  row: number
  plate: string
  ticket_no: string
  reason: string
}

interface Vehicle {
  plate: string
  rated_load: number
}

interface LedgerRow extends Ticket {
  batch_id: number
  batch_no: string
}

interface LedgerPayload {
  items: LedgerRow[]
  summary: BatchSummary
}

const batchStatuses: BatchStatus[] = ['待过账', '已过账', '已撤下']
const csvTemplate = '过磅单号,车牌,核定载重,净重,处置方式,来源绿地,过磅日期\nPB-20260916-001,粤A12345,5000,3000,粉碎还田,滨河公园,2026-09-16'

const batches = ref<Batch[]>([])
const total = ref(0)
const selected = ref<Batch | null>(null)
const selectedId = ref<number | null>(null)
const vehicles = ref<Vehicle[]>([])
const errorMessage = ref('')
const importMessage = ref('')
const csvContent = ref('')
const importRejected = ref<RejectedTicket[]>([])
const filters = reactive({ keyword: '', status: '' })
const ledgerFilters = reactive({ month: '', plate: '', mode: '' })
const ledgerItems = ref<LedgerRow[]>([])
const ledgerSummary = ref<BatchSummary>({
  ticket_count: 0,
  vehicle_count: 0,
  total_weight: 0,
  modes: { 粉碎还田: { ticket_count: 0, weight: 0 }, 外部转运: { ticket_count: 0, weight: 0 } },
})

const ticketForm = reactive({
  ticket_no: '',
  plate: '',
  rated_load: '',
  weight: '',
  mode: '',
  origin: '',
  weigh_date: '',
})

const overviewCards = computed(() => {
  const draft = batches.value.filter((item) => item.status === '待过账')
  const posted = batches.value.filter((item) => item.status === '已过账')
  return [
    { label: '待过账批次', value: draft.length },
    { label: '待过账单据', value: draft.reduce((sum, item) => sum + item.summary.ticket_count, 0) },
    { label: '已过账批次', value: posted.length },
    { label: '本月台账车辆', value: ledgerSummary.value.vehicle_count },
    { label: '本月台账合计(kg)', value: ledgerSummary.value.total_weight },
  ]
})

function resetTicketForm() {
  Object.assign(ticketForm, {
    ticket_no: '',
    plate: '',
    rated_load: '',
    weight: '',
    mode: '',
    origin: '',
    weigh_date: '',
  })
}

function fillRatedLoad() {
  const vehicle = vehicles.value.find((item) => item.plate === ticketForm.plate.trim())
  if (vehicle && !ticketForm.rated_load) {
    ticketForm.rated_load = String(vehicle.rated_load)
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  void reload()
}

function statusClass(status: BatchStatus) {
  return {
    'status-draft': status === '待过账',
    'status-posted': status === '已过账',
    'status-cancelled': status === '已撤下',
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init)
  const payload = await response.json().catch(() => ({})) as { detail?: string }
  if (!response.ok) {
    throw new Error(payload.detail || `接口返回 ${response.status}`)
  }
  return payload as T
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  query.set('size', '100')
  try {
    const payload = await requestJson<{ items: Batch[]; total: number }>(`/api/greenwaste?${query.toString()}`)
    batches.value = payload.items
    total.value = payload.total
    if (selectedId.value) {
      const current = batches.value.find((item) => item.id === selectedId.value)
      selected.value = current ?? null
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批次读取失败'
  }
}

async function reloadVehicles() {
  const payload = await requestJson<{ items: Vehicle[] }>('/api/greenwaste/vehicles')
  vehicles.value = payload.items
}

async function reloadLedger() {
  const query = new URLSearchParams()
  if (ledgerFilters.month) query.set('month', ledgerFilters.month)
  if (ledgerFilters.plate) query.set('plate', ledgerFilters.plate)
  if (ledgerFilters.mode) query.set('mode', ledgerFilters.mode)
  const payload = await requestJson<LedgerPayload>(`/api/greenwaste/ledger?${query.toString()}`)
  ledgerItems.value = payload.items
  ledgerSummary.value = payload.summary
}

async function selectBatch(id: number) {
  selectedId.value = id
  importMessage.value = ''
  importRejected.value = []
  try {
    selected.value = await requestJson<Batch>(`/api/greenwaste/batches/${id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批次明细读取失败'
    selected.value = null
  }
}

async function createBatch() {
  errorMessage.value = ''
  try {
    const payload = await requestJson<{ ok: boolean; message: string; entry: Batch | null }>('/api/greenwaste/batches', {
      method: 'POST',
      body: JSON.stringify({}),
    })
    if (!payload.ok || !payload.entry) {
      throw new Error(payload.message)
    }
    await reload()
    await selectBatch(payload.entry.id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '建批失败'
  }
}

async function importToSelected(tickets: Record<string, unknown>[], content = '') {
  if (!selected.value) {
    errorMessage.value = '请先选择一个待过账批次'
    return
  }
  errorMessage.value = ''
  importMessage.value = ''
  importRejected.value = []
  try {
    const payload = await requestJson<{
      message: string
      rejected: RejectedTicket[]
      batch: Batch
    }>(`/api/greenwaste/batches/${selected.value.id}/tickets/import`, {
      method: 'POST',
      body: JSON.stringify({ tickets, content }),
    })
    importMessage.value = payload.message
    importRejected.value = payload.rejected
    selected.value = payload.batch
    await reload()
    await reloadLedger()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '过磅单导入失败'
  }
}

async function submitSingleTicket() {
  if (!ticketForm.weigh_date) {
    ticketForm.weigh_date = new Date().toISOString().slice(0, 10)
  }
  await importToSelected([{ ...ticketForm }])
  if (!importRejected.value.length) resetTicketForm()
}

function submitCsv() {
  if (!csvContent.value.trim()) {
    errorMessage.value = '请先粘贴要导入的 CSV 内容'
    return
  }
  void importToSelected([], csvContent.value)
}

async function runBatchAction(id: number, action: 'post' | 'cancel', confirmText: string) {
  if (!window.confirm(confirmText)) return
  errorMessage.value = ''
  try {
    const payload = await requestJson<{ ok: boolean; message: string; entry: Batch | null }>(
      `/api/greenwaste/batches/${id}/actions`,
      { method: 'POST', body: JSON.stringify({ action }) },
    )
    if (!payload.ok || !payload.entry) throw new Error(payload.message)
    selected.value = payload.entry
    await reload()
    await reloadLedger()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批次动作失败'
  }
}

function postBatch(id: number) {
  void runBatchAction(id, 'post', '确认将本批所有过磅单整批过账？合计将进入处置台账。')
}

function cancelBatch(id: number) {
  void runBatchAction(id, 'cancel', '确认整批撤下？已过账批次会整体从处置台账剔除。')
}

onMounted(async () => {
  await reloadVehicles()
  await reload()
  const first = batches.value[0]
  if (first) await selectBatch(first.id)
  await reloadLedger()
})
</script>
