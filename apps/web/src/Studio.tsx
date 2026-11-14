import { useEffect, useMemo, useRef, useState } from 'react'
import type { DragEvent, FormEvent } from 'react'
import {
  API, assetPath, audioMetrics, fileSize, formatNumber, formatTime, isActive, jobPath, localArtifactUrl, modelPath, preferredAsset, projectPath, request, restorationVersionLabels,
} from './api'
import type {
  AudioAsset, Defect, Depth, ExportRecord, Health, Job, JobStatus, Metric, MixerSettings, Model, Operation, Profile, Project, Region, Stem,
} from './api'
import { Inspector } from './Inspector'
import { initialMixer, Mixer } from './Mixer'
import { liveMixConfig } from './liveMix'
import { Timeline } from './Timeline'
import { TransportBar, useTransport } from './Transport'

type View = 'studio' | 'projects' | 'models' | 'report' | 'settings'
type Icon = 'studio' | 'projects' | 'models' | 'report' | 'settings'

const trackOrder: Stem[] = ['original', 'dialogue', 'music', 'effects', 'residual', 'master', 'difference']
const views: { id: View; label: string }[] = [
  { id: 'projects', label: 'Progetti' }, { id: 'studio', label: 'Studio' }, { id: 'models', label: 'Modelli' },
  { id: 'report', label: 'Report' }, { id: 'settings', label: 'Impostazioni' },
]
const jobNames: Record<string, string> = { import: 'Importazione', separate: 'Separazione', analyze: 'Analisi', restore: 'Restauro', mix: 'Mix DSP', export: 'Esportazione', install_model: 'Installazione modello' }
const jobStatuses: Record<JobStatus, string> = { queued: 'In coda', running: 'In corso', cancelling: 'Annullamento', cancelled: 'Annullato', succeeded: 'Completato', failed: 'Errore', blocked: 'Bloccato' }
const modelStatuses: Record<string, string> = { available: 'Disponibile', ready: 'Pronto', installed: 'Installato', verified: 'Verificato', blocked: 'Bloccato', missing: 'Da installare' }
const displayDate = new Intl.DateTimeFormat('it-IT', { dateStyle: 'medium', timeStyle: 'short' })

function storedValue(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

function storeValue(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Private browser storage may be disabled.
  }
}

function errorText(value: unknown): string {
  return value instanceof Error ? value.message : 'Operazione locale non riuscita.'
}

function date(value: string) {
  const timestamp = new Date(value)
  return Number.isNaN(timestamp.getTime()) ? value : displayDate.format(timestamp)
}

function Glyph({ icon }: { icon: Icon }) {
  return <i className={`nav-glyph glyph-${icon}`} aria-hidden="true" />
}

function Wordmark() {
  return <div className="wordmark"><span className="brand-mark" aria-hidden="true"><i /><i /><i /><i /><i /></span><strong>SONORA<span> AI</span></strong></div>
}

function useJobs(initial: Job[], projectId: string | undefined, onChange: (job: Job) => void) {
  const [updates, setUpdates] = useState<Record<string, Job>>({})
  const current = useRef(onChange)
  current.current = onChange
  const updateJob = (updated: Job) => setUpdates(values => ({ ...values, [updated.id]: updated }))
  const jobMap = Object.fromEntries(initial.map(job => [job.id, job]))
  const jobs = Object.values({ ...jobMap, ...updates }).filter(job => job.project_id === null || job.project_id === projectId)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
  const activeIds = jobs.filter(isActive).map(job => job.id).sort().join(',')

  useEffect(() => {
    if (!activeIds) return
    const streams: EventSource[] = []
    const timers: number[] = []
    const settled = new Set<string>()
    const ids = activeIds.split(',')
    const controller = new AbortController()
    for (const id of ids) {
      const url = jobPath(id)
      const stream = new EventSource(API + url + '/events')
      streams.push(stream)
      function receive(job: Job) {
        if (controller.signal.aborted || settled.has(job.id)) return
        setUpdates(values => ({ ...values, [job.id]: job }))
        if (!isActive(job)) {
          settled.add(job.id)
          stream.close()
          current.current(job)
        }
      }
      stream.onmessage = event => {
        try {
          receive(JSON.parse(event.data) as Job)
        } catch {
          void request<Job>(url, { signal: controller.signal }).then(receive).catch(() => undefined)
        }
      }
      const timer = window.setInterval(() => {
        void request<Job>(url, { signal: controller.signal }).then(receive).catch(() => undefined)
      }, 3500)
      timers.push(timer)
    }
    return () => {
      controller.abort()
      streams.forEach(stream => stream.close())
      timers.forEach(timer => clearInterval(timer))
    }
  }, [activeIds])
  return { jobs, updateJob }
}

