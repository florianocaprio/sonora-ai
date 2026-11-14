import { useEffect, useRef, useState } from 'react'
import type { Analysis, AudioAsset, Defect, Depth, Metric, Model, Operation, OperationType, Profile, Region } from './api'
import { formatNumber, formatTime, restorationProfiles, stemNames } from './api'

type InspectorTab = 'analysis' | 'restoration' | 'versions'

const operationNames: Record<OperationType, string> = {
  dc_remove: 'Rimozione DC',
  dehum: 'Filtro antironzio',
  declick: 'Riparazione click',
  peq: 'Equalizzatore parametrico',
  microgap: 'Interpolazione micro-gap',
  inpaint: 'Inpainting neurale',
}

const defectStatuses: Record<Defect['status'], string> = {
  unreviewed: 'Da rivedere',
  confirmed: 'Confermato',
  dismissed: 'Escluso',
  repaired: 'Riparato',
}
const versionStatuses: Record<AudioAsset['status'], string> = { approved: 'Approvata', proposed: 'Da approvare', rejected: 'Rifiutata' }
const versionKinds: Record<AudioAsset['kind'], string> = { original: 'Originale', separated: 'Separata', restored: 'Restaurata', preview: 'Anteprima', difference: 'Differenza' }

interface Parameter {
  key: string
  label: string
  initial: number
  min: number
  max: number
  step: number
  help: string
}

const commonFrequency = { key: 'frequency_hz', label: 'Frequenza (Hz)', min: 20, max: 20_000, step: 1, help: 'Centro della banda interessata.' }
const commonQ = { key: 'q', label: 'Fattore Q', min: 0.1, max: 80, step: 0.1, help: 'Un fattore Q alto restringe la banda.' }
const parameters: Record<OperationType, Parameter[]> = {
  inpaint: [],
  dc_remove: [],
  dehum: [{ ...commonFrequency, initial: 50 }, { ...commonQ, initial: 30 }],
  declick: [{ key: 'threshold', label: 'Soglia', initial: 0.08, min: 0.001, max: 2, step: 0.001, help: 'Scostamento minimo del campione rispetto agli adiacenti.' }],
  peq: [{ ...commonFrequency, initial: 1400 }, { ...commonQ, initial: 1 },
    { key: 'gain_db', label: 'Guadagno (dB)', initial: 1.5, min: -24, max: 24, step: 0.1, help: 'Amplifica o attenua la banda centrata sulla frequenza indicata.' }],
  microgap: [{ key: 'max_duration_ms', label: 'Durata massima (ms)', initial: 20, min: 1, max: 20, step: 1, help: 'Oltre questo limite la ricostruzione viene rifiutata.' }],
}

const meterLabels: Record<string, string> = {
  sample_peak_dbfs: 'Picco campionato (dBFS)',
  rms_dbfs: 'RMS (dBFS)',
  true_peak_dbtp: 'True peak (dBTP)',
  integrated_lufs: 'Loudness integrata (LUFS)',
  stereo_correlation: 'Correlazione stereo',
  gain_reduction_db: 'Riduzione gain (dB)',
  momentary_lufs: 'Loudness finale momentanea (LUFS)',
  short_term_lufs: 'Loudness finale short-term (LUFS)',
  lra_lu: 'Loudness range (LU)',
  backend: 'Misuratore',
  reason: 'Misura non disponibile',
  crest_factor_db: 'Fattore di cresta (dB)',
}

export function MetricList({ metrics }: { metrics: Record<string, Metric> }) {
  const loudness = metrics.loudness
  const fields = typeof loudness === 'object' && loudness && !Array.isArray(loudness) ? { ...metrics, ...loudness } : metrics
  const scalars = Object.entries(fields).filter(([, value]) => value === null || ['number', 'string'].includes(typeof value))
  return scalars.length > 0 ? (
    <dl className="metrics-list">
      {scalars.map(([key, value]) => (
        <div key={key}><dt>{meterLabels[key] ?? key.replaceAll('_', ' ')}</dt><dd>{typeof value === 'number' ? formatNumber.format(value) : typeof value === 'string' ? value : 'N/D'}</dd></div>
      ))}
    </dl>
  ) : <p className="hint">Nessuna misura disponibile.</p>
}

