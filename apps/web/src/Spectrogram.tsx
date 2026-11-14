import { useEffect, useRef, useState } from 'react'
import { assetPath, formatNumber, request } from './api'
import type { AudioAsset, Region } from './api'

interface Tile {
  columns: number[][]
  sample_rate: number
  frequency_bin_hz: number
  minimum_dbfs: number
}

const stops = [
  [7, 12, 23], [41, 32, 82], [99, 58, 121], [184, 80, 111], [240, 151, 100], [248, 237, 177],
] as const

function palette(intensity: number) {
  const segment = Math.max(0, Math.min(stops.length - 1, intensity * (stops.length - 1)))
  const base = Math.floor(segment)
  const blend = segment - base
  const next = stops[Math.min(base + 1, stops.length - 1)]
  return stops[base].map((start, index) => Math.round(start + (next[index] - start) * blend))
}

const colors = Array.from({ length: 256 }, (_, index) => palette(index / 255))

export function Spectrogram({ projectId, asset, viewport }: { projectId: string; asset: AudioAsset; viewport: Region }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [loaded, setLoaded] = useState<{ key: string; data?: Tile; error?: string }>()
  const offset = asset.metadata.start_sample ?? 0
  const start = Math.max(0, viewport.start_sample - offset)
  const end = Math.min(asset.metadata.sample_count, viewport.end_sample - offset)
  const key = `${projectId}/${asset.id}/${start}/${end}`
  const current = loaded?.key === key ? loaded : undefined
  const tile = current?.data

  useEffect(() => {
    if (end <= start) return
    const controller = new AbortController()
    request<Tile>(`${assetPath(projectId, asset.id)}/spectrogram?start_sample=${start}&end_sample=${end}&columns=256&fft_size=512`, { signal: controller.signal })
      .then(data => setLoaded({ key, data }))
      .catch((error: Error) => {
        if (!controller.signal.aborted) setLoaded({ key, error: error.message })
      })
    return () => controller.abort()
  }, [projectId, asset.id, start, end, key])

  useEffect(() => {
    const context = canvas.current?.getContext('2d')
    const width = tile?.columns.length ?? 0
    const height = tile?.columns[0]?.length ?? 0
    if (!context || !tile || !width || !height) return
    context.canvas.width = width
    context.canvas.height = height
    const pixels = context.createImageData(width, height)
    const floor = tile.minimum_dbfs
    for (let x = 0; x < width; x++) {
      for (let band = 0; band < height; band++) {
        const base = ((height - band - 1) * width + x) * 4
        const lookup = Math.max(0, Math.min(255, Math.round((tile.columns[x][band] - floor) / -floor * 255)))
        const [r, g, b] = colors[lookup]
        pixels.data.set([r, g, b, 255], base)
      }
    }
    context.putImageData(pixels, 0, 0)
  }, [tile])

  if (end <= start) return <p className="hint copy-space">Nessun campione della traccia nell’intervallo visibile.</p>
  return (
    <figure className="spectrogram" aria-label="Spettrogramma della traccia selezionata">
      {tile ? <>
        <div className="frequency-axis" aria-hidden="true">
          <span>{formatNumber.format(tile.sample_rate / 2000)} kHz</span>
          <span>{formatNumber.format(tile.sample_rate / 4000)} kHz</span>
          <span>0 Hz</span>
        </div>
        <div className="spectrum-plot"><canvas ref={canvas} role="img" aria-label={`Magnitudine da ${tile.minimum_dbfs} a 0 dBFS, asse verticale da 0 a ${tile.sample_rate / 2} Hz`} /></div>
        <figcaption><span>{tile.minimum_dbfs} dBFS</span><span className="spectrum-scale" /><span>0 dBFS</span><span>Risoluzione {formatNumber.format(tile.frequency_bin_hz)} Hz</span></figcaption>
      </> : <p className="hint copy-space">{current?.error ?? 'Calcolo spettrogramma…'}</p>}
    </figure>
  )
}
