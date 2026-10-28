import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@heroui/react'
import { Camera, ImagePlus, Play, Square, ScanLine } from 'lucide-react'
import { api, imageUrl, qualities, query, response, splits, type PageProps, type Quality, type Run, type Specimen, type Split } from './api'

export default function Collect({ tool, view, data, camera, busy, run }: PageProps) {
  const samples = data.images.filter(item => item.tool_type === tool && item.view === view)
  const specimens = data.specimens.filter(item => item.tool_type === tool)
  const [specimen, setSpecimen] = useState('good_01')
  const [quality, setQuality] = useState<Quality>(specimens.find(item => item.specimen_id === 'good_01')?.quality ?? 'unknown')
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<string | null>(samples[0]?.id ?? null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [live, setLive] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const upload = useRef<HTMLInputElement>(null)
  const current = samples.find(item => item.id === selected)
  const visible = filter ? samples.filter(item => item.specimen_id === filter) : samples

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])
  const preview = useCallback(async (signal?: AbortSignal) => {
    const result = await response('/api/camera/preview', { method: 'POST', signal })
    const blob = await result.blob()
    if (signal?.aborted) return
    setPreviewUrl(URL.createObjectURL(blob)); setSelected(null)
  }, [])
  useEffect(() => {
    if (!live || !camera.connected) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const next = async () => {
      try {
        await preview(controller.signal)
        if (!controller.signal.aborted) timer = setTimeout(next, 400)
      } catch (error) {
        if (!controller.signal.aborted) { setPreviewError((error as Error).message); setLive(false) }
      }
    }
    void next()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [live, camera.connected, preview])

  const capture = () => run(async () => {
    setLive(false)
    const saved = await api<{ id: string }>('/api/camera/capture', 'POST', { tool_type: tool, view, specimen_id: specimen, quality })
    setSelected(saved.id)
  })
  const importFiles = (files: File[]) => run(async () => {
    for (const file of files) {
      const result = await response(`/api/images/upload?${query({ tool_type: tool, view, specimen_id: specimen, quality })}`,
        { method: 'POST', body: file })
      setSelected((await result.json()).id)
    }
  })

  return <>
    <div className="capture-grid">
      <section className="panel image-panel">
        <div className="panel-toolbar"><span>{current ? `${current.specimen_id} · ${qualities[current.quality]}` : '相机预览'}</span>
          <div className="flex gap-2"><Button variant="ghost" size="sm" isDisabled={!camera.connected || busy || live}
            onPress={() => void run(() => preview())}>刷新预览</Button>
          <Button variant="outline" size="sm" isDisabled={!camera.connected || busy} onPress={() => { setPreviewError(''); setLive(!live) }}>
            {live && camera.connected ? <Square size={13} /> : <Play size={13} />}{live && camera.connected ? '停止预览' : '连续预览'}</Button></div>
        </div>
        <div className="image-stage">{current || previewUrl ? <img src={current ? imageUrl(current.id) : previewUrl} alt={current ? `${current.specimen_id} 原图` : '相机预览'} />
          : <div className="stage-empty"><Camera size={34} strokeWidth={1.3} /><span>{camera.connected ? '点击预览查看画面' : '相机未连接'}</span></div>}</div>
        <div className="image-caption"><span>{current ? current.path.split('/').at(-1) : 'MER-132-30GM'}</span><span>{current ? `${current.width} × ${current.height} px` : '软件触发 · 灰度采集'}</span></div>
        {previewError && <div role="alert" className="inline-error">{previewError}</div>}
      </section>
      <section className="panel capture-form">
        <h2>采集样本</h2>
        <label className="field">实物编号<input value={specimen} list="specimen-ids" onChange={e => {
          setSpecimen(e.target.value)
          const existing = specimens.find(s => s.specimen_id === e.target.value)
          if (existing) setQuality(existing.quality)
        }} /><datalist id="specimen-ids">{specimens.map(s => <option key={s.specimen_id} value={s.specimen_id} />)}</datalist></label>
        <label className="field">好坏标签<select value={quality} onChange={e => setQuality(e.target.value as Quality)}>
          {Object.entries(qualities).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></label>
        <div className="form-spacer" />
        <Button fullWidth isDisabled={!camera.connected || busy || !specimen.trim()} onPress={() => void capture()}><Camera size={16} />拍照保存</Button>
        <Button fullWidth variant="outline" isDisabled={busy || !specimen.trim()} onPress={() => upload.current?.click()}><ImagePlus size={16} />导入图片</Button>
        <input ref={upload} type="file" hidden multiple accept="image/png,image/jpeg,image/bmp,image/tiff" aria-label="导入样本图片"
          onChange={e => { const files = Array.from(e.target.files ?? []); e.target.value = ''; if (files.length) void importFiles(files) }} />
      </section>
    </div>
    <section className="panel samples-panel">
      <div className="panel-toolbar"><h2>样本 <span className="muted count">{samples.length}</span></h2><div className="flex flex-wrap items-center gap-2">
        <select aria-label="按实物筛选" className="compact-select" value={filter} onChange={e => setFilter(e.target.value)}><option value="">全部实物</option>{specimens.map(s => <option key={s.specimen_id}>{s.specimen_id}</option>)}</select>
        <Button size="sm" variant="ghost" isDisabled={busy || !visible.length} onPress={() => void run(() => Promise.all(visible.map(item => api(`/api/images/${item.id}`, 'PATCH', { included: true }))))}>全部选入</Button>
        <Button size="sm" variant="ghost" isDisabled={busy || !visible.length} onPress={() => void run(() => Promise.all(visible.map(item => api(`/api/images/${item.id}`, 'PATCH', { included: false }))))}>全部排除</Button>
        <Button size="sm" variant="outline" isDisabled={busy} onPress={() => void run(() => api('/api/import', 'POST'))}><ScanLine size={14} />扫描已有图片</Button>
      </div></div>
      {visible.length ? <div className="sample-grid">{visible.map(item => <article key={item.id} className={selected === item.id ? 'sample selected' : 'sample'}>
        <button className="sample-image" aria-label={`查看 ${item.specimen_id} ${item.path.split('/').at(-1)}`} aria-pressed={selected === item.id}
          onClick={() => { setLive(false); setSelected(item.id) }}><img src={imageUrl(item.id)} alt={item.specimen_id} loading="lazy" /></button>
        <div className="sample-info"><span>{item.specimen_id}</span><label title="用于数据集"><input type="checkbox" aria-label={`选入 ${item.path.split('/').at(-1)}`}
          checked={item.included} disabled={busy} onChange={e => void run(() => api(`/api/images/${item.id}`, 'PATCH', { included: e.target.checked }))} />选入</label></div>
      </article>)}</div> : <div className="empty">暂无样本</div>}
    </section>
    {specimens.length > 0 && <section className="panel"><div className="panel-toolbar"><h2>实物分组</h2><span className="muted text-xs">同一实物的全部图片共用好坏标签和分组</span></div>
      <div className="table-scroll"><table><thead><tr><th>实物编号</th><th>当前面图片</th><th>好坏标签</th><th>数据分组</th><th>缺陷类别</th><th /></tr></thead>
        <tbody>{specimens.map(item => <SpecimenRow key={item.specimen_id} item={item} count={samples.filter(s => s.specimen_id === item.specimen_id).length} busy={busy} run={run} />)}</tbody></table></div>
    </section>}
  </>
}

function SpecimenRow({ item, count, busy, run }: { item: Specimen; count: number; busy: boolean; run: Run }) {
  const [quality, setQuality] = useState(item.quality)
  const [split, setSplit] = useState(item.split)
  const [category, setCategory] = useState(item.category)
  useEffect(() => { setQuality(item.quality); setSplit(item.split); setCategory(item.category) }, [item.quality, item.split, item.category])
  const changed = quality !== item.quality || split !== item.split || category !== item.category
  return <tr><td className="mono">{item.specimen_id}</td><td className="muted">{count}</td>
    <td><select aria-label={`${item.specimen_id} 好坏标签`} value={quality} onChange={e => { setQuality(e.target.value as Quality); if (e.target.value !== 'defect') setCategory('') }}>
      {Object.entries(qualities).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></td>
    <td><select aria-label={`${item.specimen_id} 数据分组`} value={split} onChange={e => setSplit(e.target.value as Split)}>{Object.entries(splits).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select></td>
    <td><input aria-label={`${item.specimen_id} 缺陷类别`} value={category} disabled={quality !== 'defect'} onChange={e => setCategory(e.target.value)} /></td>
    <td><Button size="sm" variant="outline" isDisabled={busy || !changed} onPress={() => void run(() => api('/api/specimens', 'PUT', { ...item, quality, split, category }))}>保存</Button></td></tr>
}
