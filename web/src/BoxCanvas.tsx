import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { Button } from '@heroui/react'
import { Minus, Plus, Move, SquareDashedMousePointer } from 'lucide-react'
import type { Box } from './api'
import usePanelSize from './usePanelSize'

export default function BoxCanvas({ src, width, height, boxes, label = '磨损', onChange, selected = -1, onSelect }: {
  src: string; width: number; height: number; boxes: Box[]; label?: string
  onChange?: (boxes: Box[]) => void; selected?: number; onSelect?: (index: number) => void
}) {
  const stage = usePanelSize()
  const start = useRef<[number, number] | null>(null)
  const panStart = useRef<[number, number, number, number] | null>(null)
  const [draft, setDraft] = useState<Box | null>(null)
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState<[number, number]>([0, 0])
  const [pan, setPan] = useState(!onChange)
  const [redraw, setRedraw] = useState(false)
  const editable = !!onChange
  useEffect(() => { setPan(!editable); setZoom(1); setOffset([0, 0]); setRedraw(false) }, [src, editable])
  const scale = Math.min(stage.width / width, stage.height / height) * zoom
  const clampOffset = (x: number, y: number): [number, number] => {
    const limitX = Math.max(0, (width * scale - stage.width) / 2)
    const limitY = Math.max(0, (height * scale - stage.height) / 2)
    return [Math.max(-limitX, Math.min(limitX, x)), Math.max(-limitY, Math.min(limitY, y))]
  }
  const point = (event: PointerEvent<HTMLDivElement>): [number, number] => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return [Math.max(0, Math.min(width, (event.clientX - bounds.left) / bounds.width * width)),
      Math.max(0, Math.min(height, (event.clientY - bounds.top) / bounds.height * height))]
  }
  const rectangle = (a: [number, number], b: [number, number]): Box => ({
    x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), width: Math.abs(a[0] - b[0]), height: Math.abs(a[1] - b[1]), label,
  })
  return <div className="box-workspace"><div className="box-toolbar"><div className="toolbar-actions"><Button variant="ghost" size="sm" isIconOnly aria-label="缩小图片" isDisabled={zoom <= 1} onPress={() => { setZoom(Math.max(1, zoom / 1.5)); setOffset([0, 0]) }}><Minus size={14} /></Button><button className="zoom-reset" onClick={() => { setZoom(1); setOffset([0, 0]) }}>{zoom === 1 ? '适应窗口' : `${Math.round(zoom * 100)}%`}</button><Button variant="ghost" size="sm" isIconOnly aria-label="放大图片" isDisabled={zoom >= 6} onPress={() => setZoom(Math.min(6, zoom * 1.5))}><Plus size={14} /></Button></div>
    {onChange && <div className="toolbar-actions"><Button size="sm" variant={pan ? 'secondary' : 'ghost'} aria-pressed={pan} onPress={() => setPan(!pan)}>{pan ? <Move size={14} /> : <SquareDashedMousePointer size={14} />}{pan ? '拖动画面' : '画缺陷框'}</Button>{selected >= 0 && <Button size="sm" variant={redraw ? 'secondary' : 'ghost'} onPress={() => { setRedraw(!redraw); setPan(false) }}>重画选中框</Button>}</div>}</div><div className="box-stage" ref={stage.ref}>
    <div className={`box-image ${onChange && !pan ? 'editable' : 'pannable'}`} style={{ width: width * scale, height: height * scale, transform: `translate(${offset[0]}px, ${offset[1]}px)` }}
      onPointerDown={event => {
        if (event.button !== 0) return
        if (pan) { event.currentTarget.setPointerCapture(event.pointerId); panStart.current = [event.clientX, event.clientY, ...offset]; return }
        if (!onChange) return
        event.currentTarget.setPointerCapture(event.pointerId); start.current = point(event)
      }} onPointerMove={event => {
        if (panStart.current) setOffset(clampOffset(panStart.current[2] + event.clientX - panStart.current[0], panStart.current[3] + event.clientY - panStart.current[1]))
        else if (start.current) setDraft(rectangle(start.current, point(event)))
      }}
      onPointerUp={event => {
        if (panStart.current) { panStart.current = null; return }
        if (!start.current) return
        const next = rectangle(start.current, point(event)); start.current = null; setDraft(null)
        if (next.width >= 2 && next.height >= 2) {
          if (redraw && selected >= 0) { onChange?.(boxes.map((box, index) => index === selected ? { ...next, label: box.label } : box)); setRedraw(false) }
          else { onChange?.([...boxes, next]); onSelect?.(boxes.length) }
        }
      }} onPointerCancel={() => { start.current = null; panStart.current = null; setDraft(null) }}>
      <img src={src} alt={onChange ? '拖动框选缺陷区域' : '刀具检测结果'} draggable={false} />
      {[...boxes, ...(draft ? [draft] : [])].map((box, index) => <div key={index}
        className={`defect-box ${index === selected ? 'selected' : ''} ${index === boxes.length ? 'draft' : ''}`}
        style={{ left: `${box.x / width * 100}%`, top: `${box.y / height * 100}%`, width: `${box.width / width * 100}%`, height: `${box.height / height * 100}%` }}>
        <span>{index + 1} · {box.label}{box.confidence !== undefined ? ` ${(box.confidence * 100).toFixed(0)}%` : ''}</span>
      </div>)}
    </div>
  </div></div>
}