function DefectDetail({ defect, source, busy, onSave, onListen, onRestore }: {
  defect: Defect
  source: AudioAsset
  busy: boolean
  onSave: (values: Partial<Defect>) => Promise<void>
  onListen: () => void
  onRestore: () => void
}) {
  const [start, setStart] = useState(defect.start_sample)
  const [end, setEnd] = useState(defect.end_sample)
  const [note, setNote] = useState(defect.note ?? '')
  const canSave = start >= 0 && end > start && end <= source.metadata.sample_count
  return (
    <form className="defect-detail inset" onSubmit={event => {
      event.preventDefault()
      void onSave({ start_sample: start, end_sample: end, note })
    }}>
      <h3>{defect.type.replaceAll('_', ' ')}</h3>
      <p className="hint">Gravità {defect.severity} · Confidenza euristica {formatNumber.format(defect.confidence)}{defect.origin ? ` · Origine ${defect.origin}` : ''}</p>
      <div className="input-pair">
        <label>Inizio (campioni)<input type="number" min={0} max={Math.max(0, end - 1)} step={1} value={start} onChange={event => setStart(Number(event.target.value))} /></label>
        <label>Fine (campioni)<input type="number" min={start + 1} max={source.metadata.sample_count} step={1} value={end} onChange={event => setEnd(Number(event.target.value))} /></label>
      </div>
      {defect.evidence && <details><summary>Misure di supporto</summary><MetricList metrics={defect.evidence} /></details>}
      <label>Nota<textarea rows={2} value={note} maxLength={1000} onChange={event => setNote(event.target.value)} /></label>
      <div className="wrap-actions">
        <button type="submit" disabled={busy || !canSave}>Salva dettagli</button>
        <button type="button" disabled={busy || defect.status === 'confirmed'} onClick={() => void onSave({ status: 'confirmed' })}>Conferma</button>
        <button type="button" disabled={busy || defect.status === 'dismissed'} onClick={() => void onSave({ status: 'dismissed' })}>Escludi</button>
        <button type="button" onClick={onListen}>Ascolta regione</button>
        <button type="button" disabled={defect.status === 'dismissed'} onClick={onRestore}>Apri restauro</button>
      </div>
    </form>
  )
}

function Knob({ value, param, onChange }: { value: number; param: Parameter; onChange: (value: number) => void }) {
  return (
    <div className="dual-control">
      <label title={param.help}><span>{param.label}</span><input type="range" value={value} min={param.min} max={param.max} step={param.step} onChange={event => onChange(Number(event.target.value))} /></label>
      <input aria-label={`Valore ${param.label}`} type="number" value={value} min={param.min} max={param.max} step={param.step} onChange={event => onChange(Number(event.target.value))} />
      <button className="icon-button" type="button" title="Valore predefinito" aria-label={`Ripristina ${param.label}`} onClick={() => onChange(param.initial)}>↺</button>
    </div>
  )
}

function Operations({ operations, rate, maxSample, onChange }: {
  operations: Operation[]
  rate: number
  maxSample: number
  onChange: (operations: Operation[]) => void
}) {
  function update(index: number, patch: Partial<Operation>) {
    onChange(operations.map((operation, i) => i === index ? { ...operation, ...patch } : operation))
  }

  function move(index: number, delta: number) {
    const next = [...operations]
    const other = index + delta
    const previous = next[other]
    next[other] = next[index]
    next[index] = previous
    onChange(next)
  }

  return operations.map((op, index) => (
    <details key={`${op.type}-${index}`} className="operation inset" open={operations.length === 1 || undefined}>
      <summary><strong>{operationNames[op.type]}</strong><small>{op.bypass ? 'Bypass' : `${formatTime(op.start_sample, rate)} – ${formatTime(op.end_sample, rate)}`}</small></summary>
      <div className="panel-flow">
        <div className="wrap-actions">
          <label className="inline-check"><input type="checkbox" checked={op.bypass ?? false} onChange={event => update(index, { bypass: event.target.checked })} /> Bypass</label>
          <button type="button" className="icon-button" disabled={index === 0} onClick={() => move(index, -1)} aria-label="Sposta operazione in alto">↑</button>
          <button type="button" className="icon-button" disabled={index === operations.length - 1} onClick={() => move(index, 1)} aria-label="Sposta operazione in basso">↓</button>
          <button type="button" onClick={() => onChange(operations.filter((_, i) => i !== index))}>Rimuovi</button>
        </div>
        <div className="input-pair">
          <label>Inizio<input type="number" min={0} max={Math.max(0, op.end_sample - 1)} step={1} value={op.start_sample} onChange={event => update(index, { start_sample: Number(event.target.value) })} /></label>
          <label>Fine<input type="number" min={op.start_sample + 1} max={maxSample} step={1} value={op.end_sample} onChange={event => update(index, { end_sample: Number(event.target.value) })} /></label>
        </div>
        {op.type === 'inpaint' ? (
          <label>Seed<input type="number" min={0} max={2147483647} step={1} value={op.params.seed ?? 0}
            onChange={event => update(index, { params: { seed: Number(event.target.value) } })} /></label>
        ) : <Knob value={Math.round(op.wet * 100)} param={{ key: 'wet', label: 'Wet (%)', initial: 100, min: 0, max: 100, step: 1, help: 'Miscela tra segnale in ingresso e segnale elaborato.' }} onChange={wet => update(index, { wet: wet / 100 })} />}
        {parameters[op.type]?.map(param => (
          <Knob key={param.key} param={param.key === 'frequency_hz' ? { ...param, max: Math.min(param.max, Math.floor(rate * 0.49)) } : param} value={op.params[param.key] ?? param.initial} onChange={value => update(index, { params: { ...op.params, [param.key]: value } })} />
        ))}
      </div>
    </details>
  ))
}

