import { useRef, useState, type PointerEvent } from 'react'
import { Button } from '@heroui/react'
import { imageUrl, type Roi, type Sample } from './api'

export default function RoiPicker({ sample, roi, onChange }: { sample?: Sample; roi: Roi; onChange: (roi: Roi) => void }) {
  const start = useRef<[number, number] | null>(null)
  const [draft, setDraft] = useState<Roi>(null)
  const shown = draft ?? roi
  const point = (event: PointerEvent<HTMLDivElement>): [number, number] => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return [Math.round(Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) * sample!.width),
      Math.round(Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) * sample!.height)]
  }
  const rectangle = (a: [number, number], b: [number, number]): NonNullable<Roi> => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])]
  return <section className="panel roi-panel"><div className="panel-toolbar"><h2>检测区域</h2><Button variant="ghost" size="sm" onPress={() => onChange(null)}>使用整图</Button></div>
    <div className="roi-stage">{sample ? <div className="roi-image" onPointerDown={event => {
      if (event.button !== 0) return
      event.currentTarget.setPointerCapture(event.pointerId); start.current = point(event)
    }} onPointerMove={event => { if (start.current) setDraft(rectangle(start.current, point(event))) }}
      onPointerUp={event => { if (!start.current) return; const next = rectangle(start.current, point(event)); start.current = null; setDraft(null); if (next[2] > next[0] && next[3] > next[1]) onChange(next) }}
      onPointerCancel={() => { start.current = null; setDraft(null) }}>
      <img src={imageUrl(sample.id)} alt="检测区域参考图" draggable={false} />
      {shown && <div className="roi-box" style={{ left: `${shown[0] / sample.width * 100}%`, top: `${shown[1] / sample.height * 100}%`, width: `${(shown[2] - shown[0]) / sample.width * 100}%`, height: `${(shown[3] - shown[1]) / sample.height * 100}%` }} />}
    </div> : <div className="stage-empty">暂无参考图片</div>}</div>
    <div className="roi-fields">{['左', '上', '右', '下'].map((label, index) => <label className="field" key={label}>{label}<input type="number" min="0" step="1" value={roi?.[index] ?? ''}
      aria-label={`检测区域${label}边界`} placeholder={index < 2 ? '0' : index === 2 ? String(sample?.width ?? '') : String(sample?.height ?? '')}
      onChange={e => { const next: NonNullable<Roi> = roi ? [...roi] : [0, 0, sample?.width ?? 256, sample?.height ?? 256]; next[index] = Number(e.target.value); onChange(next) }} /></label>)}</div>
    <div className="image-caption"><span>{roi ? `${roi[2] - roi[0]} × ${roi[3] - roi[1]} px` : '整张图片'}</span><span>拖动框选</span></div>
  </section>
}
