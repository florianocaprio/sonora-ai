import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, PointerEvent } from 'react'
import { assetPath, formatTime, request, stemNames } from './api'
import type { AudioAsset, Defect, Region } from './api'
import { Spectrogram } from './Spectrogram'

interface TimelineProps {
  projectId: string
  assets: AudioAsset[]
  active: AudioAsset | undefined
  monitorId: string | undefined
  sampleCount: number
  sampleRate: number
  position: number
  region: Region | null
  viewport: Region
  events: Defect[]
  selectedEventId: string | null
  onSelect: (asset: AudioAsset) => void
  onListen: (asset: AudioAsset) => void
  onSeek: (sample: number) => void
  onSelectRegion: (region: Region | null) => void
  onViewport: (region: Region) => void
  onDefect: (event: Defect) => void
}

function Waveform({ peaks }: { peaks: number[] }) {
  const canvas = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const node = canvas.current
    if (!node) return
    function draw() {
      if (!node) return
      const bounds = node.getBoundingClientRect()
      const ratio = window.devicePixelRatio || 1
      const width = Math.round(bounds.width * ratio)
      const height = Math.round(bounds.height * ratio)
      if (!width || !height) return
      node.width = width
      node.height = height
      const context = node.getContext('2d')
      if (!context) return
      const color = getComputedStyle(node).color
      context.fillStyle = color
      context.globalAlpha = 0.2
      context.fillRect(0, Math.floor(height / 2), width, ratio)
      context.globalAlpha = 0.85
      for (let index = 0; index < peaks.length; index++) {
        const start = Math.floor(index * width / peaks.length)
        const end = Math.floor((index + 1) * width / peaks.length)
        const amplitude = Math.min(1, Math.abs(peaks[index])) * height * 0.43
        context.fillRect(start, height / 2 - amplitude, Math.max(1, end - start - ratio), Math.max(1, amplitude * 2))
      }
    }
    const observer = new ResizeObserver(draw)
    observer.observe(node)
    draw()
    return () => observer.disconnect()
  }, [peaks])

  return <canvas ref={canvas} className="wave-canvas" aria-hidden="true" />
}

let longWaveformQueue = Promise.resolve()

function usePeaks(projectId: string, asset: AudioAsset, viewport: Region) {
  const offset = asset.metadata.start_sample ?? 0
  const rate = asset.metadata.sample_rate
  const end = Math.min(viewport.end_sample - offset, asset.metadata.sample_count)
  const start = Math.max(0, viewport.start_sample - offset)
  const key = `${projectId}/${asset.id}/${start}/${end}`
  const [loaded, setLoaded] = useState<{ key: string; peaks?: number[]; error?: string }>()
  useEffect(() => {
    if (start >= end) return
    const controller = new AbortController()
    const bins = Math.max(8, Math.min(512, end - start))
    const path = `${assetPath(projectId, asset.id)}/waveform?bins=${bins}&start_sample=${start}&end_sample=${end}`
    const load = async (signal?: AbortSignal) => {
      if (controller.signal.aborted) return
      try {
        const result = await request<{ peaks: number[] }>(path, { signal })
        if (!controller.signal.aborted) setLoaded({ key, peaks: result.peaks })
      } catch (error) {
        if (!controller.signal.aborted) setLoaded({ key, error: error instanceof Error ? error.message : String(error) })
      }
    }
    if (end - start > 60 * rate) {
      // Let an in-flight scan finish before starting another. The synchronous
      // API scan can outlive a cancelled client request and compete with PCM.
      longWaveformQueue = longWaveformQueue.then(() => load())
    } else void load(controller.signal)
    return () => controller.abort()
  }, [projectId, asset.id, start, end, key, rate])

  if (start >= end) return { peaks: [] }
  return loaded?.key === key ? loaded : { peaks: undefined, error: undefined }
}

interface Drag {
  pointer: number
  sample: number
  x: number
}

