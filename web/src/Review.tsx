import { useEffect, useState } from 'react'
import { Button } from '@heroui/react'
import { ArrowRight, ChevronLeft, ChevronRight, Images, ScanLine } from 'lucide-react'
import { api, imageUrl, qualities, splits, type PageProps, type Quality, type Run, type Specimen, type Split } from './api'
import Pager from './Pager'
import usePanelSize from './usePanelSize'

export default function Review({ tool, view, data, busy, run, navigate }: PageProps) {
  const samples = data.images.filter(i => i.tool_type === tool && i.view === view)
  const specimens = data.specimens.filter(s => s.tool_type === tool)
  const [filter, setFilter] = useState('all')
  const [pane, setPane] = useState('images')
  const [page, setPage] = useState(0)
  const [specimenId, setSpecimenId] = useState('')
  const visible = samples.filter(i => filter === 'all' || i.quality === filter)
  const [selected, setSelected] = useState(samples[0]?.id ?? '')
  const current = visible.find(i => i.id === selected) ?? visible[0]
  const index = current ? visible.indexOf(current) : -1
  const adopted = samples.filter(i => i.included && i.quality === 'good')
  const learning = adopted.filter(i => i.split === 'train')
  const grid = usePanelSize()
  const pageSize = Math.max(1, Math.floor((grid.width + 8) / 118)) * Math.max(1, Math.floor((grid.height + 8) / 116))
  const pages = Math.max(1, Math.ceil(visible.length / pageSize))
  const currentPage = Math.min(page, pages - 1)
  const specimen = specimens.find(s => s.specimen_id === specimenId) ?? specimens[0]
  const adopt = (ids: string[], included: boolean) => run(async () => {
    if (included) for (const item of specimens.filter(s => s.quality === 'good' && s.split === 'unassigned' && samples.some(i => ids.includes(i.id) && i.specimen_id === s.specimen_id))) {
      await api('/api/specimens', 'PUT', { ...item, split: 'train' })
    }
    await Promise.all(ids.map(id => api(`/api/images/${id}`, 'PATCH', { included })))
  })

  if (!samples.length) return <section className="empty-state"><Images size={28} strokeWidth={1.3} /><h2>还没有待筛选的图片</h2><p>先拍摄或导入这组刀具的好件、坏件图片。</p>
    <Button onPress={() => navigate('collect')}>前往拍摄样本<ArrowRight size={15} /></Button>
    <Button variant="ghost" size="sm" isDisabled={busy} onPress={() => void run(() => api('/api/import', 'POST'))}><ScanLine size={14} />扫描本机旧采集目录</Button></section>

  return <>
    <div className="review-toolbar"><div className="filter-tabs" aria-label="按好坏筛选">{[['all', '全部'], ['good', '好件'], ['defect', '坏件']].map(([value, name]) => <button key={value} className={filter === value ? 'active' : ''} aria-pressed={filter === value}
      onClick={() => { setFilter(value); setPage(0); setPane('images') }}>{name}<span>{samples.filter(i => value === 'all' || i.quality === value).length}</span></button>)}</div>
      <div className="toolbar-actions"><Button variant="outline" size="sm" isDisabled={busy || !visible.length} onPress={() => void adopt(visible.map(i => i.id), true)}>全部采用</Button>
        <Button variant="ghost" size="sm" isDisabled={busy || !visible.length} onPress={() => void adopt(visible.map(i => i.id), false)}>全部排除</Button>
        <Button variant={pane === 'settings' ? 'secondary' : 'ghost'} size="sm" onPress={() => setPane(pane === 'settings' ? 'images' : 'settings')}>{pane === 'settings' ? '返回图片' : '实物设置'}</Button></div></div>
    {pane === 'settings' ? <section className="panel specimen-settings"><div className="panel-toolbar"><h2>实物分组与缺陷类别</h2><select aria-label="选择设置实物" value={specimen.specimen_id} onChange={e => setSpecimenId(e.target.value)}>{specimens.map(s => <option key={s.specimen_id}>{s.specimen_id}</option>)}</select></div>
      <p className="model-note">同一把刀具共用分组。验证和测试需要另外的实物。</p><SpecimenEditor key={specimen.specimen_id} item={specimen} busy={busy} run={run} /></section>
      : <div className={`review-grid review-pane-${pane}`}><section className="panel review-library"><div className="sample-grid" ref={grid.ref}>
        {visible.slice(currentPage * pageSize, (currentPage + 1) * pageSize).map(item => <article key={item.id} className={current?.id === item.id ? 'sample selected' : 'sample'}>
          <button className="sample-image" aria-label={`查看 ${item.specimen_id} ${item.path.split('/').at(-1)}`} aria-pressed={current?.id === item.id} onClick={() => { setSelected(item.id); setPane('preview') }}><img src={imageUrl(item.id)} alt={item.specimen_id} loading="lazy" /></button>
          <div className="sample-info"><span title={item.specimen_id}>{item.specimen_id}</span><label><input type="checkbox" aria-label={`采用 ${item.path.split('/').at(-1)}`} checked={item.included} disabled={busy} onChange={e => void adopt([item.id], e.target.checked)} />采用</label></div>
        </article>)}{!visible.length && <div className="empty">当前分类没有图片</div>}</div><Pager page={currentPage} pages={pages} onChange={setPage} label="样本" /></section>
        <section className="panel review-viewer"><div className="panel-toolbar"><Button variant="ghost" size="sm" className="mobile-back" onPress={() => setPane('images')}>返回列表</Button><h2>{current?.specimen_id ?? '图片预览'}</h2>
          <div className="toolbar-actions"><Button variant="ghost" size="sm" isIconOnly aria-label="上一张图片" isDisabled={index <= 0} onPress={() => setSelected(visible[index - 1].id)}><ChevronLeft size={15} /></Button>
            <Button variant="ghost" size="sm" isIconOnly aria-label="下一张图片" isDisabled={index < 0 || index >= visible.length - 1} onPress={() => setSelected(visible[index + 1].id)}><ChevronRight size={15} /></Button></div></div>
          <div className="review-image">{current && <img src={imageUrl(current.id)} alt="选中样本原图" />}</div><div className="image-caption"><span>{current && `${qualities[current.quality]} · ${current.width} × ${current.height}`}</span>
            {current && <Button size="sm" variant="outline" isDisabled={busy} onPress={() => void adopt([current.id], !current.included)}>{current.included ? '取消采用' : '采用这张'}</Button>}</div></section></div>}
    <div className="step-actions"><div><strong>已采用 {adopted.length} 张好件图片</strong><span className="muted">{learning.length ? '可以创建正常外观参考' : adopted.length ? '请在实物设置中分配训练组' : '至少采用一张好件图片后继续'}</span></div>
      <Button isDisabled={!learning.length} onPress={() => navigate('models')}>创建模型<ArrowRight size={15} /></Button></div>
  </>
}

