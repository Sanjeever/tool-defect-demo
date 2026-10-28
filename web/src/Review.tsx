import { useState } from 'react'
import { Button } from '@heroui/react'
import { Camera, Trash2 } from 'lucide-react'
import { api, defectLabels, imageUrl, qualities, splits, type Box, type PageProps, type Quality, type Sample } from './api'
import BoxCanvas from './BoxCanvas'
import Pager from './Pager'

export default function Review(props: PageProps) {
  const { tool, view, data, busy, run, navigate } = props
  const [filter, setFilter] = useState('all')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState('')
  const [dirty, setDirty] = useState(false)
  const [pane, setPane] = useState('annotate')
  const samples = data.images.filter(i => i.tool_type === tool && i.view === view && (filter === 'all' || (filter === 'pending' ? !i.annotated : i.quality === filter)))
  const pages = Math.max(1, Math.ceil(samples.length / 8))
  const shown = samples.slice(Math.min(page, pages - 1) * 8, (Math.min(page, pages - 1) + 1) * 8)
  const current = samples.find(i => i.id === selected) ?? shown[0]
  const specimen = data.specimens.find(s => s.tool_type === tool && s.specimen_id === current?.specimen_id)
  return <div className={`annotation-layout annotation-pane-${pane}`}>
    <section className="panel annotation-library"><div className="panel-toolbar"><h2>样本</h2><Button size="sm" variant="ghost" isDisabled={dirty} onPress={() => navigate('collect')}><Camera size={14} />采集</Button></div>
      <div className="library-filter"><select aria-label="样本筛选" disabled={dirty} value={filter} onChange={e => { setFilter(e.target.value); setPage(0) }}>
        <option value="all">全部图片</option><option value="pending">待标注</option><option value="good">当前面合格</option><option value="defect">当前面不合格</option></select></div>
      <div className="annotation-thumbnails">{shown.map(item => <button key={item.id} disabled={dirty && current?.id !== item.id} className={item.id === current?.id ? 'annotation-thumb selected' : 'annotation-thumb'} onClick={() => { setSelected(item.id); setPane('annotate') }}>
        <img src={imageUrl(item.id)} alt={item.specimen_id} /><span>{item.specimen_id}</span><small>{item.annotated ? qualities[item.quality] : '待标注'}</small></button>)}
        {!samples.length && <div className="empty">暂无图片</div>}</div>
      <Pager page={Math.min(page, pages - 1)} pages={pages} onChange={value => { if (!dirty) { setPage(value); setSelected('') } }} label="样本" />
    </section>
    {current ? <><div className="annotation-mobile pane-tabs"><button onClick={() => setPane('library')}>图片列表</button><button onClick={() => setPane('annotate')}>标注</button></div>
      <Annotation key={current.id} sample={current} {...props} onDirty={setDirty} />
      <section className="panel annotation-specimen"><div className="panel-toolbar"><h2>实物分组</h2></div><div className="settings-form"><span>{current.specimen_id}</span>
        <label className="field">数据分组<select aria-label="实物数据分组" value={specimen?.split ?? 'unassigned'} disabled={busy} onChange={e => void run(() => api('/api/specimens', 'PUT', { ...specimen, split: e.target.value }))}>
          {Object.entries(splits).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
        <p className="model-note">同一实物的正反面和重复拍摄共用分组。</p></div></section>
    </> : <div className="empty-state"><Button onPress={() => navigate('collect')}>拍摄或导入样本</Button></div>}
  </div>
}

function Annotation({ sample, busy, run, data, onDirty }: PageProps & { sample: Sample; onDirty: (dirty: boolean) => void }) {
  const [boxes, setBoxes] = useState<Box[]>(sample.boxes)
  const [quality, setQuality] = useState<Quality>(sample.quality)
  const [view, setView] = useState(sample.view)
  const [label, setLabel] = useState(defectLabels[0])
  const [selected, setSelected] = useState(-1)
  const [page, setPage] = useState(0)
  const [dirty, setDirty] = useState(false)
  const change = () => { setDirty(true); onDirty(true) }
  const save = () => run(async () => {
    const specimen = data.specimens.find(s => s.tool_type === sample.tool_type && s.specimen_id === sample.specimen_id)!
    await api(`/api/images/${sample.id}`, 'PATCH', { boxes, quality, view, annotated: true, included: true })
    if (specimen.split === 'unassigned') await api('/api/specimens', 'PUT', { ...specimen, split: 'train' })
    setDirty(false); onDirty(false)
  })
  const pages = Math.max(1, Math.ceil(boxes.length / 4))
  return <section className="panel annotation-editor"><div className="panel-toolbar"><h2>{sample.specimen_id}</h2><span className="muted">{dirty ? '未保存' : sample.annotated ? '已标注' : '待标注'}</span></div>
    <div className="annotation-controls"><label>当前面<select aria-label="当前面好坏" value={quality} onChange={e => { setQuality(e.target.value as Quality); change() }}><option value="unknown">待确认</option><option value="good">合格</option><option value="defect">不合格</option></select></label>
      <label>拍摄面<select aria-label="标注拍摄面" value={view} onChange={e => { setView(e.target.value); change() }}><option value="top">正面</option><option value="bottom">背面</option></select></label>
      <label>画框类别<select aria-label="画框类别" value={label} onChange={e => setLabel(e.target.value)}>{defectLabels.map(value => <option key={value}>{value}</option>)}</select></label></div>
    <BoxCanvas src={imageUrl(sample.id)} width={sample.width} height={sample.height} boxes={boxes} label={label} selected={selected} onSelect={index => { setSelected(index); setPage(Math.floor(index / 4)) }} onChange={value => { setBoxes(value); setQuality('defect'); change() }} />
    <div className="annotation-boxes">{boxes.slice(Math.min(page, pages - 1) * 4, (Math.min(page, pages - 1) + 1) * 4).map((box, offset) => {
      const index = Math.min(page, pages - 1) * 4 + offset
      return <div className={selected === index ? 'annotation-box-row active' : 'annotation-box-row'} key={index}><button aria-label={`选择缺陷 ${index + 1}`} onClick={() => setSelected(index)}>{index + 1}</button>
        <select aria-label={`缺陷 ${index + 1} 类别`} value={box.label} onChange={e => { setBoxes(boxes.map((item, i) => i === index ? { ...item, label: e.target.value } : item)); change() }}>{defectLabels.map(value => <option key={value}>{value}</option>)}</select>
        <span className="mono">{Math.round(box.width)} × {Math.round(box.height)}</span><Button size="sm" variant="ghost" isIconOnly aria-label={`删除缺陷 ${index + 1}`} onPress={() => { setBoxes(boxes.filter((_, i) => i !== index)); setSelected(-1); change() }}><Trash2 size={14} /></Button></div>
    })}{!boxes.length && <span className="muted">未标注缺陷区域</span>}</div>
    <div className="annotation-footer"><Pager page={Math.min(page, pages - 1)} pages={pages} onChange={setPage} label="缺陷" /><div className="toolbar-actions">
      {dirty && <Button size="sm" variant="ghost" onPress={() => { setBoxes(sample.boxes); setQuality(sample.quality); setView(sample.view); setDirty(false); onDirty(false) }}>撤销修改</Button>}
      <Button size="sm" isDisabled={busy || quality === 'unknown' || (quality === 'defect' ? !boxes.length : !!boxes.length)} onPress={() => void save()}>确认并采用</Button></div></div>
  </section>
}
