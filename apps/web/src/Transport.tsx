import { useEffect, useRef, useState } from 'react'
import { API, assetPath, formatTime, stemNames } from './api'
import type { AudioAsset, Metric, Region } from './api'

function readDb(metrics?: Record<string, Metric>) {
  if (!metrics) return {}
  const loudness = metrics.loudness
  const integrated = typeof loudness === 'object' && loudness && !Array.isArray(loudness)
    ? loudness.integrated_lufs ?? loudness.integrated
    : metrics.integrated_lufs
  return {
    lufs: typeof integrated === 'number' && Number.isFinite(integrated) ? integrated : undefined,
    rms: typeof metrics.rms_dbfs === 'number' && Number.isFinite(metrics.rms_dbfs) ? metrics.rms_dbfs : undefined,
  }
}

interface Source {
  asset: AudioAsset
  metrics?: Record<string, Metric>
}

function comparisonLevels(a?: Source, b?: Source) {
  const first = readDb(a?.metrics)
  const second = readDb(b?.metrics)
  if (first.lufs !== undefined && second.lufs !== undefined) return { a: first.lufs, b: second.lufs, label: 'LUFS' }
  if (first.rms !== undefined && second.rms !== undefined) return { a: first.rms, b: second.rms, label: 'RMS' }
}

function cleanError(error: unknown) {
  if (error instanceof DOMException && error.name === 'AbortError') return ''
  if (error instanceof DOMException && error.name === 'NotAllowedError') return 'Premi Riproduci per autorizzare l’ascolto.'
  return error instanceof Error ? error.message : 'Impossibile avviare l’ascolto.'
}

export function useTransport(projectId: string, region: Region | null) {
  const audio = useRef<HTMLAudioElement>(null)
  const activeSource = useRef<AudioAsset>(undefined)
  const pendingSeek = useRef(0)
  const [active, setActive] = useState<AudioAsset>()
  const [position, setPosition] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [loop, setLoop] = useState(false)
  const [volume, setVolume] = useState(() => {
    try {
      const value = localStorage.getItem('sonora.monitor.volume')
      const saved = value === null ? 0.8 : Number(value)
      return Number.isFinite(saved) ? Math.max(0, Math.min(1, saved)) : 0.8
    } catch {
      return 0.8
    }
  })
  const [error, setError] = useState('')

  function seek(sample: number) {
    const element = audio.current
    const asset = activeSource.current
    if (!element || !asset) return
    const start = asset.metadata.start_sample ?? 0
    const requested = Math.min(start + asset.metadata.sample_count, Math.max(start, sample))
    pendingSeek.current = requested
    if (element.readyState > 0) element.currentTime = (requested - start) / asset.metadata.sample_rate
    setPosition(requested)
  }

  function select(asset: AudioAsset, sample?: number, resume = playing) {
    if (!audio.current) return
    const previous = activeSource.current
    const currentSample = sample ?? (previous && audio.current.readyState > 0
      ? Math.round(audio.current.currentTime * previous.metadata.sample_rate) + (previous.metadata.start_sample ?? 0)
      : pendingSeek.current)
    if (activeSource.current?.id === asset.id) {
      seek(currentSample)
      if (resume) void audio.current.play().catch(error => setError(cleanError(error)))
      return
    }
    const start = asset.metadata.start_sample ?? 0
    activeSource.current = asset
    pendingSeek.current = Math.max(start, Math.min(start + asset.metadata.sample_count, currentSample))
    setPosition(pendingSeek.current)
    setActive(asset)
    setError('')
    audio.current.src = API + assetPath(projectId, asset.id) + '/media'
    if (resume) void audio.current.play().catch(error => setError(cleanError(error)))
  }

  function toggle() {
    const element = audio.current
    if (!element?.getAttribute('src')) return
    if (element.paused) {
      if (loop && region && (position < region.start_sample || position >= region.end_sample)) seek(region.start_sample)
      void element.play().catch(error => setError(cleanError(error)))
    } else {
      element.pause()
    }
  }

  function stop() {
    audio.current?.pause()
    seek(activeSource.current?.metadata.start_sample ?? 0)
  }

  function loadedMetadata() {
    const element = audio.current
    const asset = activeSource.current
    if (!element || !asset) return
    const seconds = (pendingSeek.current - (asset.metadata.start_sample ?? 0)) / asset.metadata.sample_rate
    if (seconds) element.currentTime = seconds
  }

  useEffect(() => {
    const element = audio.current
    if (!element) return
    let frame = 0
    let lastSample = -1
    let previousPaint = 0

    function readClock() {
      const asset = activeSource.current
      if (!element || !asset || element.readyState === 0) return
      const offset = asset.metadata.start_sample ?? 0
      const sample = Math.min(offset + asset.metadata.sample_count, Math.floor(element.currentTime * asset.metadata.sample_rate) + offset)
      if (loop && region && !element.paused && sample >= region.end_sample && region.start_sample >= offset && region.end_sample <= offset + asset.metadata.sample_count) {
        element.currentTime = (region.start_sample - offset) / asset.metadata.sample_rate
        lastSample = region.start_sample
        setPosition(lastSample)
      } else if (sample !== lastSample) {
        lastSample = sample
        setPosition(sample)
      }
    }

    function advance(now = performance.now()) {
      if (now - previousPaint >= 33 || (loop && region)) {
        previousPaint = now
        readClock()
      }
      if (element && !element.paused) frame = requestAnimationFrame(advance)
    }
    function start() {
      setPlaying(true)
      setWaiting(false)
      cancelAnimationFrame(frame)
      advance()
    }
    function pause() {
      setPlaying(false)
      setWaiting(false)
      cancelAnimationFrame(frame)
      readClock()
    }
    function ended() {
      const asset = activeSource.current
      if (element && asset && loop && region && region.start_sample >= (asset.metadata.start_sample ?? 0) &&
        region.end_sample <= (asset.metadata.start_sample ?? 0) + asset.metadata.sample_count) {
        element.currentTime = (region.start_sample - (asset.metadata.start_sample ?? 0)) / asset.metadata.sample_rate
        void element.play().catch(error => setError(cleanError(error)))
      } else {
        pause()
      }
    }
    function wait() {
      setWaiting(true)
    }
    function fail() {
      pause()
      setError('Audio non riproducibile. Verifica il formato di anteprima e la connessione al servizio locale.')
    }
    element.addEventListener('playing', start)
    element.addEventListener('pause', pause)
    element.addEventListener('ended', ended)
    element.addEventListener('seeked', readClock)
    element.addEventListener('timeupdate', readClock)
    element.addEventListener('waiting', wait)
    element.addEventListener('error', fail)
    if (!element.paused) advance()
    return () => {
      cancelAnimationFrame(frame)
      element.removeEventListener('playing', start)
      element.removeEventListener('pause', pause)
      element.removeEventListener('ended', ended)
      element.removeEventListener('seeked', readClock)
      element.removeEventListener('timeupdate', readClock)
      element.removeEventListener('waiting', wait)
      element.removeEventListener('error', fail)
    }
  }, [loop, region])

  return { audio, active, position, playing, waiting, loop, setLoop, volume, setVolume, error, select, seek, toggle, stop, loadedMetadata }
}

