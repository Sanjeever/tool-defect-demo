import { useRef, useState, type PointerEvent } from 'react'
import type { Box } from './api'
import usePanelSize from './usePanelSize'

export default function BoxCanvas({ src, width, height, boxes, label = '磨损', onChange, selected = -1, onSelect }: {
  src: string; width: number; height: number; boxes: Box[]; label?: string
  onChange?: (boxes: Box[]) => void; selected?: number; onSelect?: (index: number) => void
}) {
  const stage = usePanelSize()
  const start = useRef<[number, number] | null>(null)
  const [draft, setDraft] = useState<Box | null>(null)
  const scale = Math.min(stage.width / width, stage.height / height)
  const point = (event: PointerEvent<HTMLDivElement>): [number, number] => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return [Math.max(0, Math.min(width, (event.clientX - bounds.left) / bounds.width * width)),
      Math.max(0, Math.min(height, (event.clientY - bounds.top) / bounds.height * height))]
  }
  const rectangle = (a: [number, number], b: [number, number]): Box => ({
    x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), width: Math.abs(a[0] - b[0]), height: Math.abs(a[1] - b[1]), label,
  })
  return <div className="box-workspace"><div className="box-stage" ref={stage.ref}>
    <div className={`box-image ${onChange ? 'editable' : ''}`} style={{ width: width * scale, height: height * scale }}
      onPointerDown={event => {
        if (!onChange || event.button !== 0) return
        event.currentTarget.setPointerCapture(event.pointerId); start.current = point(event)
      }} onPointerMove={event => { if (start.current) setDraft(rectangle(start.current, point(event))) }}
      onPointerUp={event => {
        if (!start.current) return
        const next = rectangle(start.current, point(event)); start.current = null; setDraft(null)
        if (next.width >= 2 && next.height >= 2) { onChange?.([...boxes, next]); onSelect?.(boxes.length) }
      }} onPointerCancel={() => { start.current = null; setDraft(null) }}>
      <img src={src} alt={onChange ? '拖动框选缺陷区域' : '刀具检测结果'} draggable={false} />
      {[...boxes, ...(draft ? [draft] : [])].map((box, index) => <div key={index}
        className={`defect-box ${index === selected ? 'selected' : ''} ${index === boxes.length ? 'draft' : ''}`}
        style={{ left: `${box.x / width * 100}%`, top: `${box.y / height * 100}%`, width: `${box.width / width * 100}%`, height: `${box.height / height * 100}%` }}>
        <span>{index + 1} · {box.label}{box.confidence !== undefined ? ` ${(box.confidence * 100).toFixed(0)}%` : ''}</span>
      </div>)}
    </div>
  </div></div>
}
