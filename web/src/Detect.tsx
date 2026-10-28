import { useEffect, useRef, useState } from 'react'
import { Button } from '@heroui/react'
import { Camera, FileImage, ScanLine, Trash2 } from 'lucide-react'
import { api, artifact, defectLabels, query, response, statuses, type Box, type Job, type PageProps, type Quality } from './api'
import BoxCanvas from './BoxCanvas'
import JobLog from './JobLog'
import Pager from './Pager'

const faces: Record<string, string> = { top: '正面', bottom: '背面' }

export default function Detect({ data, jobs, camera, busy, run, navigate, onDirty, records = false }: PageProps & { records?: boolean }) {
  const [selected, setSelected] = useState('')
  const [pane, setPane] = useState('operate')
  const [visual, setVisual] = useState(records ? 'result' : 'live')
  const [picture, setPicture] = useState('source.png')
  const [device, setDevice] = useState('cuda')
  const [route, setRoute] = useState('')
  const [confidence, setConfidence] = useState(0.5)
  const [quality, setQuality] = useState<Quality>('unknown')
  const [note, setNote] = useState('')
  const [boxes, setBoxes] = useState<Box[]>([])
  const [reviewTool, setReviewTool] = useState('')
  const [reviewView, setReviewView] = useState('top')
  const [label, setLabel] = useState(defectLabels[0])
  const [specimen, setSpecimen] = useState('')
  const [boxPage, setBoxPage] = useState(0)
  const [recordPage, setRecordPage] = useState(0)
  const [filter, setFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('')
  const [date, setDate] = useState('')
  const [mobilePane, setMobilePane] = useState(records ? 'list' : 'image')
  const upload = useRef<HTMLInputElement>(null)
  const history = jobs.filter(j => j.kind === 'detect' && (!typeFilter || j.tool_type === typeFilter) && (!date || j.created_at.startsWith(date)) && (filter === 'all' || (filter === 'pending' ? j.status === 'succeeded' && (!j.review || j.review.quality === 'unknown') : j.review?.quality === filter)))
  const job = history.find(j => j.id === selected) ?? history[0]
  const result = job?.status === 'succeeded' ? job.result : undefined
  const reviewBase = job?.review ?? { quality: 'unknown', note: '', boxes: result?.boxes ?? [], tool_type: result?.tool_type ?? '', view: result?.view ?? 'top' }
  const reviewDirty = !!result && (quality !== reviewBase.quality || note !== reviewBase.note || reviewTool !== (reviewBase.tool_type ?? '') || reviewView !== (reviewBase.view ?? 'top') || JSON.stringify(boxes) !== JSON.stringify(reviewBase.boxes))
  useEffect(() => { onDirty(reviewDirty); return () => onDirty(false) }, [reviewDirty, onDirty])
  const active = jobs.some(j => ['running', 'stopping'].includes(j.status))
  const ready = !active && !busy && !reviewDirty && !!data.schemes.length
  const settings = { device, min_confidence: confidence, ...(route ? { route_tool: route.split('/')[0], route_view: route.split('/')[1] } : {}) }
  const resetReview = () => {
    setQuality(job?.review?.quality ?? 'unknown'); setNote(job?.review?.note ?? '')
    setBoxes(job?.review?.boxes ?? job?.result?.boxes ?? [])
    setReviewTool(job?.review?.tool_type ?? job?.result?.tool_type ?? '')
    setReviewView(job?.review?.view ?? job?.result?.view ?? 'top'); setBoxPage(0); setSpecimen('')
  }
  useEffect(resetReview, [job?.id, job?.review?.at])
  const detect = (file?: File) => run(async () => {
    const next = file ? await (await response(`/api/detections/upload?${query(settings)}`, { method: 'POST', body: file })).json() as Job
      : await api<Job>('/api/detections', 'POST', { ...settings, camera: true })
    setSelected(next.id); setVisual('result'); setPane('operate'); setPicture('source.png'); setMobilePane('image')
  })
  const saveReview = () => run(() => api(`/api/jobs/${job!.id}/review`, 'POST', { quality, note, boxes, tool_type: reviewTool, view: reviewView }))
  const reviewSaved = !!job?.review && quality === job.review.quality && note === job.review.note && reviewTool === job.review.tool_type && reviewView === job.review.view && JSON.stringify(boxes) === JSON.stringify(job.review.boxes)
  const adopt = () => run(() => api(`/api/jobs/${job!.id}/adopt`, 'POST', { tool_type: reviewTool, view: reviewView, specimen_id: specimen,
    quality: data.specimens.find(s => s.tool_type === reviewTool && s.specimen_id === specimen)?.quality ?? 'unknown' }))
  const shownBoxes = pane === 'review' ? boxes : result?.boxes ?? []
  const pages = Math.max(1, Math.ceil(shownBoxes.length / 4))
  const recordPages = Math.max(1, Math.ceil(history.length / 7))
  const choose = (item: Job) => { setSelected(item.id); setVisual('result'); setPane('operate'); setPicture('source.png'); setMobilePane('image') }
  return <div className={`${records ? 'records-grid' : 'detect-grid'} mobile-${mobilePane}`}>
    <div className="workspace-mobile-tabs pane-tabs">{[...(records ? [['list', '记录列表']] : []), ['image', '画面'], ['controls', '操作']].map(([value, name]) => <button key={value} className={mobilePane === value ? 'active' : ''} onClick={() => setMobilePane(value)}>{name}</button>)}</div>
    {records && <section className="panel record-library" inert={reviewDirty}><div className="record-filters"><select aria-label="记录刀具类型" value={typeFilter} onChange={e => { setTypeFilter(e.target.value); setRecordPage(0) }}><option value="">全部类型</option>{[...new Set(jobs.filter(j => j.kind === 'detect').map(j => j.tool_type))].map(value => <option key={value}>{value}</option>)}</select>
      <select aria-label="记录结果筛选" value={filter} onChange={e => { setFilter(e.target.value); setRecordPage(0) }}><option value="all">全部结果</option><option value="pending">待复核</option><option value="good">复核合格</option><option value="defect">复核不合格</option></select>
      <input aria-label="记录日期" type="date" value={date} onChange={e => { setDate(e.target.value); setRecordPage(0) }} /></div>
      <div className="record-list">{history.slice(Math.min(recordPage, recordPages - 1) * 7, (Math.min(recordPage, recordPages - 1) + 1) * 7).map(item => <button key={item.id} className={item.id === job?.id ? 'record-row selected' : 'record-row'} onClick={() => choose(item)}><span>{item.created_at.replace('T', ' ')}</span><strong>{item.tool_type === 'auto' ? '类型待确认' : `${item.tool_type} · ${faces[item.view] ?? ''}`}</strong><small>{item.result?.label ?? statuses[item.status]}{item.review ? ` · ${item.review.quality === 'good' ? '复核合格' : item.review.quality === 'defect' ? '复核不合格' : '待复核'}` : ''}</small></button>)}</div>
      <Pager page={Math.min(recordPage, recordPages - 1)} pages={recordPages} onChange={value => { setRecordPage(value); setSelected('') }} label="记录" />
    </section>}
    <section className="panel detection-viewer"><div className="pane-tabs" aria-label="检测画面">{!records && <button className={visual === 'live' ? 'active' : ''} onClick={() => setVisual('live')}>实时画面</button>}<button className={visual === 'result' ? 'active' : ''} onClick={() => setVisual('result')}>检测结果</button>
      {!records && visual === 'result' && <select aria-label="选择检测记录" disabled={reviewDirty} value={job?.id ?? ''} onChange={e => setSelected(e.target.value)}>{!history.length && <option value="">暂无记录</option>}{history.map(item => <option key={item.id} value={item.id}>{item.created_at.replace('T', ' ')} · {item.result?.label ?? statuses[item.status]}</option>)}</select>}</div>
      {visual === 'live' ? <div className="detection-live">{camera.connected && !camera.error ? <img src="/api/camera/live" alt="实时相机画面" /> : <div className="stage-empty"><Camera size={28} /><span>{camera.error || '相机未连接'}</span><Button variant="outline" isDisabled={busy} onPress={() => void run(() => api('/api/camera/connect', 'POST', {}))}>连接相机</Button></div>}</div>
      : result && job ? <><div className="result-summary"><div><span className="eyebrow">当前可见面</span><strong>{result.label}</strong></div><div><span className="eyebrow">刀具</span><span>{result.tool_type ?? '待确认'} · {faces[result.view ?? ''] ?? '面待确认'}</span></div><div><span className="eyebrow">异常分数</span><span className="mono">{result.anomaly_score?.toFixed(4) ?? '—'}</span></div></div>
        <div className="pane-tabs">{[['source.png', pane === 'review' ? '原图标注' : '原图与缺陷'], ...(result.models ? [['heatmap.png', '异常热力图'], ['aligned.png', '对齐图']] : [])].map(([value, name]) => <button key={value} className={picture === value ? 'active' : ''} onClick={() => setPicture(value)}>{name}</button>)}</div>
        {picture === 'source.png' ? <BoxCanvas src={artifact(job.id, 'source.png')} width={result.source_size[0]} height={result.source_size[1]} boxes={shownBoxes} label={label} onChange={pane === 'review' ? value => { setBoxes(value); setQuality('defect'); setBoxPage(Math.floor((value.length - 1) / 4)) } : undefined} />
          : <div className="image-stage"><img src={artifact(job.id, picture)} alt={picture === 'heatmap.png' ? '原图上的异常热力图' : '模型对齐输入'} /></div>}
        <div className="image-caption"><span>{result.recognition.method}{result.recognition.similarity !== null ? ` · 相似度 ${result.recognition.similarity.toFixed(3)}` : ''}</span><a className="text-link" href={artifact(job.id, 'record.zip')}>导出记录</a></div>
      </> : <div className="empty-state"><ScanLine size={28} /><span>{job && ['running', 'stopping'].includes(job.status) ? '正在检测…' : job?.error || '暂无检测结果'}</span>{job && <Button variant="outline" onPress={() => setPane('logs')}>查看任务</Button>}</div>}
    </section>
    <section className="panel detect-sidebar"><div className="pane-tabs">{[['operate', records ? '结果' : '检测'], ...(!records ? [['settings', '设置']] : []), ['review', '复核'], ['logs', '任务']].map(([value, name]) => <button key={value} className={pane === value ? 'active' : ''} onClick={() => { setPane(value); if (value === 'review') { setVisual('result'); setPicture('source.png') } }}>{name}</button>)}</div>
      {pane === 'operate' ? <div className="detect-primary">{!records && <><Button isDisabled={!ready || !camera.connected || !!camera.error} onPress={() => void detect()}><Camera size={16} />拍照检测</Button><Button variant="outline" isDisabled={!ready} onPress={() => upload.current?.click()}><FileImage size={16} />导入图片检测</Button>{!data.schemes.length && <Button variant="ghost" onPress={() => navigate('models')}>先创建并启用检测方案</Button>}</>}
        {result && <><div className="result-detail"><span>已知缺陷</span><strong>{result.boxes.length} 处</strong></div>{result.experimental && <span className="status status-running">实验模型 · 未校准</span>}
          <p className="model-note">{result.defect_status ?? '请在设置中人工指定类型和拍摄面后重新检测'}</p>
          <DefectRows boxes={shownBoxes} page={boxPage} />
          {pages > 1 && <Pager page={Math.min(boxPage, pages - 1)} pages={pages} onChange={setBoxPage} label="缺陷" />}
          {job?.review && <span className="model-note">复核：{job.review.quality === 'good' ? '当前面合格' : job.review.quality === 'defect' ? '当前面不合格' : '待确认'} · {job.reviews?.length ?? 1} 次</span>}
        </>}
      </div> : pane === 'settings' ? <div className="settings-form"><label className="field">类型与拍摄面<select aria-label="检测类型与拍摄面" value={route} onChange={e => setRoute(e.target.value)}><option value="">自动识别</option>{data.schemes.map(s => <option key={`${s.tool_type}/${s.view}`} value={`${s.tool_type}/${s.view}`}>{s.tool_type} · {faces[s.view]}</option>)}</select></label>
        <label className="field">运行设备<select value={device} onChange={e => setDevice(e.target.value)}><option value="cuda">GPU · CUDA</option><option value="cpu">CPU</option></select></label><label className="field">缺陷检测分数门槛<input aria-label="缺陷检测分数门槛" type="number" min="0" max="1" step="0.05" value={confidence} onChange={e => setConfidence(Number(e.target.value))} /></label>
      </div> : pane === 'review' ? result && job ? <div className="review-form"><div className="form-row"><label className="field">刀具类型<input aria-label="复核刀具类型" list="review-tools" value={reviewTool} onChange={e => setReviewTool(e.target.value)} /><datalist id="review-tools">{[...new Set(data.specimens.map(s => s.tool_type))].map(value => <option key={value}>{value}</option>)}</datalist></label><label className="field">拍摄面<select aria-label="复核拍摄面" value={reviewView} onChange={e => setReviewView(e.target.value)}><option value="top">正面</option><option value="bottom">背面</option></select></label></div>
        <label className="field">当前面结论<select aria-label="人工复核结论" value={quality} onChange={e => { setQuality(e.target.value as Quality); if (e.target.value === 'good') setBoxes([]) }}><option value="unknown">待确认</option><option value="good">合格</option><option value="defect">不合格</option></select></label>
        <label className="field">画框类别<select aria-label="复核画框类别" value={label} onChange={e => setLabel(e.target.value)}>{defectLabels.map(value => <option key={value}>{value}</option>)}</select></label>
        <div className="review-box-list">{boxes.slice(Math.min(boxPage, pages - 1) * 4, (Math.min(boxPage, pages - 1) + 1) * 4).map((box, offset) => { const index = Math.min(boxPage, pages - 1) * 4 + offset; return <div className="annotation-box-row" key={index}><span>{index + 1}</span><select aria-label={`复核缺陷 ${index + 1} 类别`} value={box.label} onChange={e => setBoxes(boxes.map((item, i) => i === index ? { ...item, label: e.target.value } : item))}>{defectLabels.map(value => <option key={value}>{value}</option>)}</select><Button size="sm" variant="ghost" isIconOnly aria-label={`删除复核缺陷 ${index + 1}`} onPress={() => setBoxes(boxes.filter((_, i) => i !== index))}><Trash2 size={13} /></Button></div> })}</div>
        {pages > 1 && <Pager page={Math.min(boxPage, pages - 1)} pages={pages} onChange={setBoxPage} label="复核缺陷" />}
        <label className="field">备注<input value={note} maxLength={500} onChange={e => setNote(e.target.value)} /></label><div className="toolbar-actions"><Button isDisabled={busy || reviewSaved || quality === 'unknown' || !reviewTool || (quality === 'defect' && !boxes.length)} onPress={() => void saveReview()}>保存复核</Button>{reviewDirty && <Button variant="ghost" onPress={resetReview}>撤销修改</Button>}</div>
        <div className="form-row"><label className="field">实物编号<input aria-label="复核实物编号" value={specimen} onChange={e => setSpecimen(e.target.value)} /></label><Button variant="outline" isDisabled={busy || !reviewSaved || !specimen.trim() || !!job.adopted_image} onPress={() => void adopt()}>{job.adopted_image ? '已加入样本' : '加入样本'}</Button></div>
      </div> : <div className="empty">选择已完成的检测记录</div> : <JobLog job={job} busy={busy} run={run} />}
    </section><input hidden ref={upload} type="file" aria-label="导入待检测图片" accept="image/png,image/jpeg,image/bmp,image/tiff" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void detect(file) }} />
  </div>
}

function DefectRows({ boxes, page }: { boxes: Box[]; page: number }) {
  return <div className="defect-results">{boxes.slice(page * 4, (page + 1) * 4).map((box, i) => <div key={i}><span>{page * 4 + i + 1}. {box.label}</span><span className="mono">{box.confidence === undefined ? '人工标注' : `${(box.confidence * 100).toFixed(1)}%`}</span></div>)}</div>
}
