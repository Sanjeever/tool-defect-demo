import { Button } from '@heroui/react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

export default function Pager({ page, pages, onChange, label }: { page: number; pages: number; onChange: (page: number) => void; label: string }) {
  return <div className="pager" aria-label={`${label}分页`}><span>{page + 1} / {pages}</span><div>
    <Button variant="ghost" size="sm" isIconOnly aria-label={`${label}上一页`} isDisabled={page === 0} onPress={() => onChange(page - 1)}><ChevronLeft size={15} /></Button>
    <Button variant="ghost" size="sm" isIconOnly aria-label={`${label}下一页`} isDisabled={page >= pages - 1} onPress={() => onChange(page + 1)}><ChevronRight size={15} /></Button>
  </div></div>
}