function JobQueue({ jobs, busy, onJobAction }: { jobs: Job[]; busy: boolean; onJobAction: (job: Job, action: 'cancel' | 'retry') => void }) {
  return (
    <section className="panel job-panel" aria-labelledby="jobs-title">
      <header className="panel-heading"><h2 id="jobs-title">Elaborazioni</h2><span className="subtle-count">{jobs.filter(isActive).length} attive</span></header>
      {jobs.length ? <ol className="jobs-list">
        {jobs.slice(0, 8).map(job => {
          const error = typeof job.error === 'string' ? job.error : job.error?.detail ?? job.error?.message
          return <li key={job.id}>
            <div className="job-title"><strong>{jobNames[job.type] ?? job.type}</strong><span className={`job-status status-${job.status}`}>{jobStatuses[job.status]}</span></div>
            {job.stage && <p className="hint">{job.stage}</p>}
            {isActive(job) && job.status !== 'queued' && <div className="job-progress">
              {job.total && job.total > 0
                ? <><progress max={job.total} value={Math.min(job.processed, job.total)} aria-label="Avanzamento elaborazione" /><small>{formatNumber.format(job.processed)} / {formatNumber.format(job.total)}</small></>
                : <progress aria-label="Avanzamento indeterminato" />}
            </div>}
            {error && <p className="job-error">{error}</p>}
            {isActive(job) && <button type="button" disabled={busy || job.status === 'cancelling'} onClick={() => onJobAction(job, 'cancel')}>Annulla</button>}
            {['cancelled', 'failed', 'blocked'].includes(job.status) && <button type="button" disabled={busy} onClick={() => onJobAction(job, 'retry')}>Riprova</button>}
          </li>
        })}
      </ol> : <p className="hint copy-space">Nessuna elaborazione in coda.</p>}
    </section>
  )
}

function ModelCatalog({ models, busy, onInstall, onVerify, selectedId }: {
  models: Model[]
  busy: boolean
  onInstall: (model: Model) => void
  onVerify: (model: Model) => void
  selectedId: string
}) {
  return (
    <section className="panel page-panel">
      <header className="panel-heading"><h2>Modelli locali</h2></header>
      {models.length ? <div className="model-grid">
        {models.map(model => (
          <article className="model-card inset" key={model.id}>
            <header><h3>{model.name}</h3><span className={`job-status model-${model.status}`}>{modelStatuses[model.status] ?? model.status}</span></header>
            <p className="hint">{model.status_detail}</p>
            <dl className="metrics-list">
              <div><dt>Uso</dt><dd>{model.task === 'inpainting' ? 'Inpainting neurale' : 'Separazione'}</dd></div>
              <div><dt>Backend</dt><dd>{model.backends.length ? model.backends.map(item => item.toUpperCase()).join(', ') : 'Indisponibile'}</dd></div>
              {model.native_sample_rate && <div><dt>Ingresso nativo</dt><dd>{formatNumber.format(model.native_sample_rate / 1000)} kHz · {model.native_channels ?? 'N/D'} ch</dd></div>}
              <div><dt>Licenza codice</dt><dd>{model.code_license ?? 'N/D'}</dd></div>
              <div><dt>Licenza pesi</dt><dd>{model.weights_license ?? model.license ?? 'N/D'}</dd></div>
              {model.code_revision && <div className="model-sha"><dt>Revisione codice</dt><dd>{model.code_revision}</dd></div>}
              <div><dt>Checkpoint</dt><dd>{model.checkpoint ?? 'N/D'}</dd></div>
              <div><dt>Dimensione</dt><dd>{fileSize(model.size_bytes ?? model.download_bytes)}</dd></div>
              {model.sha256 && <div className="model-sha"><dt>SHA-256</dt><dd>{model.sha256}</dd></div>}
            </dl>
            {model.stereo_warning && <p className="hint">{model.stereo_warning}</p>}
            <div className="wrap-actions">
              {model.status !== 'installed' && model.status !== 'verified' && model.can_install !== false &&
                <button type="button" className="primary" disabled={busy || (!model.backends.length && model.status === 'blocked')} onClick={() => onInstall(model)}>Scarica {model.size_bytes ? fileSize(model.size_bytes) : 'checkpoint'}</button>}
              {model.checkpoint_required !== false && <button type="button" disabled={busy || !['installed', 'verified'].includes(model.status)} onClick={() => onVerify(model)}>Verifica SHA-256</button>}
              {selectedId === model.id && <span className="hint">Selezionato in studio</span>}
            </div>
          </article>
        ))}
      </div> : <p className="hint copy-space">Catalogo non disponibile.</p>}
    </section>
  )
}

