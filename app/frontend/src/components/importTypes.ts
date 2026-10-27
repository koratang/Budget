/** 导入管线共用类型（CMP-F09-02 与后端导入批次接口的约定，见 frontend/README.md） */

export type ImportStatus = 'validating' | 'failed' | 'passed' | 'imported'

export interface ImportIssue {
  /** 行号（数字或「第 n 行起 · 共 m 行」等文字） */
  row: number | string
  /** 问题类型，如「店铺不在主数据中」 */
  type: string
  /** 涉及编码或名称 */
  name?: string
  /** 处理方式说明 */
  action?: string
  /** 处理方式链接（站内路径） */
  link?: string
}

export interface ImportOverwrite {
  /** 被覆盖的期间，如 ["2027-04"] */
  periods: string[]
  file_name: string
  imported_by: string
  imported_at: string
}

export interface ImportBatch {
  id: number | string
  status: ImportStatus
  file_name?: string
  row_count?: number
  issues?: ImportIssue[]
  /** 校验通过且期间已有数据时为 true，确认须带 overwrite=true */
  needs_overwrite?: boolean
  overwrite?: ImportOverwrite | null
  /** 摘要等其他字段由使用方通过插槽展示 */
  [key: string]: unknown
}
