import { useEffect, useMemo, useState } from 'react'
import { Button } from '@heroui/react'
import { api, artifact, phases, statuses, type Job, type Run } from './api'
import Pager from './Pager'
import usePanelSize from './usePanelSize'

export default function JobLog({ job, busy, run }: { job?: Job; busy: boolean; run: Run }) {
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [page, setPage] = useState<number | null>(null)
  const area = usePanelSize()
  useEffect(() => {
    setText(''); setError(''); setPage(null)
    if (!job || (!expanded && job.status !== 'failed')) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const load = async () => {
      try {
        const log = await api<{ text: string }>(`/api/jobs/${job.id}/log`)
        if (!disposed) setText(log.text)
      } catch (e) { if (!disposed) setError((e as Error).message) }
      if (!disposed && ['running', 'stopping'].includes(job.status)) timer = setTimeout(load, 1500)
    }
    void load()
    return () => { disposed = true; clearTimeout(timer) }
  }, [job?.id, job?.status, expanded])
  const columns = Math.max(8, Math.floor((area.width - 16) / 12))
  const rows = Math.max(1, Math.floor((area.height - 16) / 18))
  const lines = useMemo(() => (error || text || '正在读取日志…').replace(/\t/g, '    ').split(/\r?\n/).flatMap(line => {
    const characters = Array.from(line)
    return characters.length ? Array.from({ length: Math.ceil(characters.length / columns) }, (_, index) => characters.slice(index * columns, (index + 1) * columns).join('')) : ['']
  }), [text, error, columns])
  const pages = Math.max(1, Math.ceil(lines.length / rows))
  const currentPage = page === null ? pages - 1 : Math.min(page, pages - 1)

  if (!job) return <div className="empty">暂无任务记录</div>
  return <section className="job-panel"><div className="job-heading"><span className={`status status-${job.status}`}>{statuses[job.status] ?? job.status}</span>
    <span className="muted">{job.status === 'running' ? phases[job.phase] : ''}</span><Button variant="ghost" size="sm" onPress={() => setExpanded(!expanded)}>{expanded ? '任务信息' : '查看日志'}</Button></div>
    {expanded ? <><div className="job-log-area" ref={area.ref}><pre className="job-log" aria-label="模型任务日志">{lines.slice(currentPage * rows, (currentPage + 1) * rows).join('\n')}</pre></div>
      <Pager page={currentPage} pages={pages} onChange={setPage} label="日志" /></> : <div className="job-status-body">
      <p>{job.kind === 'detect' ? '检测任务' : job.model === 'patchcore' ? 'PatchCore 正常外观参考' : 'YOLO 缺陷分类'}</p><span className="muted">{job.created_at.replace('T', ' ')}</span>
      {(job.error || error) && <p role="alert" className="inline-error">{job.error || error}</p>}
      {['running', 'stopping'].includes(job.status) && <Button variant="danger-soft" size="sm" isDisabled={busy || job.status === 'stopping'} onPress={() => void run(() => api(`/api/jobs/${job.id}/stop`, 'POST'))}>停止任务</Button>}
    </div>}
    <div className="job-files"><a className="text-link" href={artifact(job.id, 'manifest.json')} target="_blank" rel="noreferrer">数据清单</a>
      <a className="text-link" href={artifact(job.id, 'run.log')} target="_blank" rel="noreferrer">完整日志</a>
      {job.checkpoint && <a className="text-link" href={artifact(job.id, 'model.zip')}>下载模型</a>}</div>
  </section>
}
