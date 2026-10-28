import { useEffect, useState } from 'react'
import { Button } from '@heroui/react'
import { ArrowRight, Images, ScanLine } from 'lucide-react'
import { api, imageUrl, qualities, splits, type PageProps, type Quality, type Run, type Specimen, type Split } from './api'

export default function Review({ tool, view, data, busy, run, navigate }: PageProps) {
  const samples = data.images.filter(i => i.tool_type === tool && i.view === view)
  const specimens = data.specimens.filter(s => s.tool_type === tool)
  const [filter, setFilter] = useState('all')
  const visible = samples.filter(i => filter === 'all' || i.quality === filter)
  const [selected, setSelected] = useState(samples[0]?.id ?? '')
  const current = visible.find(i => i.id === selected) ?? visible[0]
  const adopted = samples.filter(i => i.included && i.quality === 'good')
  const learning = adopted.filter(i => i.split === 'train')
  const adopt = (ids: string[], included: boolean) => run(async () => {
    if (included) {
      for (const item of specimens.filter(s => s.quality === 'good' && s.split === 'unassigned' && samples.some(i => ids.includes(i.id) && i.specimen_id === s.specimen_id))) {
        await api('/api/specimens', 'PUT', { ...item, split: 'train' })
      }
    }
    await Promise.all(ids.map(id => api(`/api/images/${id}`, 'PATCH', { included })))
  })

  if (!samples.length) return <section className="empty-state"><Images size={32} strokeWidth={1.3} /><h2>还没有待筛选的图片</h2>
    <p>先拍摄或导入这组刀具的好件、坏件图片。</p><Button onPress={() => navigate('collect')}>前往拍摄样本<ArrowRight size={16} /></Button>
    <Button variant="ghost" isDisabled={busy} onPress={() => void run(() => api('/api/import', 'POST'))}><ScanLine size={14} />扫描本机旧采集目录</Button></section>

  return <>
    <div className="review-toolbar"><div className="filter-tabs" aria-label="按好坏筛选">{[['all', '全部'], ['good', '好件'], ['defect', '坏件']].map(([value, name]) => <button key={value}
      className={filter === value ? 'active' : ''} aria-pressed={filter === value} onClick={() => setFilter(value)}>{name}<span>{samples.filter(i => value === 'all' || i.quality === value).length}</span></button>)}</div>
      <div className="flex gap-2"><Button variant="outline" size="sm" isDisabled={busy || !visible.length} onPress={() => void adopt(visible.map(i => i.id), true)}>采用当前全部</Button>
        <Button variant="ghost" size="sm" isDisabled={busy || !visible.length} onPress={() => void adopt(visible.map(i => i.id), false)}>排除当前全部</Button></div></div>
    <div className="review-grid"><section className="panel review-library"><div className="sample-grid">{visible.map(item => <article key={item.id} className={current?.id === item.id ? 'sample selected' : 'sample'}>
      <button className="sample-image" aria-label={`查看 ${item.specimen_id} ${item.path.split('/').at(-1)}`} aria-pressed={current?.id === item.id} onClick={() => setSelected(item.id)}><img src={imageUrl(item.id)} alt={item.specimen_id} loading="lazy" /></button>
      <div className="sample-info"><span>{item.specimen_id}</span><label><input type="checkbox" aria-label={`采用 ${item.path.split('/').at(-1)}`} checked={item.included} disabled={busy}
        onChange={e => void adopt([item.id], e.target.checked)} />采用</label></div></article>)}</div>{!visible.length && <div className="empty">当前分类没有图片</div>}</section>
      <section className="panel review-viewer"><div className="panel-toolbar"><h2>{current?.specimen_id ?? '图片预览'}</h2><span className="muted">{current && qualities[current.quality]}</span></div>
        <div className="review-image">{current && <img src={imageUrl(current.id)} alt="选中样本原图" />}</div>
        <div className="image-caption"><span>{current ? `${current.width} × ${current.height} px` : ''}</span><span>{current ? current.included ? '已采用' : '未采用' : ''}</span></div></section></div>
    <div className="step-actions"><div><strong>已采用 {adopted.length} 张好件图片</strong><span className="muted">{learning.length ? '可以开始创建正常外观参考' : adopted.length ? '请在高级设置中把学习好件分到训练组' : '至少采用一张好件图片后继续'}</span></div>
      <Button isDisabled={!learning.length} onPress={() => navigate('models')}>下一步：创建模型<ArrowRight size={16} /></Button></div>
    <details className="advanced specimen-settings"><summary>高级设置：实物分组与缺陷类别</summary><p className="field-help">同一把刀具的全部图片共用分组。验证和测试需要另外的实物，重复拍照不能替代。</p>
      <div className="table-scroll"><table><thead><tr><th>实物编号</th><th>好坏标签</th><th>数据分组</th><th>真实缺陷类别</th><th /></tr></thead><tbody>
        {specimens.map(item => <SpecimenRow key={item.specimen_id} item={item} busy={busy} run={run} />)}</tbody></table></div></details>
  </>
}

function SpecimenRow({ item, busy, run }: { item: Specimen; busy: boolean; run: Run }) {
  const [quality, setQuality] = useState(item.quality)
  const [split, setSplit] = useState(item.split)
  const [category, setCategory] = useState(item.category)
  useEffect(() => { setQuality(item.quality); setSplit(item.split); setCategory(item.category) }, [item.quality, item.split, item.category])
  return <tr><td>{item.specimen_id}</td><td><select aria-label={`${item.specimen_id} 好坏标签`} value={quality} onChange={e => { setQuality(e.target.value as Quality); if (e.target.value !== 'defect') setCategory('') }}>
    {Object.entries(qualities).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></td>
    <td><select aria-label={`${item.specimen_id} 数据分组`} value={split} onChange={e => setSplit(e.target.value as Split)}>{Object.entries(splits).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></td>
    <td><input aria-label={`${item.specimen_id} 缺陷类别`} value={category} disabled={quality !== 'defect'} onChange={e => setCategory(e.target.value)} /></td>
    <td><Button size="sm" variant="outline" isDisabled={busy || (quality === item.quality && split === item.split && category === item.category)}
      onPress={() => void run(() => api('/api/specimens', 'PUT', { ...item, quality, split, category }))}>保存</Button></td></tr>
}
