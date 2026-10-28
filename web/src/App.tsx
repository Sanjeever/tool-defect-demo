import { useCallback, useEffect, useState } from 'react'
import { Button } from '@heroui/react'
import { Aperture, Camera as CameraIcon, Layers3, ScanLine, X } from 'lucide-react'
import { api, type Camera, type Job, type Workspace } from './api'
import Collect from './Collect'
import Models from './Models'
import Detect from './Detect'

const pages = [
  { id: 'collect', name: '采集与样本', icon: CameraIcon },
  { id: 'models', name: '模型', icon: Layers3 },
  { id: 'detect', name: '检测', icon: ScanLine },
] as const

export default function App() {
  const [page, setPage] = useState<(typeof pages)[number]['id']>('collect')
  const [tool, setTool] = useState('type_01')
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
    void refresh().catch(e => setError(String(e.message))).finally(() => setLoading(false))
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const [tasks, device] = await Promise.all([api<Job[]>('/api/jobs'), api<Camera>('/api/camera/status')])
        if (!disposed) { setJobs(tasks); setCamera(device) }
      } catch (e) { if (!disposed) setError((e as Error).message) }
      if (!disposed) timer = setTimeout(poll, 2000)
    }
    timer = setTimeout(poll, 2000)
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
  const props = { tool, view, data, jobs, camera, busy, run }
  const active = jobs.find(job => ['running', 'stopping'].includes(job.status))

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><Aperture size={26} strokeWidth={1.6} /><span>刀具视觉<span className="brand-sub">工作台</span></span></div>
      <nav aria-label="主导航">{pages.map(item => <button key={item.id} className={page === item.id ? 'nav-item active' : 'nav-item'}
        aria-current={page === item.id ? 'page' : undefined} onClick={() => setPage(item.id)}><item.icon size={18} />{item.name}</button>)}</nav>
      <div className="sidebar-bottom"><div>MER-132-30GM</div><span className="mono">192.168.0.22</span><div className="device-line"><span className={camera.connected ? 'dot connected' : 'dot'} />{camera.connected ? '已连接' : '未连接'}</div></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="context-fields">
        <label>刀具型号<input aria-label="刀具型号" list="tool-types" value={tool} onChange={e => setTool(e.target.value)} />
          <datalist id="tool-types">{[...new Set(data.specimens.map(s => s.tool_type))].map(value => <option key={value} value={value} />)}</datalist></label>
        <span className="context-divider" />
        <label>拍摄面<input aria-label="拍摄面" list="views" value={view} onChange={e => setView(e.target.value)} />
          <datalist id="views">{[...new Set(['top', 'side', 'bottom', ...data.images.map(i => i.view)])].map(value => <option key={value} value={value} />)}</datalist></label>
      </div><Button variant={camera.connected ? 'outline' : 'primary'} size="sm" isDisabled={busy}
        onPress={() => void run(() => api(`/api/camera/${camera.connected ? 'disconnect' : 'connect'}`, 'POST', camera.connected ? undefined : {}))}>
        <CameraIcon size={15} />{camera.connected ? '断开相机' : '连接相机'}</Button></header>
      <main>
        <div className="page-heading"><h1>{pages.find(item => item.id === page)!.name}</h1>{active && <span className="running-status" role="status"><span className="dot connected" />{active.kind === 'detect' ? '检测' : '训练'}任务运行中</span>}</div>
        {error && <div role="alert" className="error-bar"><span>{error}</span><Button variant="ghost" size="sm" isIconOnly aria-label="关闭错误" onPress={() => setError('')}><X size={16} /></Button></div>}
        {loading ? <div className="empty" role="status">正在读取工作台…</div> : !tool.trim() || !view.trim() ? <div className="empty">请填写刀具型号和拍摄面</div>
          : page === 'collect' ? <Collect key={`${tool}/${view}`} {...props} /> : page === 'models' ? <Models key={`${tool}/${view}`} {...props} /> : <Detect key={`${tool}/${view}`} {...props} />}
      </main>
    </div>
  </div>
}
