import { useState } from 'react'
import { audioMetrics, fileSize, formatNumber, preferredAsset, stemNames } from './api'
import type { Analysis, AudioAsset, AutomationPoint, Compressor, Metric, MixerSettings, Stem, TrackSettings } from './api'
import { MetricList } from './Inspector'
import type { LiveState, LiveStem } from './liveMixTypes'

const channels = ['dialogue', 'music', 'effects', 'residual'] as const
const eqDefault = { frequency_hz: 1000, gain_db: 0, q: 1 }
const limiterDefault = { enabled: false, lookahead_ms: 5, release_ms: 80 }
const compressorDefault: Compressor = { threshold_db: -20, ratio: 2, knee_db: 6, attack_ms: 10, release_ms: 80, makeup_db: 0 }

const compressorFields = [
  { key: 'threshold_db', label: 'Soglia (dB)', min: -80, max: 0, step: 1 },
  { key: 'ratio', label: 'Rapporto', min: 1, max: 20, step: 0.1 },
  { key: 'knee_db', label: 'Knee (dB)', min: 0, max: 24, step: 0.1 },
  { key: 'attack_ms', label: 'Attacco (ms)', min: 0.1, max: 1000, step: 0.1 },
  { key: 'release_ms', label: 'Rilascio (ms)', min: 1, max: 3000, step: 1 },
  { key: 'makeup_db', label: 'Recupero (dB)', min: -24, max: 24, step: 0.1 },
] as const

interface StripProps {
  stem: Stem
  settings: TrackSettings
  candidates: AudioAsset[]
  sampleCount: number
  sampleRate: number
  renderedMetrics?: Record<string, Metric>
  livePeak?: number
  editable: boolean
  onChange: (settings: TrackSettings) => void
}

type LaneName = 'gain_db' | 'pan' | 'mute'

function AutomationEditor({ settings, sampleCount, onChange }: Pick<StripProps, 'settings' | 'sampleCount' | 'onChange'>) {
  const [lane, setLane] = useState<LaneName>('gain_db')
  const [sample, setSample] = useState(0)
  const [value, setValue] = useState(0)
  const points = settings.automation?.[lane] ?? []
  const max = lane === 'gain_db' ? 24 : lane === 'pan' ? 1 : 1
  const min = lane === 'gain_db' ? -90 : lane === 'pan' ? -1 : 0

  function update(points: AutomationPoint[]) {
    onChange({ ...settings, automation: { ...settings.automation, [lane]: points.sort((a, b) => a.sample - b.sample) } })
  }

  function add() {
    const adjustedValue = lane === 'mute' ? Boolean(value) : value
    update([...points.filter(point => point.sample !== sample), { sample, value: adjustedValue }])
  }

  return (
    <div className="panel-flow automation-panel">
      <label>Parametro<select value={lane} onChange={event => { setLane(event.target.value as LaneName); setValue(0) }}><option value="gain_db">Fader</option><option value="pan">Bilanciamento</option><option value="mute">Mute</option></select></label>
      <div className="input-pair">
        <label>Campione<input type="number" min={0} max={Math.max(0, sampleCount - 1)} step={1} value={sample} onChange={event => setSample(Number(event.target.value))} /></label>
        <label>{lane === 'gain_db' ? 'Valore (dB)' : 'Valore'}{lane === 'mute' ? <select value={value} onChange={event => setValue(Number(event.target.value))}><option value={0}>Udibile</option><option value={1}>Muto</option></select> : <input type="number" value={value} min={min} max={max} step={lane === 'pan' ? 0.01 : 0.1} onChange={event => setValue(Number(event.target.value))} />}</label>
      </div>
      <button type="button" disabled={sample < 0 || sample >= sampleCount || value < min || value > max} onClick={add}>Imposta punto</button>
      <ul className="automation-points">
        {points.map(point => <li key={point.sample}><span>{point.sample} · {String(point.value)}</span><button type="button" aria-label={`Rimuovi punto al campione ${point.sample}`} onClick={() => update(points.filter(item => item.sample !== point.sample))}>×</button></li>)}
      </ul>
    </div>
  )
}

