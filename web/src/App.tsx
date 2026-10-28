import { useCallback, useEffect, useState } from 'react'
import { Button } from '@heroui/react'
import { Aperture, ArrowRight, X } from 'lucide-react'
import { api, type Camera, type Job, type Page, type Workspace } from './api'
import Collect from './Collect'
import Review from './Review'
import Models from './Models'
import Detect from './Detect'

const steps: { id: Page; name: string; description: string }[] = [
  { id: 'collect', name: '拍摄样本', description: '先拍好件，再拍坏件。每次拍摄保持相同位置和朝向。' },
  { id: 'review', name: '筛选图片', description: '采用清晰、完整的图片。好件用于学习正常外观，坏件留作对照。' },
  { id: 'models', name: '创建模型', description: '框住需要观察的刀片区域，用好件图片建立正常外观参考。' },
  { id: 'detect', name: '检测刀具', description: '拍摄或导入一张图片，查看与正常外观的差异。' },
]

export default function App() {
  const [page, setPage] = useState<Page>('collect')
  const [tool, setTool] = useState('第1组刀具')
  const [view, setView] = useState('top')
  const [data, setData] = useState<Workspace>({ specimens: [], images: [] })
  const [jobs, setJobs] = useState<Job[]>([])
  const [camera, setCamera] = useState<Camera>({ connected: false, sn: null })
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const refresh = useCallback(async () => {
    const [state, tasks, device] = await Promise.all([
      api<Workspace>('/api/state'), api<Job[]>('/api/jobs'), api<Camera>('/api/camera/status'),
    ])
    setData(state); setJobs(tasks); setCamera(device)
  }, [])
  useEffect(() => {
    void refresh().catch(e => setError(e.message)).finally(() => setLoading(false))
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const [tasks, device] = await Promise.all([api<Job[]>('/api/jobs'), api<Camera>('/api/camera/status')])
        if (!disposed) { setJobs(tasks); setCamera(device) }
      } catch (e) { if (!disposed) setError((e as Error).message) }
      if (!disposed) timer = setTimeout(poll, 1500)
    }
    timer = setTimeout(poll, 1500)
    return () => { disposed = true; clearTimeout(timer) }
  }, [refresh])
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true); setError('')
    try { await action() } catch (e) { setError((e as Error).message) }
    finally {
      try { await refresh() } catch (e) { setError((e as Error).message) }
      setBusy(false)
    }
  }
  const props = { tool, view, data, jobs, camera, busy, run, navigate: setPage }
  const samples = data.images.filter(i => i.tool_type === tool && i.view === view)
  const models = jobs.filter(j => j.kind === 'train' && j.tool_type === tool && j.view === view && j.status === 'succeeded')
  const detections = jobs.filter(j => j.kind === 'detect' && j.tool_type === tool && j.view === view)
  const counts = [`${samples.length} 张已保存`, `${samples.filter(i => i.included).length} 张已采用`, `${models.length} 个模型`, `${detections.length} 次检测`]
  const current = steps.findIndex(step => step.id === page)
  const active = jobs.find(j => ['running', 'stopping'].includes(j.status))
  const views: Record<string, string> = { top: '正面', side: '侧面', bottom: '背面' }

  return <div className="app-shell">
    <header className="app-header"><div className="brand"><Aperture size={24} strokeWidth={1.6} /><span>刀具检测工作台</span></div>
      <div className="connection"><span className={camera.connected ? 'dot connected' : 'dot'} /><span>{camera.connected ? '相机已连接' : '相机未连接'}</span>
        {camera.connected && <Button variant="ghost" size="sm" isDisabled={busy} onPress={() => void run(() => api('/api/camera/disconnect', 'POST'))}>断开</Button>}
        <span className="device-name mono">MER-132-30GM</span></div>
    </header>
    <div className="workspace-shell">
      <nav className="workflow" aria-label="操作步骤">{steps.map((step, index) => <button key={step.id} className={page === step.id ? 'workflow-step active' : 'workflow-step'}
        aria-current={page === step.id ? 'step' : undefined} onClick={() => setPage(step.id)}><span className="step-number">{index + 1}</span>
        <span><span className="step-title">{step.name}</span><span className="step-count">{counts[index]}</span></span>{index < 3 && <ArrowRight size={14} className="step-arrow" />}</button>)}</nav>
      <div className="context-bar"><div className="context-fields"><label>刀具组<input aria-label="刀具组" list="tool-types" maxLength={80} value={tool} onChange={e => setTool(e.target.value)} />
        <datalist id="tool-types">{[...new Set(data.specimens.map(s => s.tool_type))].map(value => <option key={value} value={value} />)}</datalist></label>
        <label>拍摄面<select aria-label="拍摄面" value={view} onChange={e => setView(e.target.value)}>{[...new Set([...Object.keys(views), ...data.images.map(i => i.view)])].map(value => <option key={value} value={value}>{views[value] ?? value}</option>)}</select></label></div>
        <span className="context-hint">同一种型号放在同一组</span>
      </div>
      <main><div className="page-heading"><div><h1>{steps[current].name}</h1><p>{steps[current].description}</p></div>
        {active && <span className="status status-running" role="status">{active.kind === 'detect' ? '检测中' : '模型创建中'}</span>}
      </div>
      {error && <div role="alert" className="error-bar"><span>{error}</span><Button variant="ghost" size="sm" isIconOnly aria-label="关闭错误" onPress={() => setError('')}><X size={16} /></Button></div>}
      <div className={`page-content page-${page}`}>{loading ? <div className="empty" role="status">正在读取工作台…</div> : !tool.trim() ? <div className="empty">请填写刀具组名称</div>
        : page === 'collect' ? <Collect key={`${tool}/${view}`} {...props} /> : page === 'review' ? <Review key={`${tool}/${view}`} {...props} /> : page === 'models' ? <Models key={`${tool}/${view}`} {...props} /> : <Detect key={`${tool}/${view}`} {...props} />}
      </div>
      </main>
    </div>
  </div>
}
