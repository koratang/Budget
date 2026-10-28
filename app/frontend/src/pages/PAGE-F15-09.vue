<script setup lang="ts">
/**
 * 业财数据管理 PAGE-F15-09：由原工作台 viewData + bindData 移植。
 * 导入（粘贴表格 / 选择或拖入 CSV）→ 引擎 importTable → 保存「指标」「维度填报」两部分并去掉示例数据标记；
 * 导出 CSV、下载导入模板、清空当月手工覆盖、维度切换与原工具一致。
 * 与原工具的差异：数据保存在服务器（不再是浏览器 localStorage），显示各部分最后保存人与时间；
 * 「恢复示例数据」仅财务负责人可见，会清空服务器上已保存的全部业财数据；原用户 / 权限面板不移植（由平台账号体系承担）。
 */
import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import BizfinPage from '@/components/g5/BizfinPage.vue'
import { fmtTime, useToast } from '@/components/g1/useToast'
import {
  BIZ_DIMS, CATEGORIES, CHANNELS, COMPANY, DEPTS, DIM_HEADER, IND_HEADER, LINKAGE, MARKETS, MONTHS9, MONTH_HEADER, NAV, S,
  bizDimFilled, byKind, clearAllMonthlyOverrides, dimRowsOf, importMessage, importTable, l1, l2, monthlyRowsOf,
  periodLabel, recompute, rowsOf, stamp, toCSV, validations, type CsvCell, type DimMode,
} from '@/bizfin/engine'
import { SECTION_KEYS, SECTION_LABELS, commit, resetDemo, store } from '@/bizfin/persist'

const desc = NAV.find((n) => n.id === 'data')?.sub
const { toast, show } = useToast()

/* ---------- 统计 ---------- */
const stats = computed(() => {
  const fin = byKind('fin'), biz = byKind('biz')
  /* 维度填报进度统计（同原工具：按指标 × 声明维度累计） */
  let dimTotalN = 0, dimFilledN = 0
  l2('biz').forEach((i) => {
    (i.dims || []).forEach((dk) => {
      const D = BIZ_DIMS[dk]
      if (!D) return
      dimTotalN += D.members.length
      dimFilledN += bizDimFilled(i.code)
    })
  })
  const ovCount = S.IND.filter((i) => (i._ova && Object.keys(i._ova).length) || (i._ovt && Object.keys(i._ovt).length)).length
  return {
    fin: fin.length, finL1: l1('fin').length, finL2: l2('fin').length,
    biz: biz.length, bizL1: l1('biz').length, bizL2: l2('biz').length,
    dimTotalN, dimFilledN, ovCount,
  }
})
const checks = computed(() => validations())
const saveMeta = computed(() => SECTION_KEYS.map((k) => ({ key: k, label: SECTION_LABELS[k], ...store.meta[k] })))

/* ---------- 下载 ---------- */
function download(filename: string, text: string): void {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}
const ofKind = (k: 'fin' | 'biz') => S.IND.filter((i) => i.kind === k)

function tplYear(): void {
  const sample: CsvCell[][] = S.IND.slice(0, 6).map((i) => [i.code, i.name, (i.kind === 'fin' ? '财务' : '业务'), (i.level === 1 ? '一级' : '二级'),
    i.unit, (i.dir === 1 ? '正向' : '逆向'), i.target, i.actual, i.weight, i.depts.join('/'), i.note || ''])
  download('业财指标导入模板_年度口径.csv', toCSV(IND_HEADER, sample))
  show('模板已下载：仅含 6 行示例，可按同格式补充后导入')
}
function tplMonth(): void {
  download('业财指标导入模板_月度口径.csv', toCSV(MONTH_HEADER, monthlyRowsOf(S.IND.slice(0, 3))))
  show('月度模板已下载：含「月份」列，每行代表一个指标某个月的目标值与实际值')
}
function tplDim(): void {
  download('业务指标导入模板_维度口径.csv', toCSV(DIM_HEADER, dimRowsOf(ofKind('biz'))))
  show('维度模板已下载：每行代表一个「指标 × 维度成员」的目标值与实际值')
}