function Strip({ stem, settings, candidates, sampleCount, sampleRate, renderedMetrics, livePeak, editable, onChange }: StripProps) {
  const master = stem === 'master'
  const asset = candidates.find(item => item.id === settings.asset_id)
  const fader = settings.gain_db ?? 0
  const eq = settings.eq?.[0]
  const compressor = settings.compressor
  const limiter = settings.limiter ?? limiterDefault
  const peak = livePeak === undefined
    ? renderedMetrics?.sample_peak_dbfs ?? audioMetrics(asset)?.sample_peak_dbfs
    : Math.max(-90, 20 * Math.log10(livePeak))
  const meterTitle = livePeak !== undefined ? 'Picco live' : renderedMetrics ? 'Picco misurato nell’ultimo render' : 'Picco misurato sul file'
  const patch = (partial: Partial<TrackSettings>) => onChange({ ...settings, ...partial })
  return (
    <article className={`channel-strip track-${stem}${master ? ' master-strip' : ''}`}>
      <h3><i className="track-marker" aria-hidden="true" />{stemNames[stem]}</h3>
      {!master && <label className="channel-source"><span className="sr-only">Sorgente {stemNames[stem]}</span><select value={settings.asset_id ?? ''} disabled={!editable} onChange={event => patch({ asset_id: event.target.value || undefined })}><option value="">Nessuna</option>{candidates.map(item => <option key={item.id} value={item.id}>{item.kind === 'restored' ? 'Restaurata' : item.kind === 'original' ? 'Originale' : 'Separata'} · {item.name}</option>)}</select></label>}
      <div className="fader-section">
        <div className="fader-marks" aria-hidden="true"><span>+24</span><span>0</span><span>−30</span><span>−60</span><span>−80</span></div>
        <input className="fader" type="range" min={-80} max={24} step={0.1} disabled={!editable} value={fader} aria-label={`Fader ${stemNames[stem]} (dB)`} onChange={event => patch({ gain_db: Number(event.target.value) })} />
        {typeof peak === 'number' && <meter className="peak-meter" min={-90} max={6} value={Math.max(-90, Math.min(6, peak))} low={-24} high={0} optimum={-12} aria-label={`${meterTitle} ${stemNames[stem]}`} title={`${meterTitle}: ${formatNumber.format(peak)} dBFS`} />}
      </div>
      <label className="fader-value"><span className="sr-only">Valore fader {stemNames[stem]}</span><input type="number" min={-80} max={24} step={0.1} value={fader} disabled={!editable} onChange={event => patch({ gain_db: Number(event.target.value) })} /><small>dB</small></label>
      {!master && <div className="toggle-pair"><button type="button" disabled={!editable} aria-pressed={settings.mute ?? false} onClick={() => patch({ mute: !settings.mute })}>Mute</button><button type="button" disabled={!editable} aria-pressed={settings.solo ?? false} onClick={() => patch({ solo: !settings.solo })}>Solo</button></div>}
      <details className="channel-settings">
        <summary>Processori</summary>
        <fieldset disabled={!editable} className="panel-flow">
          <label>Trim (dB)<input type="number" min={-36} max={24} step={0.1} value={settings.trim_db ?? 0} onChange={event => patch({ trim_db: Number(event.target.value) })} /></label>
          {!master && <>
            <label title="Pan per mono, bilanciamento per stereo">Pan / balance<input type="range" min={-1} max={1} step={0.01} value={settings.pan ?? 0} onChange={event => patch({ pan: Number(event.target.value) })} /><output>{formatNumber.format(settings.pan ?? 0)}</output></label>
            <label className="inline-check"><input type="checkbox" checked={settings.polarity ?? false} onChange={event => patch({ polarity: event.target.checked })} /> Inverti polarità</label>
          </>}
          <label className="inline-check"><input type="checkbox" checked={settings.bypass ?? false} onChange={event => patch({ bypass: event.target.checked })} /> Bypass processori</label>
          <label className="inline-check"><input type="checkbox" checked={Boolean(eq)} onChange={event => patch({ eq: event.target.checked ? [eqDefault] : [] })} /> EQ parametrico</label>
          {eq && <div className="panel-flow nested-controls">
            <label>Frequenza (Hz)<input type="number" min={20} max={Math.min(20_000, Math.floor(sampleRate * 0.49))} step={1} value={eq.frequency_hz} onChange={event => patch({ eq: [{ ...eq, frequency_hz: Number(event.target.value) }] })} /></label>
            <label>Guadagno (dB)<input type="number" min={-24} max={24} step={0.1} value={eq.gain_db} onChange={event => patch({ eq: [{ ...eq, gain_db: Number(event.target.value) }] })} /></label>
            <label>Fattore Q<input type="number" min={0.1} max={18} step={0.1} value={eq.q} onChange={event => patch({ eq: [{ ...eq, q: Number(event.target.value) }] })} /></label>
          </div>}
          <label className="inline-check"><input type="checkbox" checked={Boolean(compressor)} onChange={event => patch({ compressor: event.target.checked ? compressorDefault : undefined })} /> Compressore</label>
          {compressor && <div className="panel-flow nested-controls">
            {compressorFields.map(field => <label key={field.key}>{field.label}<input type="number" min={field.min} max={field.max} step={field.step} value={compressor[field.key]} onChange={event => patch({ compressor: { ...compressor, [field.key]: Number(event.target.value) } })} /></label>)}
          </div>}
          {master && <>
            <label title="Tetto true peak del limiter, misurato sul file dopo il render">Ceiling (dBTP)<input type="number" min={-30} max={0} step={0.1} value={settings.ceiling_dbtp ?? -1} onChange={event => patch({ ceiling_dbtp: Number(event.target.value) })} /></label>
            <label className="inline-check" title="Attiva il limiter sul master live e sul render"><input type="checkbox" checked={limiter.enabled} onChange={event => patch({ limiter: { ...limiter, enabled: event.target.checked } })} /> Limiter true peak</label>
            {limiter.enabled && <div className="panel-flow nested-controls">
              <label>Lookahead (ms)<input type="number" min={1} max={20} step={1} value={limiter.lookahead_ms} onChange={event => patch({ limiter: { ...limiter, lookahead_ms: Number(event.target.value) } })} /></label>
              <label>Rilascio limiter (ms)<input type="number" min={10} max={1000} step={1} value={limiter.release_ms} onChange={event => patch({ limiter: { ...limiter, release_ms: Number(event.target.value) } })} /></label>
            </div>}
          </>}
          {!master && <details><summary>Automazioni</summary><AutomationEditor settings={settings} sampleCount={sampleCount} onChange={onChange} /></details>}
        </fieldset>
      </details>
    </article>
  )
}

