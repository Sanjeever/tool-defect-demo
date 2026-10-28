import { useEffect, useState } from 'react'

export default function usePanelSize() {
  const [element, ref] = useState<HTMLDivElement | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }))
    observer.observe(element)
    return () => observer.disconnect()
  }, [element])
  return { ref, ...size }
}