interface ExportBtn { label: string; primary?: boolean; run: () => void }
const yearExports: ExportBtn[] = [
  { label: '导出全部指标（CSV）', primary: true, run: () => { download('业财指标_年度口径_全部_' + stamp() + '.csv', toCSV(IND_HEADER, rowsOf(S.IND))); show('已导出全部指标（年度口径）') } },
  { label: '导出财务指标', run: () => { download('财务指标_年度口径_' + stamp() + '.csv', toCSV(IND_HEADER, rowsOf(ofKind('fin')))); show('已导出财务指标（年度口径）') } },
  { label: '导出业务指标', run: () => { download('业务指标_年度口径_' + stamp() + '.csv', toCSV(IND_HEADER, rowsOf(ofKind('biz')))); show('已导出业务指标（年度口径）') } },
  { label: '导出业财关联关系', run: () => {
    const h = ['业务指标编码', '业务指标', '财务指标编码', '财务指标', '影响方向', '关联强度', '关联程度', '传导逻辑', '责任部门', '量化影响']
    const rows: CsvCell[][] = LINKAGE.map((l) => [l.biz, l.bizName, l.fin, l.finName, l.dir, l.strength, l.coef, l.logic, l.dept, l.impact])
    download('业财关联关系_' + stamp() + '.csv', toCSV(h, rows))
    show('已导出业财关联关系')
  } },
  { label: '导出维度填报明细', run: () => {
    const rows = dimRowsOf(ofKind('biz'))
    download('业务指标_维度填报明细_' + stamp() + '.csv', toCSV(DIM_HEADER, rows))
    show('已导出维度填报明细（' + rows.length + ' 行）')
  } },
]
const monthExports: ExportBtn[] = [
  { label: '导出月度明细（全部指标）', primary: true, run: () => { download('业财指标_月度明细_全部_' + stamp() + '.csv', toCSV(MONTH_HEADER, monthlyRowsOf(S.IND))); show('已导出月度明细（' + (S.IND.length * 9) + ' 行）') } },
  { label: '导出月度明细（财务）', run: () => { download('财务指标_月度明细_' + stamp() + '.csv', toCSV(MONTH_HEADER, monthlyRowsOf(ofKind('fin')))); show('已导出财务指标月度明细') } },
  { label: '导出月度明细（业务）', run: () => { download('业务指标_月度明细_' + stamp() + '.csv', toCSV(MONTH_HEADER, monthlyRowsOf(ofKind('biz')))); show('已导出业务指标月度明细') } },
  { label: '导出政策影响清单', run: () => {
    const rows: CsvCell[][] = S.POLICY_EVENTS.map((e) => [e.time, e.seg, e.desc, e.impact])
    download('政策环境事件台账_' + stamp() + '.csv', toCSV(['时间', '业务板块', '事件描述', '事件影响'], rows))
    show('已导出政策环境事件台账')
  } },
  { label: '导出重点工作台账', run: () => {
    const rows: CsvCell[][] = S.KW_TASKS.map((e) => [e.time, e.cat, e.goal, e.breakdown, e.eta, e.progress, e.status])
    download('重点工作台账_' + stamp() + '.csv', toCSV(['时间', '工作分类', '工作目标', '工作分解', '预计完成时间', '目前进度', '工作状态'], rows))
    show('已导出重点工作台账（' + rows.length + ' 行）')
  } },
]

/* ---------- 导入 ---------- */
const paste = ref('')
const over = ref(false)
const PASTE_HINT = '编码\t目标值\t实际值\nF1\t12000\t10500\nS1.10\t12\t10.5\n\n分维度填报（业务指标）：\n编码\t维度\t目标值\t实际值\nS1.1\tAmazon\t150\t138\nS1.1\t独立站\t90\t96\n\n带月份列的月度填报：\n编码\t月份\t目标值\t实际值\nF1\t2026年9月\t1008\t1180\nF1\t2026年8月\t1104\t1090'

/** 导入一段表格文本：成功后保存指标与维度填报两部分，并去掉「示例数据」标记 */
function runImport(text: string): boolean {
  if (!store.canEdit) return false
  try {
    const res = importTable(text)
    commit(['indicators', 'biz_dim'], true)
    show(importMessage(res))
    return true
  } catch (e) {
    show(e instanceof Error ? e.message : String(e))
    return false
  }
}
function importPaste(): void {
  if (!paste.value.trim()) { show('请先粘贴需要导入的表格数据'); return }
  runImport(paste.value)
  paste.value = ''
}
async function readFile(f: File): Promise<void> {
  if (!/\.(csv|txt)$/i.test(f.name)) { show('请选择 CSV 或 TXT 文件（Excel 请另存为「CSV UTF-8」）'); return }
  let text: string
  try {
    text = await f.text()
  } catch {
    show('文件读取失败，请重试')
    return
  }
  runImport(text)
}
function onFile(e: Event): void {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (f) void readFile(f)
  input.value = ''
}
function onDrop(e: DragEvent): void {
  over.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) void readFile(f)
}