function Exports({ exports, master, busy, onSubmit }: {
  exports: ExportRecord[]
  master: AudioAsset | undefined
  busy: boolean
  onSubmit: (options: { format: 'wav_float' | 'wav_pcm24' | 'flac'; sample_rate?: number }) => void
}) {
  const [format, setFormat] = useState<'wav_float' | 'wav_pcm24' | 'flac'>('wav_float')
  const [rate, setRate] = useState('')
  return (
    <section className="panel page-panel">
      <header className="panel-heading"><h2>Report ed esportazione</h2></header>
      <form className="export-form" onSubmit={event => { event.preventDefault(); onSubmit({ format, sample_rate: rate ? Number(rate) : undefined }) }}>
        <label>Formato<select value={format} onChange={event => setFormat(event.target.value as typeof format)}><option value="wav_float">WAV float32</option><option value="wav_pcm24">WAV PCM 24 bit</option><option value="flac">FLAC 24 bit</option></select></label>
        <label>Frequenza<select value={rate} onChange={event => setRate(event.target.value)}><option value="">Frequenza del progetto</option><option value="44100">44,1 kHz</option><option value="48000">48 kHz</option><option value="96000">96 kHz</option></select></label>
        <button type="submit" className="primary" disabled={busy || !master} title={master ? 'Esporta il master e le sorgenti della sua sessione DSP' : 'Renderizza il master dalla console DSP'}>Esporta master e stem</button>
      </form>
      {!master && <p className="hint copy-space">Renderizza il master nella console DSP per esportare i file.</p>}
      {!exports.length && master && <p className="hint copy-space">Nessuna esportazione per questo progetto.</p>}
      <div className="exports-list">
        {exports.map(record => (
          <article key={record.id} className="inset">
            <h3>{date(record.created_at)}</h3>
            {record.warnings.length > 0 && <ul className="export-warnings">{record.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}
            <ul className="artifact-list">
              {record.artifacts.map(artifact => {
                const url = localArtifactUrl(artifact.url)
                return <li key={artifact.name}>{url ? <a href={url} download={artifact.name === 'report.html' ? undefined : artifact.name} target={artifact.name === 'report.html' ? '_blank' : undefined} rel="noreferrer">{artifact.name}</a> : <span>{artifact.name}</span>}<small>{fileSize(artifact.size)}</small></li>
              })}
            </ul>
          </article>
        ))}
      </div>
    </section>
  )
}

function Projects({ projects, current, busy, onOpen, onCreate, onDuplicate, onArchive }: {
  projects: Project[]
  current?: Project
  busy: boolean
  onOpen: (project: Project) => void
  onCreate: (name: string) => void
  onDuplicate: (project: Project) => void
  onArchive: (project: Project) => void
}) {
  const [name, setName] = useState('')
  const [archived, setArchived] = useState(false)
  const visible = projects.filter(project => project.archived === archived)
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    onCreate(name.trim())
    setName('')
  }

  return (
    <section className="panel page-panel" aria-labelledby="projects-title">
      <header className="panel-heading"><h2 id="projects-title">Progetti</h2><label className="inline-check"><input type="checkbox" checked={archived} onChange={event => setArchived(event.target.checked)} /> Archiviati</label></header>
      <form className="project-form" onSubmit={submit}>
        <label><span>Nome progetto</span><input value={name} placeholder="Es. Restauro colonna sonora" onChange={event => setName(event.target.value)} maxLength={120} required /></label>
        <button type="submit" className="primary" disabled={busy || !name.trim()}>Crea progetto</button>
      </form>
      {!visible.length && <p className="hint copy-space">{archived ? 'Nessun progetto archiviato.' : 'Nessun progetto. Crea una sessione di lavoro.'}</p>}
      <ul className="project-list">
        {visible.map(project => (
          <li key={project.id}>
            <button className="project-name" type="button" disabled={busy} aria-current={project.id === current?.id || undefined} onClick={() => onOpen(project)}>
              <Glyph icon="projects" /><span><strong>{project.name}</strong><small>{date(project.updated_at)} · {project.assets.length} {project.assets.length === 1 ? 'versione' : 'versioni'}</small></span>
            </button>
            <div className="wrap-actions">
              <button type="button" disabled={busy} onClick={() => onDuplicate(project)}>Duplica</button>
              <button type="button" disabled={busy} onClick={() => onArchive(project)}>{project.archived ? 'Riapri' : 'Archivia'}</button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ImportPanel({ original, originals, busy, archived, health, onSelect, onImport }: {
  original?: AudioAsset
  originals: AudioAsset[]
  busy: boolean
  archived: boolean
  health?: Health
  onSelect: (asset: AudioAsset) => void
  onImport: (file: File, rate?: number) => void
}) {
  const [rate, setRate] = useState(() => storedValue('sonora.import.rate', '48000'))
  const [dragging, setDragging] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const disabled = busy || archived

  function drop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files.item(0)
    if (file && !disabled) onImport(file, rate ? Number(rate) : undefined)
  }

  function choose(file: File | null) {
    if (file && !disabled) onImport(file, rate ? Number(rate) : undefined)
    if (fileInput.current) fileInput.current.value = ''
  }

  const sourceRate = original?.metadata.source_sample_rate
  const layout = original?.metadata.channel_layout ?? original?.metadata.layout
  const bitrate = original?.metadata.bitrate_bps
  const bitDepth = original?.metadata.source_bit_depth
  return (
    <section className={`panel import-panel${dragging ? ' dragging' : ''}`} onDragOver={event => { event.preventDefault(); if (!disabled) setDragging(true) }} onDragLeave={event => {
      if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDragging(false)
    }} onDrop={drop}>
      <header className="panel-heading">
        <h2>Sorgente</h2>
        {archived && <span className="hint">Progetto archiviato</span>}
        {originals.length > 1 && <label><span className="sr-only">Originale attivo</span><select value={original?.id ?? ''} onChange={event => {
          const value = originals.find(asset => asset.id === event.target.value)
          if (value) onSelect(value)
        }}>{originals.map(asset => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label>}
      </header>
      <div className="import-content">
        <div className="import-file">
          <span className="source-icon" aria-hidden="true">∿</span>
          <div>{original ? <><strong title={original.name}>{original.name}</strong>
            <p className="hint">{[original.metadata.codec, typeof sourceRate === 'number' ? `sorgente ${formatNumber.format(sourceRate / 1000)} kHz` : '', `progetto ${formatNumber.format(original.metadata.sample_rate / 1000)} kHz`, typeof layout === 'string' ? layout : original.metadata.channels ? `${original.metadata.channels} ch` : '', formatTime(original.metadata.sample_count, original.metadata.sample_rate), `${formatNumber.format(original.metadata.sample_count)} campioni`, typeof bitDepth === 'number' ? `${bitDepth} bit PCM` : typeof bitrate === 'number' ? `${formatNumber.format(bitrate / 1000)} kb/s` : ''].filter(Boolean).join(' · ')}</p></>
            : <><strong>Trascina qui un file audio</strong><p className="hint">WAV, FLAC, AIFF, MP3, AAC/M4A{health?.max_upload_bytes ? ` · massimo ${fileSize(health.max_upload_bytes)}` : ''}</p></>}</div>
        </div>
        <label><span className="sr-only">Frequenza di importazione</span><select value={rate} disabled={disabled} onChange={event => { setRate(event.target.value); storeValue('sonora.import.rate', event.target.value) }}><option value="">Frequenza sorgente</option><option value="44100">44,1 kHz</option><option value="48000">48 kHz</option><option value="96000">96 kHz</option><option value="192000">192 kHz</option></select></label>
        <input type="file" ref={fileInput} hidden onChange={event => choose(event.currentTarget.files?.item(0) ?? null)} />
        <button type="button" className="primary" disabled={disabled} onClick={() => fileInput.current?.click()}>Importa audio</button>
      </div>
    </section>
  )
}

function Settings({ health }: { health?: Health }) {
  return <section className="panel page-panel">
    <header className="panel-heading"><h2>Ambiente locale</h2></header>
    {health ? <dl className="metrics-list settings-list">
      <div><dt>Sistema</dt><dd>{health.platform}</dd></div>
      <div><dt>Architettura</dt><dd>{health.machine}</dd></div>
      <div><dt>Memoria fisica</dt><dd>{fileSize(health.memory_bytes)}</dd></div>
      <div><dt>Spazio libero dati</dt><dd>{fileSize(health.disk_free_bytes)}</dd></div>
      <div><dt>PyTorch MPS</dt><dd>{health.mps ? 'Disponibile al sistema' : 'Indisponibile'}</dd></div>
      <div><dt>FFmpeg e ffprobe</dt><dd>{health.ffmpeg ? 'Disponibili' : 'Indisponibili'}</dd></div>
      <div><dt>Archivio dati</dt><dd>{health.data_dir}</dd></div>
    </dl> : <p className="hint copy-space">Il servizio locale non ha risposto.</p>}
  </section>
}

const defaultViewport: Region = { start_sample: 0, end_sample: 0 }

function ProjectStudio({ project, health, models, selectedModelId, setSelectedModelId, busy, onNavigate, onQueue, onRequest, onChange }: {
  project: Project
  health?: Health
  models: Model[]
  selectedModelId: string
  setSelectedModelId: (id: string) => void
  busy: boolean
  onNavigate: (view: View) => void
  onQueue: (path: string, data: unknown) => Promise<Job | undefined>
  onRequest: <T>(action: () => Promise<T>) => Promise<T | undefined>
  onChange: () => Promise<void>
}) {
  const originals = project.assets.filter(asset => asset.kind === 'original')
  const original = originals.at(-1)
  const [activeId, setActiveId] = useState(() => storedValue(`sonora.project.${project.id}.asset`, ''))
  const [region, setRegion] = useState<Region | null>(null)
  const [viewport, setViewport] = useState<Region>(defaultViewport)
  const [eventId, setEventId] = useState<string | null>(null)
  const [restorationTarget, setRestorationTarget] = useState('')
  const [backend, setBackend] = useState('cpu')
  const [regionalSeparation, setRegionalSeparation] = useState(false)
  const [draftMixer, setDraftMixer] = useState<{ sourceId: string; settings: MixerSettings }>()
  const path = projectPath(project.id)
  const mutable = !busy && !project.archived
  const active = project.assets.find(asset => asset.id === activeId) ?? original
  function rootSource(asset?: AudioAsset): AudioAsset | undefined {
    if (!asset || asset.stem === 'original' && asset.kind === 'original') return asset
    if (!asset.parent_id) return undefined
    return rootSource(project.assets.find(item => item.id === asset.parent_id))
  }
  const source = rootSource(active) ?? original
  const count = source?.metadata.sample_count ?? active?.metadata.sample_count ?? 0
  const rate = source?.metadata.sample_rate ?? active?.metadata.sample_rate ?? 0
  const projectViewport = viewport.end_sample && viewport.end_sample <= count ? viewport : { start_sample: 0, end_sample: count }
  const master = [...project.assets].reverse().find(asset => asset.stem === 'master' && asset.status === 'approved' &&
    asset.metadata.sample_rate === rate && asset.metadata.sample_count === count)
  const relevantAnalysis = project.analyses.find(analysis => analysis.asset_id === active?.id)
  const selectedEvent = relevantAnalysis?.events.find(event => event.id === eventId)
  const sourceAssets = useMemo(() => project.assets.filter(asset => rootSource(asset)?.id === source?.id), [project.assets, source])
  const versionLabels = useMemo(() => restorationVersionLabels(sourceAssets), [sourceAssets])
  const versions = sourceAssets.filter(asset => asset.stem === active?.stem || asset.stem === 'difference' && sourceAssets.some(item => item.stem === active?.stem && item.id === asset.parent_id)).reverse()
  const candidate = active?.kind === 'restored' ? active : versions.find(asset => asset.kind === 'restored' && asset.parent_id === active?.id && asset.status !== 'rejected')
  const baseline = candidate ? project.assets.find(asset => asset.id === candidate.parent_id) : active
  const relevantDefects = relevantAnalysis?.events.map(event => ({ ...event, start_sample: event.start_sample + (active?.metadata.start_sample ?? 0), end_sample: event.end_sample + (active?.metadata.start_sample ?? 0) })) ?? []
  const timelineAssets = trackOrder.flatMap(stem => {
    if (stem === active?.stem) return [active]
    if (stem === 'original') return source ? [source] : []
    if (stem === 'difference') {
      const delta = project.assets.find(asset => asset.stem === 'difference' && asset.parent_id === candidate?.id && asset.status !== 'rejected')
      return delta ? [delta] : []
    }
    if (stem === 'master') return master?.metadata.sample_count === count && master?.metadata.sample_rate === rate ? [master] : []
    const usable = project.assets.filter(asset => asset.stem === stem && asset.status === 'approved' && (!source || rootSource(asset)?.id === source.id))
    const latest = usable.at(-1)
    return latest ? [latest] : []
  })
  const mixerAssets = useMemo(
    () => sourceAssets.filter(asset => asset.status === 'approved' && asset.kind !== 'preview' &&
      asset.metadata.sample_count === count && asset.metadata.sample_rate === rate &&
      asset.metadata.channels === source?.metadata.channels && (asset.metadata.start_sample ?? 0) === 0),
    [sourceAssets, source, count, rate],
  )
  const restorationTracks = ['dialogue', 'music', 'effects'].flatMap(stem => {
    const track = mixerAssets.find(asset => asset.id === active?.id && asset.stem === stem) ??
      mixerAssets.filter(asset => asset.stem === stem && asset.kind === 'separated').at(-1)
    return track ? [track] : []
  })
  const savedMix = draftMixer?.sourceId === source?.id && draftMixer ? draftMixer.settings :
    Object.values(project.mixer?.tracks ?? {}).some(track => sourceAssets.some(asset => asset.id === track.asset_id)) ? project.mixer : null
  const selectedMix = useMemo(() => initialMixer(mixerAssets, savedMix), [mixerAssets, savedMix])
  const monitorConfig = useMemo(() => liveMixConfig(mixerAssets, selectedMix, rate, count), [mixerAssets, selectedMix, rate, count])
  const transport = useTransport(project.id, region, monitorConfig)
  const separationModels = models.filter(item => item.task !== 'inpainting')
  const model = separationModels.find(item => item.id === selectedModelId) ?? separationModels.find(item => item.status === 'installed' || item.status === 'verified') ?? separationModels[0]
  const selectedBackend = model?.backends.includes(backend) ? backend : model?.backends[0]
  const canSeparate = Boolean(source && model && ['installed', 'verified'].includes(model.status) && selectedBackend && mutable)

  function select(asset: AudioAsset) {
    if (asset.id === activeId) return
    if (rootSource(asset)?.id !== source?.id) {
      setRegion(null)
      setViewport(defaultViewport)
    }
    setActiveId(asset.id)
    storeValue(`sonora.project.${project.id}.asset`, asset.id)
    setEventId(null)
    setRestorationTarget('')
  }

  function selectDefect(defect: Defect, listen = false) {
    if (!active) return
    const offset = active.metadata.start_sample ?? 0
    const start = defect.start_sample + offset
    const end = defect.end_sample + offset
    setEventId(defect.id)
    setRegion({ start_sample: start, end_sample: end })
    if (start < projectViewport.start_sample || end > projectViewport.end_sample) {
      setViewport(defaultViewport)
    }
    if (listen) {
      transport.setLoop(true)
      transport.select(active, start, true)
    } else {
      transport.select(active, start, false)
    }
  }

  function monitorData(asset?: AudioAsset): { asset: AudioAsset; metrics?: Record<string, Metric> } | undefined {
    if (!asset) return undefined
    const record = project.analyses.find(analysis => analysis.asset_id === asset.id)
    return { asset, metrics: record?.metrics ?? audioMetrics(asset) }
  }

  async function importAudio(file: File, sampleRate?: number) {
    const form = new FormData()
    form.set('file', file)
    if (sampleRate) form.set('sample_rate', String(sampleRate))
    const queued = await onQueue(path + '/import', form)
    if (queued) {
      setActiveId('')
      storeValue(`sonora.project.${project.id}.asset`, '')
      setRegion(null)
      setViewport(defaultViewport)
      setEventId(null)
    }
  }

  async function render() {
    const tracks = Object.fromEntries(Object.entries(selectedMix.tracks).filter(([, track]) => track.asset_id))
    await onQueue(path + '/mix', { tracks, master: selectedMix.master })
  }

  const lastSource = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (source && lastSource.current !== source.id) {
      lastSource.current = source.id
      const monitoring = active && active.status !== 'rejected' ? active : source
      transport.select(monitoring, monitoring.metadata.start_sample ?? 0, false)
    }
  }, [transport, source, active])

  useEffect(() => {
    function keyboard(event: KeyboardEvent) {
      if (event.code !== 'Space' || event.repeat || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey ||
        !(event.target instanceof HTMLElement) || event.target.closest('input, textarea, select, button, a, summary, [contenteditable="true"]') ||
        !transport.ready) return
      event.preventDefault()
      transport.toggle()
    }
    window.addEventListener('keydown', keyboard)
    return () => window.removeEventListener('keydown', keyboard)
  }, [transport])

  return (
    <>
      <ImportPanel original={source} originals={originals} onSelect={select} busy={busy} archived={project.archived} health={health} onImport={(file, selectedRate) => void importAudio(file, selectedRate)} />
      <section className="panel separation" aria-label="Separazione AI">
        <h2>Separazione AI</h2>
        <label><span className="sr-only">Modello di separazione</span><select value={model?.id ?? ''} disabled={!separationModels.length} onChange={event => setSelectedModelId(event.target.value)}><option value="" disabled>Modelli indisponibili</option>{separationModels.map(item => <option value={item.id} key={item.id}>{item.name} · {modelStatuses[item.status] ?? item.status}</option>)}</select></label>
        <label><span className="sr-only">Backend di separazione</span><select value={selectedBackend ?? ''} disabled={!model?.backends.length} onChange={event => setBackend(event.target.value)}><option value="" disabled>Backend</option>{model?.backends.map(item => <option key={item} value={item}>{item.toUpperCase()}</option>)}</select></label>
        <label className="inline-check" title={region ? 'Calcola un’anteprima della regione selezionata' : 'Seleziona prima una regione'}><input type="checkbox" checked={regionalSeparation && Boolean(region)} disabled={!region} onChange={event => setRegionalSeparation(event.target.checked)} /> Solo regione</label>
        {model && !['installed', 'verified'].includes(model.status) && <button type="button" onClick={() => onNavigate('models')}>Gestisci modello</button>}
        <button type="button" className="primary" disabled={!canSeparate} title={canSeparate ? 'Avvia la coda di separazione' : 'Importa un originale e installa un modello disponibile'} onClick={() => {
          if (source && model && selectedBackend) void onQueue(path + '/separate', { asset_id: source.id, model_id: model.id, backend: selectedBackend, ...(region && regionalSeparation ? region : {}) })
        }}>Separa tracce</button>
      </section>
      {!source && <div className="panel timeline-empty"><span className="empty-wave" aria-hidden="true">⌁</span><p>La timeline si popola dopo l’importazione.</p></div>}
      {source && <div className="studio-workspace">
        <div className="studio-center">
          <Timeline projectId={project.id} assets={timelineAssets} active={active} monitorId={transport.active?.id} sampleCount={count} sampleRate={rate} position={transport.position} region={region} viewport={projectViewport} events={relevantDefects} selectedEventId={eventId} onSelect={select} onListen={asset => transport.select(asset)} onSeek={transport.seek} onSelectRegion={setRegion} onViewport={setViewport} onDefect={event => {
            const local = relevantAnalysis?.events.find(item => item.id === event.id)
            if (local) selectDefect(local)
          }} />
          <TransportBar transport={transport} sampleCount={count} sampleRate={rate} region={region} baseline={monitorData(baseline)} candidate={monitorData(candidate)} />
        </div>
        <Inspector key={active?.id ?? 'none'} versionLabels={versionLabels} restorationTracks={restorationTracks}
          draftKey={active && `sonora.restoration.draft.${project.id}.${source.id}.${active.stem}`}
          openRestoration={active?.id === restorationTarget} inpaintModel={models.find(item => item.task === 'inpainting' && active &&
          (item.stems?.includes(active.stem) || (!item.stems && active.stem === 'music' && item.id === 'diffusion-inpaint')))} asset={active} versions={versions} analysis={relevantAnalysis} selectedEvent={selectedEvent} region={region} busy={!mutable}
          onAnalyze={async ({ depth, sensitivity, region }: { depth: Depth; sensitivity: number; region?: Region }) => {
            if (active) await onQueue(path + '/analyze', { asset_id: active.id, depth, sensitivity, ...region })
          }}
          onDefect={defect => selectDefect(defect)}
          onSaveDefect={async (defect, values) => {
            if (relevantAnalysis) await onRequest(async () => { await request(`${path}/analyses/${relevantAnalysis.id}/events/${defect.id}`, { method: 'PATCH', data: values }); await onChange() })
          }}
          onListenDefect={defect => selectDefect(defect, true)}
          onPlan={profile => active ? onRequest(async () => {
            const analysisParam = relevantAnalysis ? `&analysis_id=${relevantAnalysis.id}` : ''
            const result = await request<{ operations: Operation[] }>(`${assetPath(project.id, active.id)}/plan?profile=${profile}${analysisParam}`)
            return result.operations
          }) : Promise.resolve(undefined)}
          onRestore={async (profile: Profile, operations: Operation[]) => Boolean(active && await onQueue(path + '/restore', { asset_id: active.id, profile, operations }))}
          onSelectAsset={select}
          onSelectTrack={track => { select(track); setRestorationTarget(track.id) }}
          onListen={asset => transport.select(asset)}
          onVersionStatus={async (asset, status) => {
            await onRequest(async () => { await request(assetPath(project.id, asset.id), { method: 'PATCH', data: { status } }); await onChange() })
          }} />
      </div>}
      {source && <Mixer assets={mixerAssets} versionLabels={versionLabels} analyses={project.analyses} settings={selectedMix} sampleCount={count} sampleRate={rate} busy={!mutable} master={master} live={transport.liveMode ? transport.liveState : undefined} liveAvailable={monitorConfig.tracks.length > 0}
        onLive={transport.startLive} onChange={settings => setDraftMixer({ sourceId: source.id, settings })} onRender={() => void render()} onListen={asset => transport.select(asset)} />}
    </>
  )
}

export function Studio() {
  const [view, setView] = useState<View>('projects')
  const [projects, setProjects] = useState<Project[]>([])
  const [project, setProject] = useState<Project>()
  const [health, setHealth] = useState<Health>()
  const [models, setModels] = useState<Model[]>([])
  const [selectedModelId, setSelectedModelId] = useState(() => storedValue('sonora.model', ''))
  const [globalJobs, setGlobalJobs] = useState<Job[]>([])
  const [busy, setBusy] = useState(false)
  const [initializing, setInitializing] = useState(true)
  const [error, setError] = useState('')
  const [notification, setNotification] = useState('')
  const lock = useRef(false)
  const desiredProjectId = useRef<string | undefined>(undefined)
  const completed = useRef(new Set<string>())

  async function loadProjects() {
    const values = await request<Project[]>('/projects')
    setProjects(values)
    return values
  }

  async function loadProject(id: string) {
    const data = await request<Project>(projectPath(id))
    if (desiredProjectId.current === id) {
      setProject(data)
      setProjects(values => [data, ...values.filter(value => value.id !== data.id)])
    }
    return data
  }

  async function refreshProject() {
    if (desiredProjectId.current) await loadProject(desiredProjectId.current)
  }

  async function loadModels() {
    const values = await request<Model[]>('/models')
    setModels(previous => values.map(value => {
      const verified = previous.find(model => model.id === value.id && model.status === 'verified' && model.sha256 === value.sha256)
      return value.status === 'installed' && verified ? verified : value
    }))
  }

  useEffect(() => {
    let cancelled = false
    async function initialize() {
      setInitializing(true)
      setError('')
      const results = await Promise.allSettled([request<Project[]>('/projects'), request<Model[]>('/models'), request<Health>('/health'), request<Job[]>('/jobs')])
      if (cancelled) return
      const [projectsResult, modelsResult, healthResult, jobsResult] = results
      if (projectsResult.status === 'fulfilled') {
        const values = projectsResult.value
        setProjects(values)
        const previous = values.find(item => item.id === storedValue('sonora.project', '') && !item.archived)
        if (previous) {
          desiredProjectId.current = previous.id
          setProject(previous)
          setView('studio')
        }
      } else {
        setError(errorText(projectsResult.reason))
      }
      if (modelsResult.status === 'fulfilled') setModels(modelsResult.value)
      else if (projectsResult.status === 'fulfilled') setError(errorText(modelsResult.reason))
      if (healthResult.status === 'fulfilled') setHealth(healthResult.value)
      if (jobsResult.status === 'fulfilled') setGlobalJobs(jobsResult.value)
      setInitializing(false)
    }
    void initialize()
    return () => { cancelled = true }
  }, [])

  const { jobs, updateJob } = useJobs([...(project?.jobs ?? []), ...globalJobs], project?.id, job => {
    const settledKey = `${job.id}/${job.status}/${job.attempts ?? 0}`
    if (completed.current.has(settledKey)) return
    completed.current.add(settledKey)
    if (job.project_id === null) {
      void loadModels().catch(error => setError(errorText(error)))
    } else if (job.project_id === desiredProjectId.current) {
      void refreshProject().catch(error => setError(errorText(error)))
    }
  })
  const activeJobs = jobs.filter(isActive)

  async function run<T>(action: () => Promise<T>): Promise<T | undefined> {
    if (lock.current) return undefined
    lock.current = true
    setBusy(true)
    setError('')
    setNotification('')
    try {
      return await action()
    } catch (error) {
      setError(errorText(error))
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  async function queue(path: string, data: unknown) {
    return run(async () => {
      const job = await request<Job>(path, { method: 'POST', data })
      updateJob(job)
      return job
    })
  }

  function open(value: Project) {
    desiredProjectId.current = value.id
    setProject(value)
    setView('studio')
    storeValue('sonora.project', value.id)
  }

  function chooseModel(id: string) {
    setSelectedModelId(id)
    storeValue('sonora.model', id)
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <Wordmark />
        <div className="top-project">{project?.name ?? 'Intelligent Audio Restoration Studio'}</div>
        <div className="top-status">
          {health && <><span className="hardware-label" title={health.platform}>{health.machine.toUpperCase()}</span><span className="hardware-label" title="Disponibilità backend rilevata dal servizio">{health.mps ? 'MPS disponibile' : 'CPU'}</span>{health.memory_bytes ? <span className="hardware-label">{fileSize(health.memory_bytes)}</span> : null}</>}
          <span className="local-status"><i className={`status-dot${health ? ' active' : ''}`} />{health ? 'Locale' : 'Servizio'}</span>
          {activeJobs.length > 0 && <span className="hardware-label">{activeJobs.length} in coda</span>}
        </div>
      </header>
      <nav className="navigation" aria-label="Navigazione principale">
        {views.map(item => <button type="button" key={item.id} aria-current={view === item.id ? 'page' : undefined} onClick={() => setView(item.id)}><Glyph icon={item.id} />{item.label}</button>)}
      </nav>
      <main className="content">
        {error && <div className="notice error top-notice" role="alert"><span>{error}</span><button type="button" aria-label="Chiudi errore" onClick={() => setError('')}>×</button></div>}
        {notification && <div className="notice success top-notice" role="status"><span>{notification}</span><button type="button" aria-label="Chiudi notifica" onClick={() => setNotification('')}>×</button></div>}
        {initializing && <p className="notice" role="status">Connessione al servizio locale…</p>}
        {view === 'projects' && <Projects projects={projects} current={project} busy={busy || initializing} onOpen={item => void run(async () => { open(item); await loadProject(item.id) })}
          onCreate={name => void run(async () => { open(await request<Project>('/projects', { method: 'POST', data: { name } })); await loadProjects() })}
          onDuplicate={item => void run(async () => { open(await request<Project>(projectPath(item.id) + '/duplicate', { method: 'POST', data: { name: `${item.name.slice(0, 110)} (copia)` } })); await loadProjects() })}
          onArchive={item => void run(async () => {
            const patched = await request<Project>(projectPath(item.id), { method: 'PATCH', data: { archived: !item.archived } })
            if (desiredProjectId.current === item.id) setProject(patched)
            await loadProjects()
          })} />}
        {view === 'studio' && (project ? <ProjectStudio key={project.id} project={project} health={health} models={models} selectedModelId={selectedModelId} setSelectedModelId={chooseModel} busy={busy} onNavigate={setView} onQueue={queue} onRequest={run} onChange={refreshProject} />
          : <section className="panel page-panel"><header className="panel-heading"><h2>Studio</h2></header><div className="copy-space"><p>Apri un progetto per importare l’audio.</p><button type="button" className="primary" onClick={() => setView('projects')}>Vai ai progetti</button></div></section>)}
        {view === 'models' && <ModelCatalog models={models} busy={busy} selectedId={selectedModelId}
          onInstall={model => void queue(modelPath(model.id) + '/install', undefined).then(job => {
            if (job) {
              chooseModel(model.id)
              setGlobalJobs(values => [job, ...values.filter(item => item.id !== job.id)])
            }
          })}
          onVerify={model => void run(async () => {
            const verified = await request<Model>(modelPath(model.id) + '/verify')
            setModels(current => current.map(item => item.id === verified.id ? verified : item))
            setNotification(`SHA-256 verificato per ${verified.name}.`)
          })} />}
        {view === 'report' && <Exports exports={project?.exports ?? []} master={preferredAsset(project?.assets ?? [], 'master')} busy={busy || !project || project.archived}
          onSubmit={options => {
            const master = preferredAsset(project?.assets ?? [], 'master')
            if (project && master) void queue(projectPath(project.id) + '/export', { mix_id: master.id, ...options })
          }} />}
        {view === 'settings' && <Settings health={health} />}
        {(view !== 'projects' || jobs.length > 0) && <JobQueue jobs={jobs} busy={busy} onJobAction={(job, action) => void run(async () => {
          const updated = await request<Job>(jobPath(job.id) + '/' + action, { method: 'POST' })
          updateJob(updated)
          if (updated.project_id === desiredProjectId.current) await refreshProject()
        })} />}
      </main>
    </div>
  )
}
