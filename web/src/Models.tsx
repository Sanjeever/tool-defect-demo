import { useEffect, useState } from 'react'
import { Button } from '@heroui/react'
import { Play, Layers3 } from 'lucide-react'
import { api, imageUrl, jobTitle, query, splits, type Job, type PageProps, type Plan } from './api'
import JobLog from './JobLog'
import Pager from './Pager'

export default function Models({ tool, view, data, jobs, busy, run, navigate }: PageProps) {
  const [model, setModel] = useState<'patchcore' | 'detector'>('patchcore')
  const [experimental, setExperimental] = useState(true)
  const [device, setDevice] = useState('cuda')
  const [batch, setBatch] = useState(2)
  const [epochs, setEpochs] = useState(30)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [error, setError] = useState('')
  const [pane, setPane] = useState('create')
  const [picture, setPicture] = useState('original')
  const [previewError, setPreviewError] = useState(false)
  const [selectedJob, setSelectedJob] = useState('')
  const [anomalyId, setAnomalyId] = useState('')
  const [detectorId, setDetectorId] = useState('')
  const [issue, setIssue] = useState(0)
  const [mobilePane, setMobilePane] = useState('controls')
  const history = jobs.filter(j => j.kind === 'train' && j.tool_type === tool && j.view === view)
  const job = history.find(j => j.id === selectedJob) ?? history[0]
  const trained = history.filter(j => j.status === 'succeeded')
  const anomalies = trained.filter(j => j.model === 'patchcore')
  const detectors = trained.filter(j => j.model === 'detector')
  const scheme = data.schemes.find(s => s.tool_type === tool && s.view === view)
  const anomaly = anomalies.find(j => j.id === anomalyId)?.id ?? scheme?.anomaly_job ?? anomalies[0]?.id ?? ''
  const detector = detectorId === 'none' ? '' : detectors.find(j => j.id === detectorId)?.id ?? scheme?.detector_job ?? detectors[0]?.id ?? ''
  const sample = data.images.find(i => i.tool_type === tool && i.view === view && i.included && i.annotated && i.quality === 'good' && i.split === 'train')
  const active = jobs.some(j => ['running', 'stopping'].includes(j.status))
  useEffect(() => {
    let disposed = false
    setPlan(null); setError('')
    void api<Plan>(`/api/dataset?${query({ tool_type: tool, view, model, experimental })}`).then(value => { if (!disposed) setPlan(value) }).catch(e => { if (!disposed) setError(e.message) })
    return () => { disposed = true }
  }, [tool, view, model, experimental, data])
  const train = () => run(async () => {
    const next = await api<Job>('/api/jobs', 'POST', { tool_type: tool, view, model, experimental, device, batch_size: batch, epochs })
    setSelectedJob(next.id); setPane('history')
  })
  return <div className={`model-workspace model-mobile-${mobilePane}`}><div className="mobile-workspace-tabs pane-tabs"><button onClick={() => setMobilePane('region')}>定位预览</button><button onClick={() => setMobilePane('controls')}>模型操作</button></div><div className="model-grid">
    <section className="panel image-panel"><div className="pane-tabs">{[['original', '参考原图'], ['aligned', '自动定位']].map(([value, name]) => <button key={value} className={picture === value ? 'active' : ''} onClick={() => { setPicture(value); setPreviewError(false) }}>{name}</button>)}</div>
      <div className="image-stage">{sample && !previewError ? <img src={picture === 'original' ? imageUrl(sample.id) : `/api/images/${sample.id}/aligned`} alt="正常参考图定位预览" onError={() => setPreviewError(true)} /> : <div className="stage-empty"><Layers3 size={28} /><span>{previewError ? '定位失败，请检查画面是否包含完整单把刀具' : '先确认并采用当前面的正常训练图片'}</span><Button variant="outline" onPress={() => navigate('review')}>前往样本</Button></div>}</div>
      <div className="image-caption"><span>{sample?.specimen_id ?? '尚无正常参考图'}</span><span>PatchCore 256 px · Geti 512 px</span></div>
    </section>
    <section className="panel model-sidebar"><div className="pane-tabs">{[['create', '训练'], ['scheme', '启用方案'], ['settings', '参数'], ['history', '任务']].map(([value, name]) => <button key={value} className={pane === value ? 'active' : ''} onClick={() => setPane(value)}>{name}</button>)}</div>
      {pane === 'create' ? <div className="training-form"><label className="field">模型能力<select aria-label="模型能力" value={model} onChange={e => setModel(e.target.value as typeof model)}><option value="patchcore">Anomalib · 正常外观</option><option value="detector">Geti · 缺陷区域</option></select></label>
        <label className="check-field"><input type="checkbox" checked={experimental} onChange={e => setExperimental(e.target.checked)} />实验训练</label>
        <p className="model-note">{experimental ? '使用训练组，不使用验证集，不产生正式合格结论。' : '使用不同实物的验证组校准，测试组保留作独立评估。'}</p>
        <div className="data-summary"><table><thead><tr><th>分组</th><th>实物</th><th>合格图</th><th>不合格图</th></tr></thead><tbody>{(['train', 'val', 'test'] as const).map(split => <tr key={split}><td>{splits[split]}</td><td>{plan?.counts[split].specimens ?? '—'}</td><td>{plan?.counts[split].good ?? '—'}</td><td>{plan?.counts[split].defect ?? '—'}</td></tr>)}</tbody></table></div>
        {(error || (model === 'detector' && !data.geti_ready)) && <p className="inline-error">{error || 'Geti 环境尚未安装，运行 uv sync --locked --project engines/geti'}</p>}
        {!!plan?.issues.length && <div className="data-requirements"><p className="data-issues">{plan.issues[Math.min(issue, plan.issues.length - 1)]}</p><Pager page={Math.min(issue, plan.issues.length - 1)} pages={plan.issues.length} onChange={setIssue} label="数据要求" /></div>}
        <Button isDisabled={busy || active || !plan?.ready || (model === 'detector' && !data.geti_ready) || batch < 1 || epochs < 1} onPress={() => void train()}><Play size={15} />{active ? '任务运行中' : '开始训练'}</Button>
      </div> : pane === 'scheme' ? <div className="settings-form"><label className="field">正常外观模型<select aria-label="方案正常外观模型" value={anomaly} onChange={e => setAnomalyId(e.target.value)}>{!anomalies.length && <option value="">尚无模型</option>}{anomalies.map(j => <option key={j.id} value={j.id}>{jobTitle(j)}</option>)}</select></label>
        <label className="field">缺陷区域模型<select aria-label="方案缺陷区域模型" value={detector} onChange={e => setDetectorId(e.target.value || 'none')}><option value="">尚未配置</option>{detectors.map(j => <option key={j.id} value={j.id}>{jobTitle(j)}</option>)}</select></label>
        <Button isDisabled={busy || !anomaly || (anomaly === scheme?.anomaly_job && (detector || null) === scheme?.detector_job)} onPress={() => void run(() => api('/api/schemes', 'PUT', { tool_type: tool, view, anomaly_job: anomaly, detector_job: detector || null }))}>启用此方案</Button>
        <span className="model-note">{scheme ? '当前类型和拍摄面已有启用方案' : '启用后加入自动类型与拍摄面匹配'}</span>
      </div> : pane === 'settings' ? <div className="settings-form"><label className="field">运行设备<select value={device} onChange={e => setDevice(e.target.value)}><option value="cuda">GPU · CUDA</option><option value="cpu">CPU</option></select></label><label className="field">批量大小<input type="number" min="1" max="64" value={batch} onChange={e => setBatch(Number(e.target.value))} /></label><label className="field">Geti 训练轮数<input type="number" min="1" max="1000" value={epochs} onChange={e => setEpochs(Number(e.target.value))} /></label></div>
      : <div className="model-history"><select aria-label="训练任务" value={job?.id ?? ''} onChange={e => setSelectedJob(e.target.value)}>{!history.length && <option value="">暂无任务</option>}{history.map(j => <option key={j.id} value={j.id}>{jobTitle(j)}</option>)}</select><JobLog job={job} busy={busy} run={run} /></div>}
    </section>
  </div></div>
}
