import { useEffect, useState } from 'react'
import { Button } from '@heroui/react'
import { Play } from 'lucide-react'
import { api, jobTitle, query, splits, type Job, type PageProps, type Plan, type Roi } from './api'
import JobLog from './JobLog'
import RoiPicker from './RoiPicker'

export default function Models({ tool, view, data, jobs, busy, run }: PageProps) {
  const [mode, setMode] = useState('experiment')
  const [device, setDevice] = useState('cuda')
  const [batch, setBatch] = useState(4)
  const [epochs, setEpochs] = useState(30)
  const [roi, setRoi] = useState<Roi>(null)
  const [savedRoi, setSavedRoi] = useState('null')
  const [plan, setPlan] = useState<Plan | null>(null)
  const [planError, setPlanError] = useState('')
  const [selectedJob, setSelectedJob] = useState('')
  const model = mode === 'classifier' ? 'classifier' : 'patchcore'
  const experimental = mode === 'experiment'
  const samples = data.images.filter(item => item.tool_type === tool && item.view === view)
  const history = jobs.filter(job => job.kind === 'train' && job.tool_type === tool && job.view === view)
  const job = history.find(job => job.id === selectedJob) ?? history[0]
  const active = jobs.some(job => ['running', 'stopping'].includes(job.status))

  useEffect(() => {
    let disposed = false
    void api<{ roi: Roi }>(`/api/recipe?${query({ tool_type: tool, view })}`).then(recipe => {
      if (!disposed) { setRoi(recipe.roi); setSavedRoi(JSON.stringify(recipe.roi)) }
    }).catch(e => { if (!disposed) setPlanError(e.message) })
    return () => { disposed = true }
  }, [tool, view])
  useEffect(() => {
    let disposed = false
    setPlan(null); setPlanError('')
    void api<Plan>(`/api/dataset?${query({ tool_type: tool, view, model, experimental })}`).then(value => {
      if (!disposed) setPlan(value)
    }).catch(e => { if (!disposed) setPlanError(e.message) })
    return () => { disposed = true }
  }, [tool, view, model, experimental, data])

  const saveRegion = async () => {
    await api('/api/recipe', 'PUT', { tool_type: tool, view, roi })
    setSavedRoi(JSON.stringify(roi))
  }
  const train = () => run(async () => {
    await saveRegion()
    const result = await api<Job>('/api/jobs', 'POST', { tool_type: tool, view, model, experimental, roi, device, batch_size: batch, epochs })
    setSelectedJob(result.id)
  })

  return <>
    <div className="model-grid">
      <div><RoiPicker sample={samples.find(item => item.included) ?? samples[0]} roi={roi} onChange={setRoi} />
        <div className="region-actions"><span className="muted text-xs">输入统一为灰度三通道 · 256 × 256</span><Button variant="outline" size="sm" isDisabled={busy || JSON.stringify(roi) === savedRoi}
          onPress={() => void run(saveRegion)}>保存区域</Button></div>
      </div>
      <section className="panel training-form"><h2>训练配置</h2>
        <label className="field">训练方式<select aria-label="训练方式" value={mode} onChange={e => setMode(e.target.value)}>
          <option value="experiment">PatchCore · 未校准实验</option><option value="calibrated">PatchCore · 阈值校准</option><option value="classifier">YOLO · 缺陷分类</option>
        </select></label>
        <label className="field">运行设备<select aria-label="运行设备" value={device} onChange={e => setDevice(e.target.value)}><option value="cuda">GPU · CUDA</option><option value="cpu">CPU</option></select></label>
        <div className="form-row"><label className="field">批量大小<input type="number" min="1" max="64" value={batch} onChange={e => setBatch(Number(e.target.value))} /></label>
          {model === 'classifier' && <label className="field">训练轮数<input type="number" min="1" max="1000" value={epochs} onChange={e => setEpochs(Number(e.target.value))} /></label>}</div>
        <div className="data-summary"><table><thead><tr><th>分组</th><th>实物</th><th>好件图</th><th>坏件图</th></tr></thead><tbody>
          {(['train', 'val', 'test'] as const).map(split => <tr key={split}><td>{splits[split]}</td><td>{plan?.counts[split].specimens ?? '—'}</td><td>{plan?.counts[split].good ?? '—'}</td><td>{plan?.counts[split].defect ?? '—'}</td></tr>)}
        </tbody></table></div>
        {experimental && <p className="model-note">实验建库仅使用正常训练图，输出分数与热力图。当前模式不判断正常／异常。</p>}
        {mode === 'calibrated' && <p className="model-note">使用独立好件、坏件验证图校准阈值。检测效果仍需独立测试实物验证。</p>}
        {model === 'classifier' && <p className="model-note">训练与验证每类需有不同实物。类别名称来自人工确认的真实缺陷。</p>}
        {planError && <p className="inline-error" role="alert">{planError}</p>}
        {!!plan?.issues.length && <ul className="data-issues">{plan.issues.map(issue => <li key={issue}>{issue}</li>)}</ul>}
        <Button fullWidth isDisabled={busy || active || !plan?.ready || batch < 1 || batch > 64 || (model === 'classifier' && (epochs < 1 || epochs > 1000))}
          onPress={() => void train()}><Play size={15} />开始{experimental ? '实验建库' : '训练'}</Button>
      </section>
    </div>
    <div className="history-toolbar"><h2>训练记录</h2><select aria-label="选择训练记录" value={job?.id ?? ''} onChange={e => setSelectedJob(e.target.value)}>
      {!history.length && <option value="">暂无训练记录</option>}{history.map(item => <option key={item.id} value={item.id}>{jobTitle(item)}</option>)}
    </select></div>
    <JobLog job={job} busy={busy} run={run} />
  </>
}
