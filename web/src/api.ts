export type Quality = 'good' | 'defect' | 'unknown'
export type Split = 'unassigned' | 'train' | 'val' | 'test'
export type Roi = [number, number, number, number] | null
export interface Specimen {
  tool_type: string; specimen_id: string; quality: Quality; split: Split; category: string
}
export interface Sample extends Specimen {
  id: string; path: string; width: number; height: number; included: boolean; view: string; created_at: string
}
export interface Workspace { specimens: Specimen[]; images: Sample[] }
export interface Camera { connected: boolean; sn: string | null }
export interface Job {
  id: string; kind?: 'train' | 'detect'; status: string; phase: string; created_at: string
  tool_type: string; view: string; model: 'patchcore' | 'classifier'; experimental: boolean
  checkpoint: string | null; error: string
  settings?: { roi: Roi; source_size: number[]; preprocessing: string }
  result?: { label: string; anomaly_score: number; classification?: { category: string; confidence: number; decision: string } }
  review?: { quality: Quality; note: string; at: string }
}
export interface Plan {
  ready: boolean; issues: string[]
  counts: Record<'train' | 'val' | 'test', { good: number; defect: number; specimens: number }>
}
export type Run = (action: () => Promise<unknown>) => Promise<void>
export interface PageProps {
  tool: string; view: string; data: Workspace; jobs: Job[]; camera: Camera; busy: boolean; run: Run
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
export const jobTitle = (job: Job) => `${job.created_at?.replace('T', ' ')} · ${job.model === 'patchcore' ? 'PatchCore' : 'YOLO'}${job.experimental ? ' · 未校准' : ''}`