const presetsKey = 'sonora.restoration.presets'

interface RestorationDraft { profile: Profile; chains: Record<Profile, Operation[]> }

function readDraft(key?: string): RestorationDraft {
  try {
    const saved = key ? JSON.parse(localStorage.getItem(key) ?? 'null') as RestorationDraft | null : null
    if (saved && Object.hasOwn(restorationProfiles, saved.profile) &&
      Array.isArray(saved.chains?.basic) && Array.isArray(saved.chains.medium) && Array.isArray(saved.chains.high)) return saved
  } catch {
    // Treat unavailable or unreadable storage as an empty draft.
  }
  return { profile: 'basic', chains: { basic: [], medium: [], high: [] } }
}

interface SavedPlan { name: string; stem: AudioAsset['stem']; profile: Profile; operations: Operation[] }
function readPresets(): SavedPlan[] {
  try {
    return (JSON.parse(localStorage.getItem(presetsKey) ?? '[]') as SavedPlan[])
  } catch {
    return []
  }
}

export function Inspector({ asset, versions, versionLabels, restorationTracks, draftKey, openRestoration, inpaintModel, analysis, selectedEvent, region, busy, onAnalyze, onDefect, onSaveDefect, onListenDefect, onPlan, onRestore, onSelectAsset, onSelectTrack, onListen, onVersionStatus }: {
  asset?: AudioAsset
  versions: AudioAsset[]
  versionLabels: Map<string, string>
  restorationTracks: AudioAsset[]
  draftKey?: string
  openRestoration: boolean
  inpaintModel?: Model
  analysis?: Analysis
  selectedEvent: Defect | undefined
  region: Region | null
  busy: boolean
  onAnalyze: (settings: { depth: Depth; sensitivity: number; region?: Region }) => Promise<void>
  onDefect: (defect: Defect) => void
  onSaveDefect: (defect: Defect, values: Partial<Defect>) => Promise<void>
  onListenDefect: (defect: Defect) => void
  onPlan: (profile: Profile) => Promise<Operation[] | undefined>
  onRestore: (profile: Profile, operations: Operation[]) => Promise<boolean>
  onSelectAsset: (asset: AudioAsset) => void
  onSelectTrack: (asset: AudioAsset) => void
  onListen: (asset: AudioAsset) => void
  onVersionStatus: (asset: AudioAsset, status: 'approved' | 'rejected') => Promise<void>
}) {
  const [tab, setTab] = useState<InspectorTab>(openRestoration ? 'restoration' : 'analysis')
  const [depth, setDepth] = useState<Depth>('standard')
  const [sensitivity, setSensitivity] = useState(0.5)
  const [statusFilter, setStatusFilter] = useState<Defect['status'] | ''>('')
  const [typeFilter, setTypeFilter] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [eventPage, setEventPage] = useState(0)
  const [draft, setDraft] = useState(() => readDraft(draftKey))
  const currentDraft = useRef(draft)
  const planRequest = useRef<AbortController | null>(null)
  const [draftError, setDraftError] = useState(false)
  const { profile, chains } = draft
  const operations = chains[profile]
  const [operationType, setOperationType] = useState<OperationType>('dc_remove')
  const [planName, setPlanName] = useState('')
  const [presets, setPresets] = useState(readPresets)
  const [presetError, setPresetError] = useState('')
  const [regional, setRegional] = useState(false)
  useEffect(() => () => planRequest.current?.abort(), [])
  const allEvents = analysis?.events ?? []
  const visibleEvents = allEvents.filter(event => (!statusFilter || event.status === statusFilter) && (!typeFilter || event.type === typeFilter) && (!severityFilter || String(event.severity) === severityFilter))
  const pageLength = 20
  const page = Math.min(eventPage, Math.max(0, Math.ceil(visibleEvents.length / pageLength) - 1))
  const offset = asset?.metadata.start_sample ?? 0
  const exactRegion = region && asset ? {
    start_sample: Math.max(0, region.start_sample - offset),
    end_sample: Math.min(asset.metadata.sample_count, region.end_sample - offset),
  } : undefined
  const selection = exactRegion && exactRegion.end_sample > exactRegion.start_sample ? exactRegion : undefined
  const sampleRate = asset?.metadata.sample_rate ?? 0
  const sampleCount = asset?.metadata.sample_count ?? 0

  const inpaintReady = ['installed', 'verified', 'ready'].includes(inpaintModel?.status ?? '')
  const inpaintAllowed = profile === 'high' && inpaintReady
  const minGap = inpaintModel?.min_gap_ms ?? 20
  const maxGap = inpaintModel?.max_gap_ms ?? 250
  const sideContext = inpaintModel?.min_context_ms_per_side ?? 250
  const inpaintAdded = operations.some(op => op.type === 'inpaint' && !op.bypass)
  const selectedOperation = (operationType === 'inpaint' && !inpaintAllowed) || (operationType === 'microgap' && profile !== 'high')
    ? 'dc_remove' : operationType

  function saveDraft(next: RestorationDraft) {
    currentDraft.current = next
    setDraft(next)
    if (!draftKey) return
    try {
      localStorage.setItem(draftKey, JSON.stringify(next))
      setDraftError(false)
    } catch {
      setDraftError(true)
    }
  }

  function setOperations(next: Operation[]) {
    const current = currentDraft.current
    saveDraft({ ...current, chains: { ...current.chains, [profile]: next } })
  }

  function appendOperation(targetProfile: Profile, operation: Operation) {
    saveDraft({ profile: targetProfile, chains: { ...chains, [targetProfile]: [...chains[targetProfile], operation] } })
  }

  function newOperation() {
    const start = Math.ceil(sampleRate * sideContext / 1000)
    const target = selection ?? (selectedOperation === 'inpaint'
      ? { start_sample: start, end_sample: start + Math.floor(sampleRate * Math.min(100, maxGap) / 1000) }
      : { start_sample: 0, end_sample: sampleCount })
    appendOperation(profile, {
      ...target,
      type: selectedOperation,
      wet: 1,
      params: Object.fromEntries(parameters[selectedOperation].map(param => [param.key, param.initial])),
    })
  }

  async function suggestPlan() {
    const pending = new AbortController()
    planRequest.current?.abort()
    planRequest.current = pending
    const plan = await onPlan(profile)
    if (plan && !pending.signal.aborted && currentDraft.current.chains[profile] === operations) {
      setOperations(selection ? plan.map(op => ({
        ...op,
        start_sample: Math.max(op.start_sample, selection.start_sample),
        end_sample: Math.min(op.end_sample, selection.end_sample),
      })).filter(op => op.start_sample < op.end_sample) : plan)
    }
  }

  function storePreset() {
    if (!asset || !planName.trim()) return
    const name = planName.trim()
    const next = [...presets.filter(preset => preset.name !== name || preset.stem !== asset.stem || preset.profile !== profile), { name, stem: asset.stem, profile, operations }]
    try {
      localStorage.setItem(presetsKey, JSON.stringify(next))
      setPresets(next)
      setPresetError('')
      setPlanName('')
    } catch {
      setPresetError('Il browser non consente di salvare il preset.')
    }
  }

  function usePreset(name: string) {
    const preset = presets.find(item => item.name === name && item.stem === asset?.stem && item.profile === profile)
    if (!preset) return
    setOperations(preset.operations.map(op => {
      if (!selection) return { ...op, end_sample: Math.min(op.end_sample, sampleCount) }
      const end = op.type === 'microgap' || op.type === 'inpaint'
        ? Math.min(selection.end_sample, selection.start_sample + op.end_sample - op.start_sample)
        : selection.end_sample
      return { ...op, start_sample: selection.start_sample, end_sample: end }
    }).filter(op => op.start_sample < op.end_sample))
  }

  function takeDefect(defect: Defect) {
    setTab('restoration')
    const proposal = defect.proposal ?? defect.proposed_operation
    const proposedType = typeof proposal === 'string' ? proposal : proposal?.type
    if (proposedType && proposedType in parameters) {
      const type = proposedType as OperationType
      const targetProfile = type === 'microgap' || type === 'inpaint' ? 'high' : type === 'peq' ? 'medium' : profile
      const defaults = Object.fromEntries(parameters[type].map(param => [param.key, param.initial]))
      appendOperation(targetProfile, {
        type, start_sample: defect.start_sample, end_sample: defect.end_sample,
        wet: typeof proposal === 'object' && proposal ? proposal.wet ?? 1 : 1,
        params: typeof proposal === 'object' && proposal ? { ...defaults, ...proposal.params } : defaults,
      })
    }
  }

  const canRestore = asset && asset.status === 'approved' && asset.kind !== 'preview' && !['master', 'difference', 'residual'].includes(asset.stem)
  function invalidInpaint(op: Operation) {
    const frames = op.end_sample - op.start_sample
    const seed = op.params.seed ?? 0
    return !inpaintAllowed || frames * 1000 < sampleRate * minGap || frames * 1000 > sampleRate * maxGap
      || Math.min(op.start_sample, sampleCount - op.end_sample) * 1000 < sampleRate * sideContext
      || !Number.isInteger(seed) || seed < 0 || seed > 2147483647
  }

  const invalidOperations = operations.filter(op => !op.bypass).filter(op => op.type === 'inpaint').length > 1 || operations.some(op => op.start_sample < 0 || op.end_sample > sampleCount || op.end_sample <= op.start_sample ||
    op.wet < 0 || op.wet > 1 || (op.type === 'microgap' && !op.bypass && (profile !== 'high' || (op.end_sample - op.start_sample) / sampleRate * 1000 > (op.params.max_duration_ms ?? 20))) ||
    (op.type === 'inpaint' && !op.bypass && invalidInpaint(op)) ||
    (typeof op.params.frequency_hz === 'number' && op.params.frequency_hz > Math.floor(sampleRate * 0.49)))
  const activeOperations = operations.filter(op => !op.bypass).length
  const needsConfiguration = !activeOperations || invalidOperations

  async function startRestoration() {
    if (needsConfiguration) {
      setTab('restoration')
      return
    }
    if (await onRestore(profile, operations)) setTab('versions')
  }

  return (
    <aside className="panel inspector" aria-label="Inspector">
      <header className="panel-heading"><h2>Inspector</h2>{asset && <span className={`track-chip track-${asset.stem}`}>{stemNames[asset.stem]}</span>}</header>
      <div className="restoration-action panel-flow">
        {restorationTracks.length > 0 && <div className="profile-selector" role="group" aria-label="Traccia da restaurare">
          {restorationTracks.map(track => <button key={track.stem} type="button" aria-pressed={asset?.stem === track.stem}
            aria-label={`Restauro ${stemNames[track.stem]}`} onClick={() => {
              setTab('restoration')
              if (asset?.id !== track.id) onSelectTrack(track)
            }}>{stemNames[track.stem]}</button>)}
        </div>}
        {canRestore && <p className="restoration-context">{stemNames[asset.stem]} · {versionLabels.get(asset.id) ?? versionKinds[asset.kind]} · {restorationProfiles[profile]}</p>}
        <button type="button" className="primary" aria-describedby="restoration-status" disabled={busy || !canRestore || (tab === 'restoration' && needsConfiguration)} onClick={() => void startRestoration()}>Avvia restauro</button>
        <p className="hint" id="restoration-status">{!canRestore ? 'Seleziona un originale o uno stem completo e approvato.'
          : invalidOperations ? 'Verifica la catena in Restauro.'
          : activeOperations ? `${activeOperations} ${activeOperations === 1 ? 'intervento attivo' : 'interventi attivi'}`
          : 'Aggiungi o proponi una catena in Restauro.'}</p>
        {draftError && <p className="notice error" role="alert">Salvataggio automatico non riuscito. Verifica le impostazioni del browser.</p>}
      </div>
      <div className="inspector-tabs" aria-label="Pannello inspector">
        <button type="button" aria-pressed={tab === 'analysis'} onClick={() => setTab('analysis')}>Difetti</button>
        <button type="button" aria-pressed={tab === 'restoration'} onClick={() => setTab('restoration')}>Restauro</button>
        <button type="button" aria-pressed={tab === 'versions'} onClick={() => setTab('versions')}>Versioni</button>
      </div>
      {!asset ? <div className="inspector-content"><p className="hint">Importa una traccia per aprire l’inspector.</p></div> : (
        <div className="inspector-content panel-flow">
          {tab === 'analysis' && <>
            <form className="panel-flow" onSubmit={event => { event.preventDefault(); void onAnalyze({ depth, sensitivity, region: regional ? selection : undefined }) }}>
              <label>Profondità<select value={depth} onChange={event => setDepth(event.target.value as Depth)}><option value="quick">Rapida</option><option value="standard">Standard</option><option value="deep">Approfondita</option></select></label>
              <Knob value={Math.round(sensitivity * 100)} param={{ key: 'sensitivity', label: 'Sensibilità (%)', initial: 50, min: 0, max: 100, step: 1, help: 'Regola le soglie del profilo di rilevamento.' }} onChange={value => setSensitivity(value / 100)} />
              <label className="inline-check" title={selection ? 'Usa la selezione della timeline' : 'Seleziona una regione sulla timeline'}><input type="checkbox" checked={regional && Boolean(selection)} disabled={!selection} onChange={event => setRegional(event.target.checked)} /> Solo regione</label>
              <button type="submit" className="primary" disabled={busy}>Analizza traccia</button>
            </form>
            {analysis && <>
              <details className="inset"><summary>Misure del segnale</summary><MetricList metrics={analysis.metrics} /></details>
              <div className="input-pair">
                <label>Tipo<select value={typeFilter} onChange={event => { setTypeFilter(event.target.value); setEventPage(0) }}><option value="">Tutti</option>{[...new Set(allEvents.map(event => event.type))].map(type => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}</select></label>
                <label>Stato<select value={statusFilter} onChange={event => { setStatusFilter(event.target.value as typeof statusFilter); setEventPage(0) }}><option value="">Tutti</option>{Object.entries(defectStatuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              </div>
              <label>Gravità<select value={severityFilter} onChange={event => { setSeverityFilter(event.target.value); setEventPage(0) }}><option value="">Tutte</option>{[...new Set(allEvents.map(event => String(event.severity)))].map(severity => <option key={severity} value={severity}>{severity}</option>)}</select></label>
              <ul className="defect-list">
                {visibleEvents.slice(page * pageLength, (page + 1) * pageLength).map(defect => (
                  <li key={defect.id}><button type="button" aria-pressed={selectedEvent?.id === defect.id} onClick={() => onDefect(defect)}><span><strong>{defect.type.replaceAll('_', ' ')}</strong><small>{defectStatuses[defect.status]} · Gravità {defect.severity}</small></span><time>{formatTime(defect.start_sample + offset, sampleRate)}</time></button></li>
                ))}
              </ul>
              {!visibleEvents.length && <p className="hint">Nessuna anomalia con i filtri selezionati.</p>}
              {visibleEvents.length > pageLength && <div className="page-control"><button type="button" disabled={page === 0} onClick={() => setEventPage(page - 1)}>‹ Indietro</button><span>{page + 1}/{Math.ceil(visibleEvents.length / pageLength)}</span><button type="button" disabled={(page + 1) * pageLength >= visibleEvents.length} onClick={() => setEventPage(page + 1)}>Avanti ›</button></div>}
              {selectedEvent && <DefectDetail key={`${selectedEvent.id}-${selectedEvent.start_sample}-${selectedEvent.end_sample}-${selectedEvent.note ?? ''}`} defect={selectedEvent} source={asset} busy={busy} onSave={values => onSaveDefect(selectedEvent, values)} onListen={() => onListenDefect(selectedEvent)} onRestore={() => takeDefect(selectedEvent)} />}
            </>}
          </>}
          {tab === 'restoration' && !canRestore && <p className="hint">Seleziona un originale o uno stem completo e approvato per il restauro.</p>}
          {tab === 'restoration' && canRestore && <>
            <div className="profile-selector" aria-label="Profilo di restauro">
              {(Object.keys(restorationProfiles) as Profile[]).map(value => <button type="button" key={value} aria-pressed={profile === value} onClick={() => saveDraft({ ...draft, profile: value })}>{restorationProfiles[value]}</button>)}
            </div>
            <p className="hint">{profile === 'basic' ? 'Interventi conservativi su difetti tecnici.' : profile === 'medium' ? 'Interventi conservativi ed equalizzazione correttiva.' : 'Ricostruzione di micro-gap e anteprima neurale da ascoltare e approvare.'}</p>
            {profile === 'high' && inpaintModel && <p className="hint">
              {inpaintReady ? `${inpaintModel.name}. Regione da ${minGap} a ${maxGap} ms, con almeno ${sideContext} ms ai lati.`
                : 'Installa il modello di inpainting dalla pagina Modelli.'}
            </p>}
            <button type="button" disabled={busy} onClick={() => void suggestPlan()}>Proponi catena</button>
            <Operations key={profile} operations={operations} rate={sampleRate} maxSample={sampleCount} onChange={setOperations} />
            <div className="field-action">
              <select aria-label="Processore di restauro" value={selectedOperation} onChange={event => setOperationType(event.target.value as OperationType)}>{Object.entries(operationNames).map(([value, label]) => <option key={value} value={value} disabled={(value === 'inpaint' && !inpaintAllowed) || (value === 'microgap' && profile !== 'high')}>{label}</option>)}</select>
              <button type="button" disabled={busy || (selectedOperation === 'inpaint' && inpaintAdded)} onClick={newOperation}>Aggiungi</button>
            </div>
            {invalidOperations && <p className="notice error" role="alert">Verifica gli estremi e le frequenze degli interventi. Per le ricostruzioni verifica il profilo, il contesto e la durata della regione.</p>}
            <details className="inset">
              <summary>Preset personali</summary>
              <div className="panel-flow">
                <div className="field-action">
                  <input aria-label="Nome preset" value={planName} maxLength={64} placeholder="Nome preset" onChange={event => setPlanName(event.target.value)} />
                  <button type="button" disabled={!operations.length || !planName.trim()} onClick={storePreset}>Salva</button>
                </div>
                <select aria-label="Carica preset" value="" onChange={event => usePreset(event.target.value)}><option value="">Carica su regione o traccia</option>{presets.filter(item => item.stem === asset.stem && item.profile === profile).map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</select>
                {presetError && <p className="notice error" role="alert">{presetError}</p>}
              </div>
            </details>
          </>}
          {tab === 'versions' && <>
            {!versions.length && <p className="hint">Nessuna versione disponibile.</p>}
            <ul className="version-list">
              {versions.map(version => (
                <li key={version.id} className="inset">
                  <div className="version-meta"><strong>{versionLabels.get(version.id) ?? versionKinds[version.kind]}</strong><small>{versionStatuses[version.status]}</small></div>
                  <p>{version.name}</p>
                  {Boolean(version.metadata.generated_regions?.length) && <p className="hint">
                    Contiene audio generato. Ascolta la patch prima di approvarla.
                  </p>}
                  <div className="wrap-actions">
                    <button type="button" aria-pressed={version.id === asset.id} onClick={() => onSelectAsset(version)}>Seleziona</button>
                    <button type="button" disabled={version.status === 'rejected'} onClick={() => onListen(version)}>Ascolta</button>
                    {version.kind === 'restored' && version.status === 'proposed' && <>
                      <button type="button" className="primary" disabled={busy} onClick={() => void onVersionStatus(version, 'approved')}>Approva</button>
                      <button type="button" disabled={busy} onClick={() => void onVersionStatus(version, 'rejected')}>Rifiuta</button>
                    </>}
                  </div>
                </li>
              ))}
            </ul>
          </>}
        </div>
      )}
    </aside>
  )
}
