export type Quality = 'good' | 'defect' | 'unknown'
export type Split = 'unassigned' | 'train' | 'val' | 'test'
export type Roi = [number, number, number, number] | null
export interface Box { x: number; y: number; width: number; height: number; label: string; confidence?: number }
export const defectLabels = ['磨损', '缺角', '划痕', '氧化']
export interface Specimen {
  tool_type: string; specimen_id: string; quality: Quality; split: Split; category: string
}
export interface Sample extends Specimen {
  id: string; path: string; width: number; height: number; included: boolean; view: string; created_at: string
  boxes: Box[]; annotated: boolean; specimen_quality: Quality
}
export interface Scheme { tool_type: string; view: string; anomaly_job: string; detector_job: string | null }
export interface Workspace { specimens: Specimen[]; images: Sample[]; schemes: Scheme[]; geti_ready?: boolean }
export interface Camera { connected: boolean; sn: string | null; fps?: number; size?: number[]; error?: string }
export interface Job {
  id: string; kind?: 'train' | 'detect'; status: string; phase: string; created_at: string
  tool_type: string; view: string; model: 'patchcore' | 'detector' | 'scheme'; experimental: boolean
  checkpoint: string | null; error: string
  settings?: { preprocessing: string }
  result?: { label: string; anomaly_score: number | null; anomaly_label?: string; source_size: number[]; boxes: Box[]; tool_type?: string; view?: string; experimental?: boolean; defect_status?: string; models?: { anomaly: string; detector: string | null }; recognition: { method: string; similarity: number | null; candidates: (Scheme & { similarity: number })[] } }
  review?: { quality: Quality; note: string; at: string; boxes: Box[]; tool_type?: string; view?: string }
  reviews?: Job['review'][]; adopted_image?: string
  metrics?: { scope: string; values: Record<string, number | number[]> }
}
export interface Plan {
  ready: boolean; issues: string[]
  counts: Record<'train' | 'val' | 'test', { good: number; defect: number; specimens: number }>
}
export type Run = (action: () => Promise<unknown>) => Promise<void>
export type Page = 'collect' | 'review' | 'models' | 'detect' | 'records'
export interface PageProps {
  tool: string; view: string; data: Workspace; jobs: Job[]; camera: Camera; busy: boolean; run: Run
  navigate: (page: Page) => void
  onDirty: (dirty: boolean) => void
}
export const qualities = { unknown: '待确认', good: '好件', defect: '坏件' }
export const splits = { unassigned: '未分组', train: '训练', val: '验证', test: '测试' }
export const statuses: Record<string, string> = {
  running: '运行中', stopping: '停止中', succeeded: '已完成', failed: '失败', cancelled: '已停止', interrupted: '已中断',
}
export const phases: Record<string, string> = { preparing: '准备数据', training: '训练中', predicting: '检测中', finished: '完成' }
export const query = (values: Record<string, string | number | boolean>) => new URLSearchParams(
  Object.entries(values).map(([key, value]) => [key, String(value)]),
).toString()

export async function response(path: string, init?: RequestInit) {
  const result = await fetch(path, init)
  if (!result.ok) {
    const body = await result.json().catch(() => ({ detail: `请求失败（${result.status}）` }))
    throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
  }
  return result
}
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  return (await response(path, { method, headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body) })).json()
}
export const imageUrl = (id: string) => `/api/images/${id}/file`
export const artifact = (job: string, name: string) => `/api/jobs/${job}/artifact?${query({ name })}`
export const jobTitle = (job: Job) => `${job.created_at?.replace('T', ' ')} · ${job.model === 'patchcore' ? 'PatchCore' : 'Geti'}${job.experimental ? ' · 实验' : ''}`
