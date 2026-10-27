<script setup lang="ts">
/**
 * PAGE-F02-02 SKU 对照表：概况、判定月份、对照表列表与上传弹窗（AC-F02-03/04；DEC-021）。
 * 接口：GET /api/master/sku-mapping、POST /api/master/sku-mapping/upload、POST …/upload/{id}/confirm（API-F02-02）。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, ApiError, upload } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G1Modal from '@/components/g1/G1Modal.vue'
import { fmtTime, useToast } from '@/components/g1/useToast'
import '@/components/g1/g1.css'

interface SkuRow { sku: string; spu: string; category: string; sku_listed_on: string; spu_first_listed_on: string; new_until: string; is_new: boolean }
interface SkuPage {
  month: string; month_end: string
  summary: { sku_count: number; spu_count: number; category_count: number; last_upload: { at: string; by: string; file_name: string } | null }
  categories: string[]; new_spu_count: number; total: number; page: number; page_size: number; items: SkuRow[]; can_edit: boolean
}
interface UploadIssue { row: number; sku: string | null; message: string }
interface UploadResult { id: number; status: 'failed' | 'passed' | 'imported'; file_name: string; row_count: number; issues: UploadIssue[]; added: number; updated: number }

const loading = ref(true)
const error = ref<unknown>(null)
const data = ref<SkuPage | null>(null)
const f = reactive({ month: '', q: '', category: '', kind: '', page: 1 })
const { toast, show } = useToast()

async function load(): Promise<void> {
  error.value = null
  try {
    data.value = await api.get<SkuPage>('/api/master/sku-mapping', { month: f.month, q: f.q.trim(), category: f.category, kind: f.kind, page: f.page })
    if (!f.month) f.month = data.value.month
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

let timer: ReturnType<typeof setTimeout> | null = null
watch(() => [f.month, f.category, f.kind], (_now, old) => {
  if (old && old[0] === '') return
  f.page = 1
  void load()
})
watch(() => f.q, () => {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { f.page = 1; void load() }, 250)
})

const pages = computed(() => (data.value ? Math.max(1, Math.ceil(data.value.total / data.value.page_size)) : 1))
const range = computed(() => {
  const d = data.value
  if (!d || !d.total) return '共 0 条'
  const a = (d.page - 1) * d.page_size + 1
  return `显示第 ${a}–${a + d.items.length - 1} 条，共 ${d.total.toLocaleString('en-US')} 条`
})
function goPage(p: number): void {
  f.page = p
  void load()
}

// ---- 上传弹窗 ----
const up = ref<'closed' | 'pick' | 'checking' | 'bad' | 'ok'>('closed')
const fileName = ref('')
const result = ref<UploadResult | null>(null)
const upErr = ref('')
const confirming = ref(false)

function openUpload(): void {
  up.value = 'pick'
  result.value = null
  upErr.value = ''
}

async function onFile(ev: Event): Promise<void> {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  upErr.value = ''
  if (!file.name.toLowerCase().endsWith('.xlsx')) {
    upErr.value = '请上传 .xlsx 文件'
    return
  }
  fileName.value = file.name
  up.value = 'checking'
  const form = new FormData()
  form.append('file', file)
  try {
    result.value = await upload<UploadResult>('/api/master/sku-mapping/upload', form)
    up.value = result.value.status === 'failed' ? 'bad' : 'ok'
  } catch (e) {
    up.value = 'pick'
    upErr.value = e instanceof ApiError ? e.message : '上传失败，请重试'
  }
}

async function confirmWrite(): Promise<void> {
  if (!result.value) return
  confirming.value = true
  try {
    const r = await api.post<UploadResult>(`/api/master/sku-mapping/upload/${result.value.id}/confirm`)
    up.value = 'closed'
    show(`已写入 SKU 对照表，共 ${(r.added + r.updated).toLocaleString('en-US')} 行`)
    f.page = 1
    await load()
  } catch (e) {
    upErr.value = e instanceof ApiError ? e.message : '写入失败，请重试'
  } finally {
    confirming.value = false
  }
}

const n = (v: number) => v.toLocaleString('en-US')
</script>

<template>
  <div class="g1" data-page-id="PAGE-F02-02">
    <div class="page-head">
      <h1 class="page-title">SKU 对照表</h1>
      <button v-if="data?.can_edit && !error" type="button" class="btn btn-primary" @click="openUpload">上传对照表</button>
    </div>

    <PageState v-if="loading" state="loading" :rows="4" />
    <PageState v-else-if="error && error instanceof ApiError && error.isForbidden" state="forbidden" description="SKU 对照表由财务BP 维护。" />
    <PageState v-else-if="error" state="error" title="SKU 对照表加载失败" description="网络异常或服务暂时不可用，请重试。" @retry="load" />
    <PageState v-else-if="data && data.summary.sku_count === 0" title="还没有 SKU 对照表"
               description="上传包含 SKU、SPU 编码、品类、首次上架日期四列的 Excel 后，BI 数据才能归集到品类和新老品。">
      <template #action><button v-if="data.can_edit" type="button" class="btn" @click="openUpload">上传对照表</button><span v-else /></template>
    </PageState>

    <div v-else-if="data">
      <div class="summary meta">
        <span>当前对照表：<span class="num">{{ n(data.summary.sku_count) }}</span> 个 SKU · <span class="num">{{ n(data.summary.spu_count) }}</span> 个 SPU · {{ data.summary.category_count }} 个品类</span>
        <span v-if="data.summary.last_upload">最近上传：{{ fmtTime(data.summary.last_upload.at) }} · {{ data.summary.last_upload.by }} · {{ data.summary.last_upload.file_name }}</span>
      </div>

      <div class="card rule">
        <label for="month"><strong>判定月份</strong></label>
        <input id="month" v-model="f.month" class="input" type="month" min="2025-01" max="2028-12">
        <span class="meta">规则：该月最后一天（{{ data.month_end }}）早于「首次上架日期 + 12 个月」为新品，否则为老品</span>
      </div>

      <div class="filters">
        <input v-model="f.q" class="input" type="search" placeholder="搜索 SKU 或 SPU 编码" aria-label="搜索 SKU 或 SPU 编码">
        <select v-model="f.category" class="select" aria-label="品类">
          <option value="">全部品类</option>
          <option v-for="c in data.categories" :key="c" :value="c">{{ c }}</option>
        </select>
        <select v-model="f.kind" class="select" aria-label="新老品">
          <option value="">新品与老品</option><option value="new">只看新品</option><option value="old">只看老品</option>
        </select>
        <span class="meta" style="margin-left: auto">{{ data.month }}：新品 SPU {{ n(data.new_spu_count) }} 个 / 共 {{ n(data.summary.spu_count) }} 个</span>
      </div>

      <div class="table-wrap">
        <table class="table" aria-label="SKU 对照表与新老品判定">
          <thead>
            <tr><th>SKU</th><th>SPU 编码</th><th>品类</th><th class="num">SKU 首次上架日期</th><th class="num">SPU 首次上架日期（取最早 SKU）</th><th class="num">新品期截止（SPU 首次上架 + 12 个月）</th><th>{{ data.month }} 判定</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in data.items" :key="r.sku">
              <td class="code">{{ r.sku }}</td>
              <td class="code">{{ r.spu }}</td>
              <td>{{ r.category }}</td>
              <td class="num">{{ r.sku_listed_on }}</td>
              <td class="num">{{ r.spu_first_listed_on }}</td>
              <td class="num">{{ r.new_until }}</td>
              <td><span v-if="r.is_new" class="badge badge-new">新品</span><span v-else class="badge">老品</span></td>
            </tr>
            <tr v-if="!data.items.length">
              <td colspan="7"><div class="state" style="padding: var(--space-8)"><div class="state-title">没有符合条件的 SKU</div><p>调整筛选条件后再试。</p></div></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span>{{ range }}</span>
        <span>
          <button v-if="pages > 1" type="button" class="btn" :disabled="f.page <= 1" @click="goPage(f.page - 1)">上一页</button>
          第 {{ f.page }} / {{ pages }} 页 · 每页 50 条
          <button v-if="pages > 1" type="button" class="btn" :disabled="f.page >= pages" @click="goPage(f.page + 1)">下一页</button>
        </span>
      </div>
    </div>

    <G1Modal v-if="up !== 'closed'" title="上传 SKU 对照表" @close="up = 'closed'">
      <div v-if="up === 'pick'">
        <p>整表上传 Excel（.xlsx），按 SKU 新增或更新，文件中未出现的 SKU 保留不删除。必须包含以下四列；任一行缺字段、日期格式错误、SKU 重复、品类不在清单（{{ data?.categories.join('、') }}）或同一 SPU 下 SKU 品类不一致时，整份文件不写入：</p>
        <div class="cols"><span class="badge">SKU</span><span class="badge">SPU 编码</span><span class="badge">品类</span><span class="badge">首次上架日期（YYYY-MM-DD）</span></div>
        <label class="drop" for="sku-file">点击选择文件<input id="sku-file" type="file" accept=".xlsx" hidden @change="onFile"></label>
        <div v-if="upErr" class="field-error" role="alert">{{ upErr }}</div>
      </div>
      <div v-else-if="up === 'checking'" aria-live="polite">
        <p>正在校验 {{ fileName }} …</p>
        <div class="skeleton"></div>
      </div>
      <div v-else-if="up === 'bad' && result" role="alert">
        <div class="err-title">校验未通过，整份文件未写入（{{ n(new Set(result.issues.map((i) => i.row)).size) }} 行有问题）</div>
        <p>请在 Excel 中修正后重新上传。当前对照表保持不变。</p>
        <div class="err-list">
          <table class="table">
            <thead><tr><th class="num">行号</th><th>SKU</th><th>问题</th></tr></thead>
            <tbody>
              <tr v-for="(it, i) in result.issues" :key="i"><td class="num">{{ it.row }}</td><td class="code">{{ it.sku ?? '—' }}</td><td>{{ it.message }}</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-else-if="up === 'ok' && result">
        <div class="ok-title">校验通过：共 {{ n(result.added + result.updated) }} 行（新增 {{ n(result.added) }} 个 SKU，更新 {{ n(result.updated) }} 个 SKU）</div>
        <p>确认写入后，按 SKU 新增或更新对照表；文件中未出现的 SKU 保留不删除。各月新老品判定按新对照表重新计算。</p>
        <div v-if="upErr" class="field-error" role="alert">{{ upErr }}</div>
      </div>
      <template #actions>
        <button type="button" class="btn" @click="up = 'closed'">取消</button>
        <button v-if="up === 'bad'" type="button" class="btn" @click="openUpload">重新选择文件</button>
        <button v-if="up === 'ok'" type="button" class="btn btn-primary" :disabled="confirming" @click="confirmWrite">确认写入</button>
      </template>
    </G1Modal>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: var(--space-2); }
.summary { display: flex; gap: var(--space-6); margin-bottom: var(--space-4); }
.summary .num { font-variant-numeric: tabular-nums; color: var(--fg); font-weight: 600; }
.rule { display: flex; gap: var(--space-4); align-items: center; padding: var(--space-3) var(--space-4); margin-bottom: var(--space-3); }
.rule strong { font-size: var(--text-sm); }
.rule .meta { font-variant-numeric: tabular-nums; }
.g1 :deep(.modal) { width: 560px; }
.g1 :deep(.modal p) { margin: 0 0 var(--space-3); font-size: var(--text-sm); }
.drop { display: block; border: 1px dashed var(--border); border-radius: var(--radius-md); padding: var(--space-6); text-align: center; color: var(--muted); font-size: var(--text-sm); background: var(--surface-warm); cursor: pointer; }
.cols { display: flex; gap: var(--space-2); flex-wrap: wrap; margin: var(--space-2) 0 var(--space-3); }
.err-title { color: var(--danger); font-weight: 600; margin-bottom: var(--space-2); }
.ok-title { color: var(--success); font-weight: 600; margin-bottom: var(--space-2); }
.err-list { max-height: 200px; overflow: auto; border: 1px solid var(--border-soft); border-radius: var(--radius-md); }
.badge-new { color: var(--fg); font-weight: 600; border: 1px solid var(--border); background: var(--surface); }
</style>
