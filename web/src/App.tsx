import { useCallback, useEffect, useState } from 'react'
import { Button } from '@heroui/react'
import { Aperture, ScanLine, Images, Layers3, History, X } from 'lucide-react'
import { api, type Camera, type Job, type Page, type Workspace } from './api'
import Collect from './Collect'
import Review from './Review'
import Models from './Models'
import Detect from './Detect'

const tabs = [{ id: 'detect', name: '检测', Icon: ScanLine }, { id: 'review', name: '样本', Icon: Images }, { id: 'models', name: '模型', Icon: Layers3 }, { id: 'records', name: '记录', Icon: History }] as const

export default function App() {
  const [page, setPage] = useState<Page>('detect')
  const [tool, setTool] = useState('刀具01')
  const [view, setView] = useState('top')
  const [data, setData] = useState<Workspace>({ specimens: [], images: [], schemes: [] })
  const [jobs, setJobs] = useState<Job[]>([])
  const [camera, setCamera] = useState<Camera>({ connected: false, sn: null })
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    const preventClose = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault() }
    window.addEventListener('beforeunload', preventClose)
    return () => window.removeEventListener('beforeunload', preventClose)
  }, [dirty])
  const refresh = useCallback(async () => {
    const [state, tasks, device] = await Promise.all([api<Workspace>('/api/state'), api<Job[]>('/api/jobs'), api<Camera>('/api/camera/status')])
    setData(state); setJobs(tasks); setCamera(device)
  }, [])
  useEffect(() => {
    void refresh().catch(e => setError(e.message)).finally(() => setLoading(false))
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try { const [tasks, device] = await Promise.all([api<Job[]>('/api/jobs'), api<Camera>('/api/camera/status')]); if (!disposed) { setJobs(tasks); setCamera(device) } }
      catch (e) { if (!disposed) setError((e as Error).message) }
      if (!disposed) timer = setTimeout(poll, 1500)
    }
    timer = setTimeout(poll, 1500)
    return () => { disposed = true; clearTimeout(timer) }
  }, [refresh])
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true); setError('')
    try { await action() } catch (e) { setError((e as Error).message) }
    finally { try { await refresh() } catch (e) { setError((e as Error).message) }; setBusy(false) }
  }
  const navigate = (next: Page) => { if (dirty) setError('请先保存或撤销当前标注'); else setPage(next) }
  const changeTool = (value: string) => { if (dirty) setError('请先保存或撤销当前标注'); else setTool(value) }
  const changeView = (value: string) => { if (dirty) setError('请先保存或撤销当前标注'); else setView(value) }
  const props = { tool, view, data, jobs, camera, busy, run, navigate, onDirty: setDirty }
  const contextual = ['collect', 'review', 'models'].includes(page)
  const active = jobs.find(j => ['running', 'stopping'].includes(j.status))
  const counts = [data.schemes.length ? `${data.schemes.length} 个方案` : '', `${data.images.length} 张图片`, `${jobs.filter(j => j.kind === 'train' && j.status === 'succeeded').length} 个模型`, `${jobs.filter(j => j.kind === 'detect').length} 条记录`]
  return <div className="app-shell"><header className="app-header"><div className="brand"><Aperture size={22} strokeWidth={1.6} /><span>刀具视觉工作台</span></div><div className="connection"><span className={camera.connected ? 'dot connected' : 'dot'} /><span>{camera.connected ? '相机已连接' : '相机未连接'}</span>{camera.connected && <Button size="sm" variant="ghost" isDisabled={busy} onPress={() => void run(() => api('/api/camera/disconnect', 'POST'))}>断开</Button>}<span className="device-name mono">MER-132-30GM</span></div></header>
    <div className={`workspace-shell ${contextual ? '' : 'without-context'}`}><nav className="workflow" aria-label="工作区">{tabs.map(({ id, name, Icon }, index) => <button key={id} disabled={busy} className={`workflow-step ${page === id || (id === 'review' && page === 'collect') ? 'active' : ''}`} aria-current={page === id ? 'page' : undefined} onClick={() => navigate(id)}><Icon size={17} strokeWidth={1.6} /><span><span className="step-title">{name}</span><span className="step-count">{counts[index]}</span></span></button>)}</nav>
      {contextual && <div className="context-bar"><div className="context-fields"><label>刀具类型<input aria-label="刀具类型" disabled={busy || dirty} list="tool-types" value={tool} maxLength={80} onChange={e => changeTool(e.target.value)} /><datalist id="tool-types">{[...new Set([...Array.from({ length: 7 }, (_, i) => `刀具0${i + 1}`), ...data.specimens.map(s => s.tool_type)])].map(value => <option key={value}>{value}</option>)}</datalist></label><label>拍摄面<select aria-label="拍摄面" disabled={busy || dirty} value={view} onChange={e => changeView(e.target.value)}><option value="top">正面</option><option value="bottom">背面</option></select></label></div>{page === 'collect' && <Button size="sm" variant="ghost" onPress={() => navigate('review')}>返回样本</Button>}</div>}
      <main>{active && <div className="active-task" role="status"><span>{active.kind === 'train' ? '模型训练中' : '检测中'} · {active.tool_type === 'auto' ? '自动识别' : active.tool_type}</span><Button variant="ghost" size="sm" isDisabled={busy || active.status === 'stopping'} onPress={() => void run(() => api(`/api/jobs/${active.id}/stop`, 'POST'))}>{active.status === 'stopping' ? '停止中' : '停止任务'}</Button></div>}
        {error && <div className="error-bar" role="alert"><span>{error}</span><Button variant="ghost" size="sm" isIconOnly aria-label="关闭错误" onPress={() => setError('')}><X size={16} /></Button></div>}
        <div className={`page-content page-${page}`}>{loading ? <div className="empty">正在读取工作台…</div> : contextual && !tool.trim() ? <div className="empty">请填写刀具类型</div> : page === 'collect' ? <Collect key={`${tool}/${view}`} {...props} /> : page === 'review' ? <Review key={`${tool}/${view}`} {...props} /> : page === 'models' ? <Models key={`${tool}/${view}`} {...props} /> : <Detect key={page} {...props} records={page === 'records'} />}</div>
      </main></div></div>
}
