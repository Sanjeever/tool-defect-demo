import { useRef, useState } from 'react'
import { Button } from '@heroui/react'
import { ArrowRight, Camera, ImagePlus, PlugZap } from 'lucide-react'
import { api, query, response, type PageProps, type Quality } from './api'

export default function Collect({ tool, view, data, camera, busy, run, navigate }: PageProps) {
  const samples = data.images.filter(i => i.tool_type === tool && i.view === view)
  const specimens = data.specimens.filter(s => s.tool_type === tool)
  const [quality, setQuality] = useState<Quality>('good')
  const [specimen, setSpecimen] = useState(specimens.find(s => s.quality === 'good')?.specimen_id ?? '好件01')
  const [streamError, setStreamError] = useState('')
  const previewError = camera.connected ? camera.error || streamError : ''
  const upload = useRef<HTMLInputElement>(null)
  const own = samples.filter(i => i.specimen_id === specimen)
  const switchQuality = (value: Quality) => {
    setQuality(value)
    setSpecimen(specimens.find(s => s.quality === value)?.specimen_id ?? (value === 'good' ? '好件01' : '坏件01'))
  }
  const capture = () => run(() => api('/api/camera/capture', 'POST', { tool_type: tool, view, specimen_id: specimen, quality }))
  const importFiles = (files: File[]) => run(async () => {
    for (const file of files) await response(`/api/images/upload?${query({ tool_type: tool, view, specimen_id: specimen, quality })}`, { method: 'POST', body: file })
  })

  return <>
    <div className="capture-grid">
      <section className="panel image-panel"><div className="panel-toolbar"><h2>实时画面</h2><span className="preview-status">
        {camera.connected ? <><span className={previewError ? 'dot' : 'dot connected'} />{previewError ? '画面中断' : camera.fps ? `${camera.fps.toFixed(1)} fps` : '正在接收画面'}</> : '尚未连接'}</span></div>
        <div className="image-stage">{camera.connected && !previewError ? <img src="/api/camera/live" alt="实时相机画面" onError={() => setStreamError('预览连接已中断，请断开相机后重新连接')} />
          : <div className="stage-empty"><div className="camera-outline"><Camera size={34} strokeWidth={1.3} /></div><h3>{previewError ? '无法接收相机画面' : '连接相机，查看刀具画面'}</h3>
            <p>{previewError || '请先在 GalaxyView 中关闭设备，释放相机控制权。'}</p>
            <Button isDisabled={busy} onPress={() => void run(async () => {
              if (camera.connected) await api('/api/camera/disconnect', 'POST')
              await api('/api/camera/connect', 'POST', {}); setStreamError('')
            })}><PlugZap size={16} />{busy ? '连接中…' : '连接并预览'}</Button></div>}</div>
        <div className="image-caption"><span>{camera.size ? `${camera.size[0]} × ${camera.size[1]} 原图` : 'MER-132-30GM'}</span><span>预览不自动保存</span></div>
      </section>
      <section className="capture-form panel"><h2>现在拍哪把刀具？</h2>
        <div className="quality-picker" role="radiogroup" aria-label="当前刀具好坏">{(['good', 'defect'] as const).map(value => <label key={value} className={quality === value ? 'quality-option selected' : 'quality-option'}>
          <input type="radio" name="quality" checked={quality === value} onChange={() => switchQuality(value)} />{value === 'good' ? '正常好件' : '缺陷坏件'}</label>)}</div>
        <label className="field">实物编号<input aria-label="实物编号" value={specimen} maxLength={80} list="specimen-ids" onChange={e => {
          setSpecimen(e.target.value); const existing = specimens.find(s => s.specimen_id === e.target.value); if (existing) setQuality(existing.quality)
        }} /><datalist id="specimen-ids">{specimens.map(s => <option key={s.specimen_id} value={s.specimen_id} />)}</datalist><span className="field-help">同一把刀具保持编号不变。</span></label>
        <div className="capture-count" aria-live="polite"><strong>{own.length}</strong><span>张已保存到「{specimen || '当前刀具'}」</span></div>
        <p className="capture-tip">取下再放回，覆盖不同位置和旋转角度。正反面分别采集。</p>
        <Button fullWidth isDisabled={!camera.connected || !!camera.error || busy || !specimen.trim()} onPress={() => void capture()}><Camera size={17} />{busy ? '处理中…' : '拍照保存'}</Button>
        <Button fullWidth variant="outline" isDisabled={busy || !specimen.trim()} onPress={() => upload.current?.click()}><ImagePlus size={16} />导入已有图片</Button>
        <input ref={upload} type="file" hidden multiple accept="image/png,image/jpeg,image/bmp,image/tiff" aria-label="导入样本图片" onChange={e => {
          const files = Array.from(e.target.files ?? []); e.target.value = ''; if (files.length) void importFiles(files)
        }} />
      </section>
    </div>
    <div className="capture-bottom"><div><h2>已拍 {samples.length} 张</h2><span className="muted">已标注 {samples.filter(i => i.annotated).length} 张</span></div>
      <Button variant="outline" isDisabled={!samples.length} onPress={() => navigate('review')}>标注样本<ArrowRight size={16} /></Button></div>
  </>
}
