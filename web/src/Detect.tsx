import { useEffect, useRef, useState } from 'react'
import { Button } from '@heroui/react'
import { ArrowRight, Camera, FileImage, ScanLine } from 'lucide-react'
import { api, artifact, jobTitle, qualities, query, response, statuses, type Job, type PageProps, type Quality } from './api'
import JobLog from './JobLog'

const pictures = [['source.png', '原图'], ['input.png', '模型输入'], ['predictions/input.heatmap.png', '热力图']]

export default function Detect({ tool, view, data, jobs, camera, busy, run, navigate }: PageProps) {
  const trained = jobs.filter(j => j.kind === 'train' && j.status === 'succeeded' && j.tool_type === tool && j.view === view)
  const anomalies = trained.filter(j => j.model === 'patchcore')
  const [anomalyId, setAnomalyId] = useState('')
  const anomaly = anomalies.find(j => j.id === anomalyId) ?? anomalies[0]
  const compatible = trained.filter(j => j.model === 'classifier' && j.settings && anomaly?.settings && JSON.stringify(j.settings.roi) === JSON.stringify(anomaly.settings.roi) && JSON.stringify(j.settings.source_size) === JSON.stringify(anomaly.settings.source_size))
  const [classifier, setClassifier] = useState('')
  const [device, setDevice] = useState('cuda')
  const [confidence, setConfidence] = useState(0.7)
  const [sample, setSample] = useState('')
  const [selectedJob, setSelectedJob] = useState('')
  const [review, setReview] = useState<Quality>('unknown')
  const [note, setNote] = useState('')
  const [pane, setPane] = useState('operate')
  const [visual, setVisual] = useState('live')
  const [picture, setPicture] = useState('predictions/input.heatmap.png')
  const upload = useRef<HTMLInputElement>(null)
  const samples = data.images.filter(i => i.tool_type === tool && i.view === view)
  const history = jobs.filter(j => j.kind === 'detect' && j.tool_type === tool && j.view === view)
  const job = history.find(j => j.id === selectedJob) ?? history[0]
  const active = jobs.some(j => ['running', 'stopping'].includes(j.status))
  const ready = !!anomaly && !busy && !active
  const classificationJob = !anomaly?.experimental && compatible.some(j => j.id === classifier) ? classifier : null
  const settings = { anomaly_job: anomaly?.id ?? '', classifier_job: classificationJob, device, min_confidence: confidence }
  const result = job?.status === 'succeeded' ? job.result : undefined
  useEffect(() => { setClassifier('') }, [anomaly?.id])
  useEffect(() => { setReview(job?.review?.quality ?? 'unknown'); setNote(job?.review?.note ?? '') }, [job?.id, job?.review?.quality, job?.review?.note])
  const detect = (fromCamera: boolean) => run(async () => {
    const next = await api<Job>('/api/detections', 'POST', { ...settings, camera: fromCamera, image_id: fromCamera ? null : sample })
    setSelectedJob(next.id); setVisual('result')
  })
  const detectFile = (file: File) => run(async () => {
    const params = query({ anomaly_job: settings.anomaly_job, device, min_confidence: confidence, ...(classificationJob ? { classifier_job: classificationJob } : {}) })
    const next = await (await response(`/api/detections/upload?${params}`, { method: 'POST', body: file })).json()
    setSelectedJob(next.id); setVisual('result')
  })
  if (!anomaly) return <section className="empty-state"><ScanLine size={28} strokeWidth={1.3} /><h2>这组刀具还没有可用模型</h2><p>先采用好件图片，创建正常外观参考。</p><Button onPress={() => navigate('models')}>前往创建模型<ArrowRight size={15} /></Button></section>

  return <div className="detect-grid"><section className="panel detection-viewer"><div className="pane-tabs" aria-label="检测画面"><button aria-pressed={visual === 'live'} className={visual === 'live' ? 'active' : ''} onClick={() => setVisual('live')}>实时画面</button>
    <button aria-pressed={visual === 'result'} className={visual === 'result' ? 'active' : ''} onClick={() => setVisual('result')}>检测结果</button>
    {visual === 'result' && <select aria-label="选择检测记录" value={job?.id ?? ''} onChange={e => setSelectedJob(e.target.value)}>{!history.length && <option value="">暂无记录</option>}{history.map(j => <option key={j.id} value={j.id}>{j.created_at.replace('T', ' ')} · {j.result?.label ?? statuses[j.status]}</option>)}</select>}</div>
    {visual === 'live' ? <div className="detection-live">{camera.connected && !camera.error ? <img src="/api/camera/live" alt="检测前实时画面" /> : <div className="stage-empty"><Camera size={28} /><span>{camera.error || '相机未连接，可导入图片检测'}</span><Button variant="outline" size="sm" onPress={() => navigate('collect')}>前往连接相机</Button></div>}</div>
      : result && job ? <div className="result-content"><div className="result-summary"><div><span className="eyebrow">判断</span><strong className={result.label === '异常' ? 'abnormal' : ''}>{result.label}</strong></div><div><span className="eyebrow">异常分数</span><strong className="mono">{result.anomaly_score.toFixed(4)}</strong></div>
        {(result.classification || result.label === '异常') && <div><span className="eyebrow">缺陷分类</span><strong>{result.classification?.decision ?? '待复核'}</strong>{result.classification && <span className="muted">{result.classification.category} · {(result.classification.confidence * 100).toFixed(1)}%</span>}</div>}
        <a className="text-link" href={artifact(job.id, 'result.json')} target="_blank" rel="noreferrer">结果 JSON</a></div>
        <div className="picture-tabs pane-tabs">{pictures.map(([name, title]) => <button key={name} aria-pressed={picture === name} className={picture === name ? 'active' : ''} onClick={() => setPicture(name)}>{title}</button>)}</div>
        <div className="result-images">{pictures.map(([name, title]) => <figure key={name} className={picture === name ? 'active' : ''}><div><img src={artifact(job.id, name)} alt={title} /></div><figcaption>{title}</figcaption></figure>)}</div></div>
      : <div className="empty-state"><ScanLine size={28} /><p>{job && ['running', 'stopping'].includes(job.status) ? '正在检测图片…' : job?.error || '暂无检测结果'}</p>{job && <Button variant="outline" size="sm" onPress={() => setPane('logs')}>查看任务日志</Button>}</div>}
  </section><section className="panel detect-sidebar"><div className="pane-tabs" aria-label="检测操作面板">{[['operate', '检测'], ['settings', '设置'], ['review', '复核'], ['logs', '日志']].map(([value, name]) => <button key={value} aria-pressed={pane === value} className={pane === value ? 'active' : ''} onClick={() => { setPane(value); if (value === 'review') setVisual('result') }}>{name}</button>)}</div>
    {pane === 'operate' ? <div className="detect-primary"><h2>{anomaly.experimental ? '正常外观参考' : '正常／异常判定'}</h2><p className="model-note">保持与采样时相同的拍摄面、位置和光线。</p>
      {anomaly.experimental && <p className="model-note">未校准模型用于观察差异，不代表合格判断。</p>}
      <Button fullWidth isDisabled={!ready || !camera.connected || !!camera.error} onPress={() => void detect(true)}><Camera size={16} />{active ? '任务运行中…' : '拍照检测'}</Button>
      <Button fullWidth variant="outline" isDisabled={!ready} onPress={() => upload.current?.click()}><FileImage size={16} />导入图片检测</Button>
      {result && <Button fullWidth variant="ghost" onPress={() => { setVisual('result'); setPane('review') }}>复核当前结果<ArrowRight size={15} /></Button>}
    </div> : pane === 'settings' ? <div className="settings-form"><label className="field">异常模型<select aria-label="异常模型" value={anomaly.id} onChange={e => setAnomalyId(e.target.value)}>{anomalies.map(j => <option key={j.id} value={j.id}>{jobTitle(j)}</option>)}</select></label>
      <label className="field">缺陷分类模型<select aria-label="缺陷分类模型" disabled={anomaly.experimental} value={classificationJob ?? ''} onChange={e => setClassifier(e.target.value)}><option value="">不分类</option>{compatible.map(j => <option key={j.id} value={j.id}>{jobTitle(j)}</option>)}</select></label>
      <div className="form-row"><label className="field">运行设备<select aria-label="运行设备" value={device} onChange={e => setDevice(e.target.value)}><option value="cuda">GPU · CUDA</option><option value="cpu">CPU</option></select></label><label className="field">分类门槛<input aria-label="分类置信度门槛" type="number" min="0" max="1" step="0.05" value={confidence} onChange={e => setConfidence(Number(e.target.value))} /></label></div>
      <label className="field">已保存样本<select aria-label="样本图片" value={sample} onChange={e => setSample(e.target.value)}><option value="">选择样本</option>{samples.map(i => <option key={i.id} value={i.id}>{i.specimen_id} · {i.path.split('/').at(-1)}</option>)}</select></label><Button variant="outline" isDisabled={!ready || !sample} onPress={() => void detect(false)}>检测样本</Button>
    </div> : pane === 'review' ? result && job ? <div className="review-form"><p className="model-note">复核结果保留在当前检测记录中。</p><label className="field">人工复核<select aria-label="人工复核" value={review} onChange={e => setReview(e.target.value as Quality)}>{Object.entries(qualities).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
      <label className="field">备注<input value={note} maxLength={500} onChange={e => setNote(e.target.value)} /></label><Button variant="outline" isDisabled={busy || (review === (job.review?.quality ?? 'unknown') && note === (job.review?.note ?? ''))} onPress={() => void run(() => api(`/api/jobs/${job.id}/review`, 'POST', { quality: review, note }))}>保存复核</Button></div> : <div className="empty">完成检测后可复核</div>
      : <JobLog job={job} busy={busy} run={run} />}
    <input ref={upload} hidden type="file" accept="image/png,image/jpeg,image/bmp,image/tiff" aria-label="导入待检测图片" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void detectFile(file) }} />
  </section></div>
}