function Track({
  projectId, asset, selected, monitoring, viewport, onSelect, onListen, onSeek, onSelectRegion,
}: {
  projectId: string
  asset: AudioAsset
  selected: boolean
  monitoring: boolean
  viewport: Region
  onSelect: () => void
  onListen: () => void
  onSeek: (sample: number) => void
  onSelectRegion: (region: Region) => void
}) {
  const { peaks, error } = usePeaks(projectId, asset, viewport)
  const drag = useRef<Drag | null>(null)

  function sampleAt(event: PointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    const relative = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width))
    return Math.round(viewport.start_sample + relative * (viewport.end_sample - viewport.start_sample))
  }

  function startDrag(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = { pointer: event.pointerId, sample: sampleAt(event), x: event.clientX }
    onSelect()
  }

  function regionAt(event: PointerEvent<HTMLDivElement>) {
    const begin = drag.current
    if (!begin || event.pointerId !== begin.pointer || Math.abs(event.clientX - begin.x) < 4) return
    const current = sampleAt(event)
    const offset = asset.metadata.start_sample ?? 0
    return {
      start_sample: Math.max(offset, Math.min(begin.sample, current)),
      end_sample: Math.min(offset + asset.metadata.sample_count, Math.max(begin.sample, current)),
    }
  }

  function moveDrag(event: PointerEvent<HTMLDivElement>) {
    const region = regionAt(event)
    if (region && region.end_sample > region.start_sample) onSelectRegion(region)
  }

  function finishDrag(event: PointerEvent<HTMLDivElement>) {
    if (drag.current?.pointer !== event.pointerId) return
    const region = regionAt(event)
    drag.current = null
    if (region && region.end_sample > region.start_sample) {
      onSelectRegion(region)
      onSeek(region.start_sample)
    } else {
      onSeek(sampleAt(event))
    }
  }

  const offset = asset.metadata.start_sample ?? 0
  const visibleStart = Math.max(offset, viewport.start_sample)
  const visibleEnd = Math.min(offset + asset.metadata.sample_count, viewport.end_sample)
  const span = viewport.end_sample - viewport.start_sample
  const label = asset.stem === 'master' ? 'Remixed' : stemNames[asset.stem]

  return (
    <div className={`timeline-track track-${asset.stem}${selected ? ' selected' : ''}`}>
      <div className="track-label">
        <button type="button" className="track-title" aria-pressed={selected} onClick={onSelect} title={asset.stem === 'master' ? label : asset.name}>
          <i className="track-marker" aria-hidden="true" />
          <span>{label}</span>
          {asset.status === 'proposed' && <small>Bozza</small>}
        </button>
        <button type="button" className="track-audition" aria-pressed={monitoring} aria-label={asset.stem === 'master' ? 'Ascolta Remixed' : `Ascolta ${label.toLowerCase()}`} title={asset.stem === 'master' ? 'Ascolta Remixed' : 'Invia al monitor'} onClick={onListen}>◖))</button>
      </div>
      <div className="wave-area" onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={finishDrag} onPointerCancel={() => { drag.current = null }}>
        {peaks ? visibleStart < visibleEnd && <div className="wave-segment" style={{ left: `${(visibleStart - viewport.start_sample) * 100 / span}%`, width: `${(visibleEnd - visibleStart) * 100 / span}%` }}><Waveform peaks={peaks} /></div> : <span className="wave-message">{error || 'Calcolo forma d’onda…'}</span>}
      </div>
    </div>
  )
}

