/** G4 报表共用类型 */
export interface VarianceNote {
  text: string
  author: string
  updated_at: string
}

export interface NoteKey {
  object_type: string
  object_key: string
}

export interface NoteTarget extends NoteKey {
  report_type: 'channel-site' | 'category'
  month: string
  /** 弹窗副标题中的对象名，如「Amazon-US-01」 */
  label: string
  note: VarianceNote | null | undefined
}