export function initialMixer(assets: AudioAsset[], saved: MixerSettings | null): MixerSettings {
  const tracks: MixerSettings['tracks'] = { ...saved?.tracks }
  const separated = channels.slice(0, 3).some(stem => preferredAsset(assets, stem))
  if (separated) {
    delete tracks.original
  } else if (!tracks.original || (tracks.original.asset_id && !assets.some(asset => asset.id === tracks.original?.asset_id))) {
    tracks.original = { gain_db: 0, asset_id: preferredAsset(assets, 'original')?.id }
  }
  for (const stem of channels) {
    const savedTrack = saved?.tracks?.[stem]
    const latest = preferredAsset(assets, stem)
    const sourceIsValid = savedTrack?.asset_id && assets.some(asset => asset.id === savedTrack.asset_id && asset.status === 'approved' && asset.kind !== 'preview')
    tracks[stem] = { gain_db: 0, pan: 0, mute: stem === 'residual', ...savedTrack, asset_id: sourceIsValid ? savedTrack.asset_id : latest?.id }
  }
  return { tracks, master: saved?.master ?? { gain_db: 0, ceiling_dbtp: -1 } }
}

export function Mixer({ assets, analyses, settings, sampleCount, sampleRate, busy, master, live, liveAvailable, onLive, onChange, onRender, onListen }: {
  assets: AudioAsset[]
  analyses: Analysis[]
  settings: MixerSettings
  sampleCount: number
  sampleRate: number
  busy: boolean
  master?: AudioAsset
  live?: LiveState
  liveAvailable: boolean
  onLive: () => void
  onChange: (settings: MixerSettings) => void
  onRender: () => void
  onListen: (master: AudioAsset) => void
}) {
  const selected = Object.values(settings.tracks).filter(track => track.asset_id)
  const hasSolo = selected.some(track => track.solo && !track.mute)
  const hasSource = selected.some(track => !track.mute && (!hasSolo || track.solo))
  const loaded = audioMetrics(master)
  const size = master?.metadata.size_bytes
  const masterMetrics: Record<string, Metric> = { ...loaded }
  const originals = assets.filter(asset => asset.stem === 'original' && asset.status === 'approved' && asset.kind !== 'preview')
  const showOriginal = Boolean(settings.tracks.original?.asset_id) || !channels.slice(0, 3).some(stem => assets.some(asset => asset.stem === stem && asset.status === 'approved' && asset.kind !== 'preview'))
  const visibleChannels: LiveStem[] = showOriginal ? ['original', ...channels] : [...channels]
  return (
    <section className="panel mixer" aria-labelledby="mixer-title">
      <header className="panel-heading"><h2 id="mixer-title">Console DSP</h2><button className="primary" type="button" disabled={busy || !hasSource} title={hasSource ? 'Calcola il master per l’ascolto e l’export' : 'Seleziona e attiva almeno una sorgente approvata'} onClick={onRender}>Render mix</button></header>
      <div className={`mixer-banks${showOriginal ? ' has-original' : ''}`}>
        {visibleChannels.map(stem => {
          const approved = stem === 'original' ? originals : assets.filter(asset => asset.stem === stem && asset.status === 'approved' && asset.kind !== 'preview')
          const candidates = approved.map(asset => {
            const analysis = analyses.find(item => item.asset_id === asset.id)
            return analysis ? { ...asset, metadata: { ...asset.metadata, metrics: analysis.metrics } } : asset
          })
          const selected = candidates.find(item => item.id === settings.tracks[stem]?.asset_id)
          return <Strip key={stem} stem={stem} candidates={candidates} sampleCount={selected?.metadata.sample_count ?? sampleCount} sampleRate={selected?.metadata.sample_rate ?? sampleRate} renderedMetrics={master?.metadata.tracks?.[stem]} livePeak={live ? live.peaks[stem] ?? 0 : undefined} settings={settings.tracks[stem] ?? {}} editable={candidates.length > 0} onChange={track => onChange({ ...settings, tracks: { ...settings.tracks, [stem]: track } })} />
        })}
        <Strip stem="master" settings={settings.master} candidates={[]} sampleCount={sampleCount} sampleRate={sampleRate} renderedMetrics={loaded} livePeak={live ? live.peaks.master ?? 0 : undefined} editable={hasSource} onChange={config => onChange({ ...settings, master: config })} />
      </div>
      <div className="mixer-footer">
        <span className="hint">{showOriginal ? 'La console usa l’originale finché non ci sono stem approvati. ' : 'Il residuo può reintrodurre contaminazioni. '}EQ, compressore e limiter operano anche nel monitor live. Il render verifica il true peak del file.{live?.limiterDelayMs ? ` Lookahead live: ${formatNumber.format(live.limiterDelayMs)} ms.` : ''}</span>
        <div className="button-cluster">
          <button type="button" disabled={!liveAvailable || Boolean(live?.playing)} onClick={onLive}>Ascolta mix live</button>
          <button type="button" disabled={!master} onClick={() => { if (master) onListen(master) }}>Ascolta master</button>
        </div>
      </div>
      {master && <details className="master-metrics"><summary>Misure ultimo master{typeof size === 'number' ? ` · ${fileSize(size)}` : ''}</summary><MetricList metrics={masterMetrics} />
        {Array.isArray(master.metadata.warnings) && master.metadata.warnings.length > 0 && <ul className="export-warnings">{master.metadata.warnings.map((warning: string) => <li key={warning}>{warning}</li>)}</ul>}
      </details>}
    </section>
  )
}