export function Timeline(props: TimelineProps) {
  const { active, assets, viewport, region, sampleRate, sampleCount, position } = props
  const [showSpectrum, setShowSpectrum] = useState(false)
  const span = viewport.end_sample - viewport.start_sample
  const percent = (sample: number) => span ? (sample - viewport.start_sample) * 100 / span : 0
  const regionStart = region ? Math.max(0, percent(region.start_sample)) : 0
  const regionEnd = region ? Math.min(100, percent(region.end_sample)) : 0
  const visibleEvents = props.events.filter(event => event.status !== 'dismissed' && event.end_sample > viewport.start_sample && event.start_sample < viewport.end_sample)
  const canZoomIn = span > Math.max(10, Math.round(sampleRate / 10))
  const canZoomOut = span < sampleCount

  function zoom(factor: number) {
    const nextSpan = Math.max(Math.round(sampleRate / 10), Math.min(sampleCount, Math.round(span * factor)))
    const anchor = position >= viewport.start_sample && position <= viewport.end_sample ? position : viewport.start_sample + span / 2
    const nextStart = Math.max(0, Math.min(sampleCount - nextSpan, Math.round(anchor - nextSpan / 2)))
    props.onViewport({ start_sample: nextStart, end_sample: nextStart + nextSpan })
  }

  function pan(delta: number) {
    const nextStart = Math.max(0, Math.min(sampleCount - span, viewport.start_sample + delta))
    props.onViewport({ start_sample: nextStart, end_sample: nextStart + span })
  }

  function setRegionBoundary(which: keyof Region, value: string) {
    if (value.trim() === '') return
    const sample = Number(value)
    if (!Number.isSafeInteger(sample)) return
    const next = {
      start_sample: region?.start_sample ?? 0,
      end_sample: region?.end_sample ?? sampleCount,
      [which]: sample,
    }
    if (next.start_sample >= 0 && next.start_sample < next.end_sample && next.end_sample <= sampleCount) {
      props.onSelectRegion(next)
    }
  }

  return (
    <section className="timeline panel" aria-labelledby="timeline-title">
      <header className="panel-heading">
        <h2 id="timeline-title">Timeline</h2>
        <div className="timeline-tools">
          <button type="button" disabled={!active} aria-pressed={showSpectrum} onClick={() => setShowSpectrum(!showSpectrum)}>Spettrogramma</button>
          <div className="button-cluster">
            <button type="button" className="icon-button" disabled={!canZoomOut || viewport.start_sample <= 0} onClick={() => pan(-Math.round(span / 2))} aria-label="Sposta visualizzazione a sinistra">‹</button>
            <button type="button" className="icon-button" disabled={!canZoomOut || viewport.end_sample >= sampleCount} onClick={() => pan(Math.round(span / 2))} aria-label="Sposta visualizzazione a destra">›</button>
          </div>
          <div className="button-cluster">
            <button type="button" className="icon-button" disabled={!canZoomOut} onClick={() => zoom(2)} aria-label="Riduci zoom">−</button>
            <button type="button" className="icon-button" disabled={!canZoomIn} onClick={() => zoom(0.5)} aria-label="Aumenta zoom">+</button>
          </div>
          <button type="button" disabled={!canZoomOut} onClick={() => props.onViewport({ start_sample: 0, end_sample: sampleCount })}>Tutto</button>
        </div>
      </header>
      <div className="timeline-grid">
        <div className="time-ruler">
          <div className="ruler-label">TRACCIA</div>
          <div className="ruler-ticks" aria-hidden="true">
            {Array.from({ length: 6 }, (_, index) => (
              <span key={index} style={{ left: `${20 * index}%` }}>{formatTime(viewport.start_sample + span * index / 5, sampleRate)}</span>
            ))}
          </div>
        </div>
        {assets.map(asset => (
          <Track
            key={asset.id}
            projectId={props.projectId}
            asset={asset}
            selected={active?.id === asset.id}
            monitoring={props.monitorId === asset.id}
            viewport={viewport}
            onSelect={() => props.onSelect(asset)}
            onListen={() => props.onListen(asset)}
            onSeek={props.onSeek}
            onSelectRegion={props.onSelectRegion}
          />
        ))}
        <div className="marker-lane">
          <div className="ruler-label">DIFETTI</div>
          <div className="markers">
            {visibleEvents.length === 0 && <span className="muted">{props.events.length ? 'Nessun difetto visibile' : 'Nessun difetto da mostrare'}</span>}
            {visibleEvents.map(event => (
              <button
                key={event.id}
                type="button"
                className="event-marker"
                aria-pressed={props.selectedEventId === event.id}
                aria-label={`${event.type}, ${formatTime(event.start_sample, sampleRate)}, gravità ${event.severity}`}
                title={`${event.type} · ${event.severity}`}
                style={{ left: `${Math.max(0, percent(event.start_sample))}%`, width: `${Math.max(0.15, Math.min(100, percent(event.end_sample)) - Math.max(0, percent(event.start_sample)))}%` }}
                onClick={() => props.onDefect(event)}
              />
            ))}
          </div>
        </div>
        <div className="timeline-overlay" aria-hidden="true">
          {regionStart < regionEnd && <div className="range-overlay" style={{ left: `${regionStart}%`, width: `${regionEnd - regionStart}%` }} />}
          {percent(position) >= 0 && percent(position) <= 100 && <div className="playhead" style={{ '--playhead': `${percent(position)}%` } as CSSProperties} />}
        </div>
      </div>
      {showSpectrum && active && <Spectrogram projectId={props.projectId} asset={active} viewport={viewport} />}
      <div className="region-controls">
        <span>Regione <small>(campioni)</small></span>
        <label>Inizio <input type="number" min={0} max={Math.max(0, (region?.end_sample ?? sampleCount) - 1)} step={1} key={`start-${region?.start_sample}`} defaultValue={region?.start_sample ?? ''} placeholder="0" onBlur={event => setRegionBoundary('start_sample', event.target.value)} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur() }} /></label>
        <label>Fine <input type="number" min={(region?.start_sample ?? 0) + 1} max={sampleCount} step={1} key={`end-${region?.end_sample}`} defaultValue={region?.end_sample ?? ''} placeholder={String(sampleCount)} onBlur={event => setRegionBoundary('end_sample', event.target.value)} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur() }} /></label>
        <button type="button" disabled={!region} onClick={() => props.onSelectRegion(null)}>Deseleziona</button>
      </div>
    </section>
  )
}
