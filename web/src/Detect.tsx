import { useEffect, useRef, useState } from 'react'
import { Button } from '@heroui/react'
import { Camera, FileImage, ScanLine } from 'lucide-react'
import { api, artifact, jobTitle, qualities, query, response, statuses, type Job, type PageProps, type Quality } from './api'
import JobLog from './JobLog'

export default function Detect({ tool, view, data, jobs, camera, busy, run }: PageProps) {
  const trained = jobs.filter(job => job.kind === 'train' && job.status === 'succeeded' && job.tool_type === tool && job.view === view)
  const anomalies = trained.filter(job => job.model === 'patchcore')
  const [anomalyId, setAnomalyId] = useState('')
  const anomaly = anomalies.find(job => job.id === anomalyId) ?? anomalies[0]
  const compatible = trained.filter(job => job.model === 'classifier' && job.settings && anomaly?.settings &&
    JSON.stringify(job.settings.roi) === JSON.stringify(anomaly.settings.roi) && JSON.stringify(job.settings.source_size) === JSON.stringify(anomaly.settings.source_size))
  const [classifier, setClassifier] = useState('')
  const [device, setDevice] = useState('cuda')
  const [confidence, setConfidence] = useState(0.7)
  const samples = data.images.filter(item => item.tool_type === tool && item.view === view)
  const [sample, setSample] = useState('')
  const [selectedJob, setSelectedJob] = useState('')
  const [review, setReview] = useState<Quality>('unknown')
  const [note, setNote] = useState('')
  const upload = useRef<HTMLInputElement>(null)
  const history = jobs.filter(job => job.kind === 'detect' && job.tool_type === tool && job.view === view)
  const job = history.find(job => job.id === selectedJob) ?? history[0]
  const active = jobs.some(job => ['running', 'stopping'].includes(job.status))
  const ready = !!anomaly && !busy && !active
  const classificationJob = !anomaly?.experimental && compatible.some(item => item.id === classifier) ? classifier : null
  const settings = { anomaly_job: anomaly?.id ?? '', classifier_job: classificationJob, device, min_confidence: confidence }

  useEffect(() => { setClassifier('') }, [anomaly?.id])
  useEffect(() => { setReview(job?.review?.quality ?? 'unknown'); setNote(job?.review?.note ?? '') }, [job?.id, job?.review?.quality, job?.review?.note])

  const detect = (fromCamera: boolean) => run(async () => {
    const result = await api<Job>('/api/detections', 'POST', { ...settings, camera: fromCamera, image_id: fromCamera ? null : sample })
    setSelectedJob(result.id)
  })
  const detectFile = (file: File) => run(async () => {
    const params = query({ anomaly_job: settings.anomaly_job, device, min_confidence: confidence,
      ...(classificationJob ? { classifier_job: classificationJob } : {}) })
    const result = await response(`/api/detections/upload?${params}`, { method: 'POST', body: file })
    setSelectedJob((await result.json()).id)
  })
  const result = job?.status === 'succeeded' ? job.result : undefined

  return <>
    <section className="panel detection-controls">
      <div className="detect-models"><label className="field">异常模型<select value={anomaly?.id ?? ''} onChange={e => setAnomalyId(e.target.value)}>
        {!anomalies.length && <option value="">暂无已训练模型</option>}{anomalies.map(item => <option key={item.id} value={item.id}>{jobTitle(item)}</option>)}
      </select></label><label className="field">缺陷分类模型<select disabled={!anomaly || anomaly.experimental} value={classificationJob ?? ''} onChange={e => setClassifier(e.target.value)}>
        <option value="">不分类</option>{compatible.map(item => <option key={item.id} value={item.id}>{jobTitle(item)}</option>)}
      </select></label></div>
      <div className="detection-actions"><label className="field sample-select">样本图片<select value={sample} onChange={e => setSample(e.target.value)}><option value="">选择样本</option>
        {samples.map(item => <option key={item.id} value={item.id}>{item.specimen_id} · {item.path.split('/').at(-1)}</option>)}</select></label>
        <Button variant="outline" isDisabled={!ready || !sample} onPress={() => void detect(false)}><ScanLine size={16} />检测样本</Button>
        <Button variant="outline" isDisabled={!ready} onPress={() => upload.current?.click()}><FileImage size={16} />导入检测</Button>
        <Button isDisabled={!ready || !camera.connected} onPress={() => void detect(true)}><Camera size={16} />拍照检测</Button>
        <input ref={upload} hidden type="file" accept="image/png,image/jpeg,image/bmp,image/tiff" aria-label="导入待检测图片"
          onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void detectFile(file) }} />
      </div>
      <details className="advanced"><summary>运行设置</summary><div className="form-row"><label className="field">运行设备<select value={device} onChange={e => setDevice(e.target.value)}><option value="cuda">GPU · CUDA</option><option value="cpu">CPU</option></select></label>
        <label className="field">分类置信度门槛<input type="number" min="0" max="1" step="0.05" value={confidence} onChange={e => setConfidence(Number(e.target.value))} /></label></div></details>
      {anomaly?.experimental && <p className="model-note">当前模型未校准，输出原始异常分数。热力图颜色按单张图缩放，不用于合格判断。</p>}
    </section>
    <div className="history-toolbar"><h2>检测记录</h2><select aria-label="选择检测记录" value={job?.id ?? ''} onChange={e => setSelectedJob(e.target.value)}>
      {!history.length && <option value="">暂无检测记录</option>}{history.map(item => <option key={item.id} value={item.id}>{item.created_at.replace('T', ' ')} · {item.result?.label ?? statuses[item.status]}</option>)}
    </select></div>
    {job ? <>
      {result && <section className="panel result-panel"><div className="result-summary"><div><span className="eyebrow">检测结果</span><div className={`result-label ${result.label === '异常' ? 'abnormal' : ''}`}>{result.label}</div></div>
        <div><span className="eyebrow">异常分数</span><div className="score mono">{result.anomaly_score.toFixed(4)}</div></div>
        <div><span className="eyebrow">缺陷分类</span><div className="classification">{result.classification?.decision ?? (result.label === '异常' ? '待复核' : '—')}</div>
          {result.classification && <span className="muted text-xs">{result.classification.category} · {(result.classification.confidence * 100).toFixed(1)}%</span>}</div>
        <a className="text-link" href={artifact(job.id, 'result.json')} target="_blank" rel="noreferrer">结果 JSON</a></div>
        <div className="result-images">{[['source.png', '原图'], ['input.png', '模型输入'], ['predictions/input.heatmap.png', '异常热力图']].map(([name, title]) => <figure key={name}>
          <div><img src={artifact(job.id, name)} alt={title} /></div><figcaption>{title}</figcaption></figure>)}</div>
        <div className="review-form"><label className="field">人工复核<select value={review} onChange={e => setReview(e.target.value as Quality)}>{Object.entries(qualities).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
          <label className="field review-note">备注<input value={note} maxLength={500} onChange={e => setNote(e.target.value)} /></label>
          <Button variant="outline" isDisabled={busy || (review === (job.review?.quality ?? 'unknown') && note === (job.review?.note ?? ''))}
            onPress={() => void run(() => api(`/api/jobs/${job.id}/review`, 'POST', { quality: review, note }))}>保存复核</Button></div>
      </section>}
      <JobLog job={job} busy={busy} run={run} />
    </> : <div className="empty detection-empty"><ScanLine size={30} strokeWidth={1.3} /><span>{anomaly ? '选择图片或拍照检测' : '请先完成 PatchCore 实验建库或训练'}</span></div>}
  </>
}