function SpecimenEditor({ item, busy, run }: { item: Specimen; busy: boolean; run: Run }) {
  const [quality, setQuality] = useState(item.quality)
  const [split, setSplit] = useState(item.split)
  const [category, setCategory] = useState(item.category)
  useEffect(() => { setQuality(item.quality); setSplit(item.split); setCategory(item.category) }, [item.quality, item.split, item.category])
  return <div className="specimen-form"><label className="field">好坏标签<select aria-label={`${item.specimen_id} 好坏标签`} value={quality} onChange={e => { setQuality(e.target.value as Quality); if (e.target.value !== 'defect') setCategory('') }}>
    {Object.entries(qualities).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
    <label className="field">数据分组<select aria-label={`${item.specimen_id} 数据分组`} value={split} onChange={e => setSplit(e.target.value as Split)}>{Object.entries(splits).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
    <label className="field">真实缺陷类别<input aria-label={`${item.specimen_id} 缺陷类别`} value={category} disabled={quality !== 'defect'} onChange={e => setCategory(e.target.value)} /></label>
    <Button size="sm" variant="outline" isDisabled={busy || (quality === item.quality && split === item.split && category === item.category)} onPress={() => void run(() => api('/api/specimens', 'PUT', { ...item, quality, split, category }))}>保存实物设置</Button></div>
}
