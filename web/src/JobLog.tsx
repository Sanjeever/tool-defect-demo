import { useEffect, useState } from 'react'
import { Button } from '@heroui/react'
import { api, artifact, phases, statuses, type Job, type Run } from './api'

export default function JobLog({ job, busy, run }: { job?: Job; busy: boolean; run: Run }) {
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)
  useEffect(() => {
    setText(''); setError('')
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

  if (!job) return null
  return <section className="panel job-panel"><div className="panel-toolbar"><div className="flex items-center gap-3"><h2>任务状态</h2>
    <span className={`status status-${job.status}`}>{statuses[job.status] ?? job.status}</span><span className="muted text-xs">{job.status === 'running' ? phases[job.phase] : ''}</span></div>
    <div className="flex items-center gap-3">
      <a className="text-link" href={artifact(job.id, 'manifest.json')} target="_blank" rel="noreferrer">数据清单</a>
      {job.checkpoint && <a className="text-link" href={artifact(job.id, 'model.zip')}>下载模型</a>}
      {['running', 'stopping'].includes(job.status) && <Button variant="danger-soft" size="sm" isDisabled={busy || job.status === 'stopping'}
        onPress={() => void run(() => api(`/api/jobs/${job.id}/stop`, 'POST'))}>停止任务</Button>}
    </div></div>
    {(job.error || error) && <p role="alert" className="inline-error">{job.error || error}</p>}
    <details className="log-details" open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}><summary>查看运行日志</summary>
      <pre className="job-log" tabIndex={0} aria-label="模型任务日志">{text || '正在读取日志…'}</pre></details>
  </section>
}