/* ---------- 维度与月度管理 ---------- */
function setDim(d: DimMode): void {
  S.dim = d
  recompute()
  show(d === 'year' ? '已切换为【年度维度】' : '已切换为【月度维度】：' + periodLabel())
}
function setMonth(m: number): void {
  S.curM = m
  if (S.dim !== 'month') S.dim = 'month'
  recompute()
  show('数据月份已切换为：' + periodLabel())
}
function clearOverrides(): void {
  if (!store.canEdit) return
  clearAllMonthlyOverrides(S.curM - 1)
  recompute()
  commit('indicators')
  show('已清空 ' + periodLabel() + ' 的全部手工覆盖值，年度累计值已同步还原')
}

/* ---------- 恢复示例数据（财务负责人） ---------- */
const resetting = ref(false)
async function onReset(): Promise<void> {
  const ok = await ElMessageBox.confirm(
    '确认恢复为示例数据？这会清空服务器上已保存的全部业财数据（财务与业务指标、维度填报、政策环境事件、重点工作），所有同事看到的都将回到原工具自带的示例数据，此操作不可撤销。建议先导出备份。',
    '恢复示例数据',
    { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' },
  ).then(() => true, () => false)
  if (!ok) return
  resetting.value = true
  try {
    await resetDemo()
    show('已恢复示例数据')
  } catch (e) {
    show('恢复示例数据失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    resetting.value = false
  }
}
</script>

<template>
  <BizfinPage page-id="PAGE-F15-09" title="业财数据管理" :desc="desc">
    <div v-if="!store.canEdit" class="readonly-bar" role="note" data-readonly>当前账号对「业财数据管理」仅查看，无法导入数据或清空手工覆盖；可下载模板与导出 CSV。</div>

    <div class="grid-2 section">
      <section class="card">
        <div class="card-title"><span>表格导入</span><span class="small muted">支持 CSV 文件上传或从 Excel 直接粘贴</span></div>
        <template v-if="store.canEdit">
          <label class="drop" :class="{ over }" @dragenter.prevent="over = true" @dragover.prevent="over = true" @dragleave.prevent="over = false" @drop.prevent="onDrop">
            <span class="t">点击选择 CSV 文件，或将文件拖拽到此处</span>
            <span class="d">编码格式 UTF-8（Excel 另存为「CSV UTF-8」），首行为表头</span>
            <input type="file" accept=".csv,.txt" class="visually-hidden" data-file @change="onFile">
          </label>
          <div class="sub-h">或粘贴表格数据（支持 Excel 复制后的制表符分隔内容）</div>
          <textarea v-model="paste" class="paste" :placeholder="PASTE_HINT" aria-label="粘贴表格数据"></textarea>
        </template>
        <div class="btn-row">
          <template v-if="store.canEdit">
            <button type="button" class="btn btn-primary" data-paste-import @click="importPaste">导入粘贴内容</button>
            <button type="button" class="btn" @click="paste = ''">清空</button>
          </template>
          <button type="button" class="btn" @click="tplYear">下载导入模板</button>
          <button type="button" class="btn" @click="tplMonth">下载月度导入模板</button>
          <button type="button" class="btn" @click="tplDim">下载维度导入模板</button>
        </div>
        <p class="note">
          <b>识别规则：</b>按「编码」列匹配已有指标并覆盖；若编码不存在则按「指标名称」匹配。表头可识别的列名包括：<b>编码 / code</b>、<b>指标名称 / name</b>、<b>维度 / 维度成员 / member</b>、<b>目标值 / target</b>、<b>实际值 / actual</b>、<b>权重 / weight</b>、<b>责任部门 / dept</b>、<b>单位 / unit</b>、<b>方向 / dir</b>（正向或逆向）、<b>月份 / month</b>。只填「编码 + 实际值」也可批量更新。
        </p>
        <p class="note">
          <b>分维度填报（业务指标）：</b>表头只要包含<b>「维度」列</b>（填写维度成员名，如 <b>Amazon</b> / <b>镜柜</b> / <b>美东</b> / <b>服务商B</b>），该行即写入对应指标的<b>维度矩阵</b>；维度成员必须属于该指标声明的维度（营销板块分渠道、产品板块分品类、采购周期分品类、单位头程成本分线路、单位仓储与操作费用分服务商），否则该行被跳过。写入后指标整体值由维度填报值自动聚合（加总型求和 / 比率型算术平均），无需单独填列。
        </p>
        <p class="note">
          <b>月度填报：</b>表头只要包含<b>「月份」列</b>（取值如 <b>9</b> / <b>09月</b> / <b>2026年9月</b> / <b>2026-09</b>），该行的目标值与实际值即被识别为<b>当月数值</b>，系统会自动反算并更新年度累计值；不含月份列的表格按<b>年度累计口径</b>处理。两种口径可以放在同一个文件中。
        </p>
      </section>

      <section class="card">
        <div class="card-title"><span>导出与数据维护</span><span class="small muted">年度口径 / 月度口径均可导出</span></div>
        <div class="sub-h">年度口径导出</div>
        <div class="btn-row">
          <button v-for="b in yearExports" :key="b.label" type="button" class="btn" :class="{ 'btn-primary': b.primary }" @click="b.run">{{ b.label }}</button>
        </div>
        <div class="sub-h">月度口径导出（2026 年 1-9 月明细，含月目标 / 月实际）</div>
        <div class="btn-row">
          <button v-for="b in monthExports" :key="b.label" type="button" class="btn" :class="{ 'btn-primary': b.primary }" @click="b.run">{{ b.label }}</button>
          <button v-if="store.canReset" type="button" class="btn btn-danger" data-reset :disabled="resetting" @click="onReset">恢复示例数据</button>
        </div>
        <dl class="kv">
          <dt>财务指标数量</dt><dd>{{ stats.fin }}（一级 {{ stats.finL1 }} / 二级 {{ stats.finL2 }}）</dd>
          <dt>业务指标数量</dt><dd>{{ stats.biz }}（一级 {{ stats.bizL1 }} / 二级 {{ stats.bizL2 }}，4 板块）</dd>
          <dt>维度填报单元</dt><dd>{{ stats.dimFilledN }} / {{ stats.dimTotalN }} 个（分渠道 / 分品类 / 分线路 / 分服务商）</dd>
          <dt>业财关联关系</dt><dd>{{ LINKAGE.length }} 条</dd>
          <dt>政策环境事件</dt><dd>{{ S.POLICY_EVENTS.length }} 条</dd>
          <dt>重点工作台账</dt><dd>{{ S.KW_TASKS.length }} 项</dd>
          <dt>覆盖部门</dt><dd>{{ DEPTS.length }} 个</dd>
          <dt>覆盖渠道</dt><dd>{{ CHANNELS.length }} 个</dd>
          <dt>覆盖产品线</dt><dd>{{ CATEGORIES.length }} 条</dd>
          <dt>覆盖市场</dt><dd>{{ MARKETS.length }} 个</dd>
          <dt>数据存储</dt><dd>平台服务器（各部分独立保存，全员共享同一份数据）</dd>
        </dl>
        <p class="note">编辑与导入的数据会自动保存到平台服务器，刷新页面或换电脑登录都不会丢失；如需长期留档，请定期使用导出功能备份为 CSV 文件。<template v-if="store.canReset">「恢复示例数据」会清空服务器上已保存的全部业财数据，所有同事都会受影响。</template></p>
      </section>
    </div>

    <section class="card section">
      <div class="card-title"><span>保存记录 <span class="small muted sub">各部分最后一次保存的人与时间；尚未保存过的部分使用原工具自带的示例数据</span></span></div>
      <div class="table-wrap">
        <table class="table" data-testid="save-meta">
          <thead><tr><th>数据部分</th><th>数据来源</th><th>最后保存人</th><th>最后保存时间</th></tr></thead>
          <tbody>
            <tr v-for="m in saveMeta" :key="m.key" :data-section="m.key">
              <td>{{ m.label }}</td>
              <td><span class="badge" :class="m.is_demo ? 'badge-warn' : 'badge-good'">{{ m.is_demo ? '示例数据' : '正式数据' }}</span></td>
              <td>{{ m.updated_by ?? '—' }}</td>
              <td>{{ fmtTime(m.updated_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="card section">
      <div class="card-title">
        <span>月度 / 年度维度管理 <span class="small muted sub">全局维度对所有业财分析页面同时生效</span></span>
        <span class="badge" :class="{ 'badge-warn': S.dim === 'month' }">当前：{{ S.dim === 'year' ? '年度维度' : '月度维度' }} · {{ periodLabel() }}</span>
      </div>
      <div class="grid-3">
        <div>
          <div class="sub-h">1. 选择维度</div>
          <div class="seg" role="group" aria-label="维度管理：维度">
            <button type="button" :aria-pressed="S.dim === 'year'" @click="setDim('year')">年度维度</button>
            <button type="button" :aria-pressed="S.dim === 'month'" @click="setDim('month')">月度维度</button>
          </div>
        </div>
        <div>
          <div class="sub-h">2. 选择月份（月度维度生效）</div>
          <div class="seg months" role="group" aria-label="维度管理：月份">
            <button v-for="(m, i) in MONTHS9" :key="m" type="button" :aria-pressed="i + 1 === S.curM" @click="setMonth(i + 1)">{{ m }}</button>
          </div>
        </div>
        <div>
          <div class="sub-h">3. 手工填报的月份覆盖</div>
          <div class="small">已被手工覆盖的指标：<b data-ov-count>{{ stats.ovCount }}</b> 个</div>
          <button v-if="store.canEdit" type="button" class="btn ov-btn" data-clear-ov @click="clearOverrides">清空 {{ periodLabel() }} 的手工覆盖</button>
        </div>
      </div>
      <div class="chk-list dim-notes top-gap">
        <div class="chk ok"><span class="ic" aria-hidden="true">✓</span><div><div class="t">发生额型指标（万元 / 单 / 万次）</div>
          <div class="d">月度值按季节权重拆分，<b>月度合计严格等于年度累计值</b>；一级指标与二级明细的月度值双向勾稽一致。</div></div></div>
        <div class="chk ok"><span class="ic" aria-hidden="true">✓</span><div><div class="t">比率均值型指标（% / 天 / 元 / 倍 / 分）</div>
          <div class="d">月度值围绕年度累计值波动并带改善趋势，<b>按月加权平均严格等于年度累计值</b>。</div></div></div>
        <div class="chk ok"><span class="ic" aria-hidden="true">✓</span><div><div class="t">业务指标分维度填报（4 板块）</div>
          <div class="d">营销板块分<b>渠道</b>（Amazon / Wayfair / Home Depot / Lowe's / 独立站）、产品板块与采购周期分<b>品类</b>（框镜 / 灯镜 / 镜柜 / 其他）、单位头程成本分<b>线路</b>（美东 / 美西 / 英国 / 欧洲）、单位仓储与操作费用分<b>服务商</b>（A / B / C）。维度填报值聚合后自动回填为指标整体值。</div></div></div>
        <div class="chk ok"><span class="ic" aria-hidden="true">✓</span><div><div class="t">月度维度下可直接编辑与导入</div>
          <div class="d">在月度维度修改任一单元格，该值将作为当月实际写入，系统自动反算年度累计值，其余月份保持不变。导入表格时增加「月份」列即可批量填报月度数据。</div></div></div>
      </div>
    </section>

    <section class="card section">
      <div class="card-title"><span>数据校验结果 <span class="small muted sub">导入后可在此检查勾稽关系</span></span></div>
      <div class="chk-list" data-checks>
        <div v-for="(c, i) in checks" :key="i" class="chk" :class="c.state">
          <span class="ic" aria-hidden="true">{{ c.state === 'ok' ? '✓' : '!' }}</span>
          <div><div class="t">{{ c.title }}</div><div class="d">{{ c.detail }}</div></div>
        </div>
      </div>
    </section>

    <section class="card section">
      <div class="card-title">公司信息与组织</div>
      <dl class="kv org">
        <dt>公司名称</dt><dd>{{ COMPANY }}</dd>
        <dt>主营产品</dt><dd>{{ CATEGORIES.join(' / ') }}</dd>
        <dt>销售渠道</dt><dd>{{ CHANNELS.join(' / ') }}</dd>
        <dt>主要市场</dt><dd>{{ MARKETS.map((m) => m[0]).join(' / ') }}</dd>
      </dl>
      <div class="sub-h">业务部门</div>
      <div class="chips"><span v-for="d in DEPTS" :key="d" class="badge">{{ d }}</span></div>
    </section>

    <section class="card section">
      <div class="card-title"><span>指标字典 <span class="small muted sub">字段定义与计算口径</span></span></div>
      <div class="table-wrap">
        <table class="table dict" data-testid="dict-table">
          <thead>
            <tr>
              <th style="width: 56px">编码</th><th style="width: 52px">类型</th><th style="width: 52px">层级</th><th>指标名称</th>
              <th style="width: 58px">单位</th><th style="width: 58px">方向</th><th>计算口径 / 说明</th><th style="width: 150px">责任部门</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="i in S.IND" :key="i.code">
              <td class="code-tag">{{ i.code }}</td>
              <td><span class="badge" :class="i.kind === 'fin' ? '' : 'badge-info'">{{ i.kind === 'fin' ? '财务' : '业务' }}</span></td>
              <td><span class="badge" :class="{ 'badge-info': i.level === 1 }">{{ i.level === 1 ? '一级' : '二级' }}</span></td>
              <td>{{ i.name }}</td>
              <td class="muted">{{ i.unit }}</td>
              <td>{{ i.dir === 1 ? '正向' : '逆向' }}</td>
              <td class="wrap small">{{ i.note || '—' }}</td>
              <td class="wrap small">{{ i.depts.join(' / ') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </BizfinPage>
</template>

<style scoped>
.sub { font-weight: 400; margin-left: var(--space-2); }
.sub-h { font-size: var(--text-sm); font-weight: 600; margin: var(--space-3) 0 var(--space-2); }
.readonly-bar { margin-bottom: var(--space-4); padding: var(--space-2) var(--space-3); border-left: 3px solid var(--warn); background: color-mix(in oklab, var(--warn), white 93%); color: var(--fg-2); font-size: var(--text-sm); }
.drop { display: block; border: 1.5px dashed var(--border); border-radius: var(--radius-lg); padding: var(--space-5); text-align: center; background: var(--surface-warm); cursor: pointer; transition: border-color var(--motion-fast) var(--ease-standard), background var(--motion-fast) var(--ease-standard); }
.drop:hover, .drop.over { border-color: var(--accent); background: color-mix(in oklab, var(--accent), white 93%); }
.drop:focus-within { box-shadow: var(--focus-ring); }
.drop .t { display: block; font-size: var(--text-sm); font-weight: 600; color: var(--fg-2); }
.drop .d { display: block; font-size: var(--text-xs); color: var(--muted); margin-top: var(--space-1); }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.paste { width: 100%; box-sizing: border-box; min-height: 110px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--space-2) var(--space-3); font-family: var(--font-mono); font-size: var(--text-xs); resize: vertical; line-height: 1.7; background: var(--surface); color: var(--fg); }
.paste:focus-visible { outline: none; border-color: var(--accent); box-shadow: var(--focus-ring); }
.btn-row { display: flex; gap: var(--space-2); flex-wrap: wrap; margin: var(--space-3) 0; }
.note { font-size: var(--text-xs); color: var(--muted); line-height: 1.75; margin: var(--space-2) 0 0; }
.note b { color: var(--fg); }
.kv { display: grid; grid-template-columns: auto 1fr; gap: 6px 14px; font-size: var(--text-sm); margin: var(--space-3) 0 0; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
.kv.org { margin-bottom: var(--space-3); }
/* 月份按钮：规则网格，每个按钮自带完整边框，换行后不再出现 seg 拼接边框错位 */
.seg.months { display: grid; grid-template-columns: repeat(auto-fill, minmax(52px, 1fr)); gap: 6px; border: 0; border-radius: 0; overflow: visible; }
.seg.months button { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 4px 0; text-align: center; font-variant-numeric: tabular-nums; }
.seg.months button + button { border-left: 1px solid var(--border); }
.seg.months button[aria-pressed="true"] { border-color: var(--accent); }
.ov-btn { margin-top: var(--space-2); }
.top-gap { margin-top: var(--space-4); }
.chips { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.dict td.wrap { white-space: normal; line-height: 1.6; }
.chk-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: var(--space-2); }
.chk { display: flex; align-items: flex-start; gap: var(--space-2); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); background: var(--surface-warm); border: 1px solid var(--border-soft); }
.chk .ic { width: 17px; height: 17px; border-radius: 50%; flex: 0 0 17px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 800; color: var(--accent-on); margin-top: 2px; }
.chk.ok .ic { background: var(--success); }
.chk.warn .ic { background: var(--warn); }
.chk .t { font-size: var(--text-sm); font-weight: 600; }
.chk .d { font-size: var(--text-xs); color: var(--fg-2); line-height: 1.65; }
.chk .d b { color: var(--fg); }
/* 4 条维度说明固定两列排成 2 × 2，不再出现第二行只剩 1 条、右侧大片留白 */
.chk-list.dim-notes { grid-template-columns: repeat(2, minmax(0, 1fr)); }
@media (max-width: 760px) { .chk-list.dim-notes { grid-template-columns: minmax(0, 1fr); } }
</style>