export type Transport = ReturnType<typeof useTransport>

export function TransportBar({ transport, sampleCount, sampleRate, region, baseline, candidate }: {
  transport: Transport
  sampleCount: number
  sampleRate: number
  region: Region | null
  baseline?: Source
  candidate?: Source
}) {
  const { active, audio, position, playing, waiting, loop, setLoop, volume, setVolume, error, select, seek, toggle, stop, loadedMetadata } = transport
  const [matched, setMatched] = useState(false)
  const levels = comparisonLevels(baseline, candidate)
  const matchMethod = levels?.label
  const currentIsBaseline = active?.id === baseline?.asset.id
  const currentIsCandidate = active?.id === candidate?.asset.id
  const attenuation = matched && levels && (currentIsBaseline || currentIsCandidate)
    ? 10 ** ((Math.min(levels.a, levels.b) - (currentIsBaseline ? levels.a : levels.b)) / 20)
    : 1

  useEffect(() => {
    if (audio.current) audio.current.volume = volume * attenuation
    try {
      localStorage.setItem('sonora.monitor.volume', String(volume))
    } catch {
      // The volume remains available for this session.
    }
  }, [volume, attenuation, audio])

  const offset = active?.metadata.start_sample ?? 0
  const canLoop = Boolean(active && region && region.start_sample >= offset && region.end_sample <= offset + active.metadata.sample_count)

  function compare(source?: Source) {
    if (source) select(source.asset)
  }

  return (
    <section className="transport panel" aria-label="Trasporto">
      <audio ref={audio} preload="metadata" onLoadedMetadata={loadedMetadata} />
      <div className="transport-main">
        <div className="button-cluster">
          <button className="play-button" type="button" disabled={!active} onClick={toggle} aria-label={playing ? 'Pausa' : 'Riproduci'} title="Spazio">{playing ? 'Ⅱ' : '▶'}</button>
          <button className="icon-button" type="button" disabled={!active} onClick={stop} aria-label="Stop">■</button>
          <button className="loop-button" type="button" disabled={!canLoop} aria-pressed={loop && canLoop} onClick={() => setLoop(!loop)} title={canLoop ? 'Ripeti la regione selezionata' : 'Seleziona una regione coperta dalla traccia in ascolto'}>Loop</button>
        </div>
        <output className="timecode" aria-label="Posizione riproduzione">{formatTime(position, sampleRate)}<small> / {formatTime(sampleCount, sampleRate)}</small></output>
        <div className="monitor-source">
          <span className={'status-dot' + (playing ? ' active' : '')} aria-hidden="true" />
          <span>{waiting ? 'Buffering…' : active ? stemNames[active.stem] : 'Monitor'}</span>
        </div>
        <div className="button-cluster ab-controls" aria-label="Ascolto A/B">
          <button type="button" disabled={!baseline} aria-pressed={Boolean(baseline && currentIsBaseline)} title={baseline?.asset.name ?? 'Versione sorgente non disponibile'} onClick={() => compare(baseline)}>A</button>
          <button type="button" disabled={!candidate} aria-pressed={Boolean(candidate && currentIsCandidate)} title={candidate?.asset.name ?? 'Versione restaurata non disponibile'} onClick={() => compare(candidate)}>B</button>
        </div>
        <label className="match-control" title={matchMethod ? `Abbinamento in ${matchMethod}, applicato al solo monitor` : 'Servono misure confrontabili sulle due versioni'}>
          <input type="checkbox" checked={Boolean(matchMethod && matched)} disabled={!matchMethod} onChange={event => setMatched(event.target.checked)} /> Abbina {matchMethod || 'livello'}
        </label>
        <label className="volume-control">
          <span>Monitor</span>
          <input type="range" min={0} max={1} step={0.01} value={volume} onChange={event => setVolume(Number(event.target.value))} />
          <output>{Math.round(volume * 100)}%</output>
        </label>
      </div>
      {sampleCount > 0 && <input className="transport-seek" type="range" aria-label="Posizione in campioni" min={0} max={sampleCount} step={1} value={position} disabled={!active} onChange={event => seek(Number(event.target.value))} />}
      {error && <p className="notice error" role="alert">{error}</p>}
    </section>
  )
}
