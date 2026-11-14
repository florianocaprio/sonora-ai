import { useEffect, useRef, useState } from 'react'
import * as studioApi from './api'
import type { AudioAsset, MixerSettings, Region } from './api'
import type { LiveMixConfig, LiveState, LiveStem, LiveTrack, MixEvent, MixMessage } from './liveMixTypes'
import liveProcessorURL from './liveMixProcessor?worker&url'

const liveStems: LiveStem[] = ['original', 'dialogue', 'music', 'effects', 'residual']
const emptyState: LiveState = { position: 0, playing: false, buffering: false, peaks: {}, underruns: 0 }
const littleEndian = new Uint8Array(new Uint32Array([1]).buffer)[0] === 1

function finite(value: number | undefined, min: number, max: number) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : 0
}

export function liveMixConfig(assets: AudioAsset[], settings: MixerSettings, rate: number, count: number): LiveMixConfig {
  const tracks = liveStems.flatMap<LiveTrack>(stem => {
    const track = settings.tracks[stem]
    const source = track && assets.find(asset => asset.id === track.asset_id && asset.status === 'approved')
    if (!source || source.kind === 'preview' || source.metadata.sample_rate !== rate ||
      source.metadata.sample_count !== count || (source.metadata.start_sample ?? 0) !== 0) return []
    const channels = source.metadata.channels
    if (channels !== 1 && channels !== 2) return []
    const automation = track.automation && {
      gain_db: track.automation.gain_db?.map(point => ({ ...point, value: finite(Number(point.value) + (track.trim_db ?? 0), -170, 48) })),
      pan: track.automation.pan,
      mute: track.automation.mute,
    }
    return [{
      stem, assetId: source.id, channels,
      gainDb: finite(track.gain_db, -90, 24) + finite(track.trim_db, -80, 24),
      pan: finite(track.pan, -1, 1), mute: track.mute ?? stem === 'residual', solo: Boolean(track.solo),
      invert: Boolean(track.polarity), automation,
    }]
  })
  return { rate, count, tracks, masterDb: finite(settings.master.gain_db, -90, 24) + finite(settings.master.trim_db, -80, 24) }
}

function streamKey(config: LiveMixConfig) {
  return JSON.stringify([config.rate, config.count, config.tracks.map(track => [track.stem, track.assetId, track.channels])])
}

function shortError(error: unknown) {
  return error instanceof Error ? error.message : 'Il monitor multitraccia non è disponibile.'
}

class LiveMixer {
  private context?: AudioContext
  private node?: AudioWorkletNode
  private setup?: Promise<void>
  private generation = 0
  private position = 0
  private playing = false
  private closed = false
  private started = false
  private lastState: LiveState = emptyState
  private underruns = 0
  private command = 0
  private settingsKey = ''
  private config: LiveMixConfig
  private key: string
  private loop: Region | null = null
  private volume = 0.8
  private requested = new Map<number, AbortController>()
  private delivered = new Set<number>()

  constructor(private projectID: string, config: LiveMixConfig, private update: (state: LiveState) => void) {
    this.config = config
    this.key = streamKey(config)
    this.settingsKey = JSON.stringify(config)
  }

  private post(message: MixMessage, transfer: Transferable[] = []) {
    this.node?.port.postMessage(message, transfer)
  }

  private publish(data: LiveState) {
    this.lastState = data
    this.update(data)
  }

  private async createNode(context: AudioContext) {
    await context.audioWorklet.addModule(liveProcessorURL)
    if (this.closed) return
    const node = new AudioWorkletNode(context, 'sonora-live-mix', {
      numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [2],
    })
    node.port.onmessage = ({ data }: MessageEvent<MixEvent>) => {
      if ('type' in data) return
      if (data.generation !== this.generation || this.closed || !this.started) return
      if (data.playing && !this.playing) return
      this.position = data.position
      this.underruns = data.underruns
      const contextPaused = this.playing && context.state !== 'running'
      if (!data.playing && data.position >= this.config.count) {
        this.playing = false
        this.clearBlocks()
        this.post({ type: 'retain', generation: this.generation, starts: [] })
      }
      this.publish({
        ...data, playing: this.playing, buffering: this.playing && (data.buffering || contextPaused),
      })
      if (this.playing) this.prefetch()
    }
    node.addEventListener('processorerror', () => this.fail(new Error('Errore nel processore del monitor audio. Riapri il progetto.')))
    node.connect(context.destination)
    this.node = node
    context.onstatechange = () => {
      if (this.playing && !this.closed && context.state !== 'running') {
        this.publish({ ...this.lastState, buffering: true })
      }
    }
  }

  private fail(error: unknown) {
    this.pause()
    this.publish({ ...emptyState, position: this.position, underruns: this.underruns, error: shortError(error) })
  }

  private clearBlocks() {
    for (const request of this.requested.values()) request.abort()
    this.requested.clear()
    this.delivered.clear()
  }

  private reset() {
    this.generation += 1
    this.clearBlocks()
    this.publish({ ...emptyState, position: this.position, underruns: this.underruns, playing: this.playing, buffering: this.playing, deviceRate: this.context?.sampleRate })
    this.post({
      type: 'reset', generation: this.generation, position: this.position,
      config: this.config, loop: this.loop, playing: this.playing,
    })
    if (this.playing) this.prefetch()
  }

  private async block(start: number, length: number) {
    const generation = this.generation
    const request = new AbortController()
    this.requested.set(start, request)
    try {
      const tracks = await Promise.all(this.config.tracks.map(async track => {
        const data = await studioApi.requestPCM(this.projectID, track.assetId, start, length, request.signal)
        if (data.byteLength !== length * track.channels * 4) throw new Error('Il blocco PCM non corrisponde alla timeline della traccia.')
        if (littleEndian) return data
        const decoded = new Float32Array(data.byteLength / 4)
        const wire = new DataView(data)
        for (let sample = 0; sample < decoded.length; sample += 1) decoded[sample] = wire.getFloat32(sample * 4, true)
        return decoded.buffer
      }))
      if (generation !== this.generation || request.signal.aborted) return
      this.delivered.add(start)
      this.post({ type: 'block', generation, start, length, tracks }, tracks)
    } catch (error) {
      if (generation === this.generation && !request.signal.aborted) this.fail(error)
      request.abort()
    } finally {
      if (this.requested.get(start) === request) this.requested.delete(start)
    }
  }

  private prefetch() {
    const { count, rate, tracks } = this.config
    if (!tracks.length || !this.node || this.closed) return
    const blockSize = Math.min(131072, rate)
    const start = this.loop?.start_sample ?? 0
    const end = this.loop?.end_sample ?? count
    const floor = (sample: number) => Math.floor(sample / blockSize) * blockSize
    const first = this.position >= end && this.loop ? start : this.position
    const desired: number[] = []
    for (let next = floor(first); next < end && desired.length < 3; next += blockSize) desired.push(next)
    const last = desired.at(-1)
    if (this.loop && last !== undefined && last + blockSize >= end && !desired.includes(floor(start))) {
      if (desired.length === 3) desired.pop()
      desired.push(floor(start))
    }
    let evict = false
    for (const [offset, request] of this.requested) {
      if (!desired.includes(offset)) {
        request.abort()
        this.requested.delete(offset)
      }
    }
    for (const offset of this.delivered) {
      if (!desired.includes(offset)) {
        this.delivered.delete(offset)
        evict = true
      }
    }
    if (evict) this.post({ type: 'retain', generation: this.generation, starts: desired })
    for (const offset of desired) {
      if (!this.delivered.has(offset) && !this.requested.has(offset)) {
        void this.block(offset, Math.min(blockSize, count - offset))
      }
    }
  }

  audioPosition() {
    return this.position
  }

  configure(config: LiveMixConfig) {
    const key = streamKey(config)
    const settingsKey = JSON.stringify(config)
    if (this.settingsKey === settingsKey) return
    this.settingsKey = settingsKey
    this.config = config
    if (this.key !== key) {
      this.key = key
      this.position = Math.min(this.position, config.count)
      if (!config.tracks.length) this.pause()
      if (this.started) this.reset()
    } else {
      this.post({ type: 'settings', config })
    }
  }

  setLoop(loop: Region | null) {
    const valid = loop && loop.start_sample >= 0 && loop.end_sample <= this.config.count && loop.start_sample < loop.end_sample
    this.loop = valid ? loop : null
    this.post({ type: 'loop', loop: this.loop })
    if (this.playing && this.loop && (this.position < this.loop.start_sample || this.position >= this.loop.end_sample)) {
      this.seek(this.loop.start_sample)
    } else if (this.playing) {
      this.prefetch()
    }
  }

  setVolume(value: number) {
    this.volume = value
    this.post({ type: 'volume', value })
  }

  async play(sample = this.position) {
    if (!this.config.tracks.length || this.closed) return
    this.playing = true
    const command = ++this.command
    const end = this.loop?.end_sample ?? this.config.count
    const start = this.loop?.start_sample ?? 0
    this.position = sample < start || sample >= end ? start : sample
    this.publish({ ...emptyState, position: this.position, underruns: this.underruns, playing: true, buffering: true })
    try {
      if (!this.context) {
        if (!globalThis.AudioContext || !globalThis.AudioWorkletNode) {
          throw new Error('AudioWorklet richiede un browser compatibile su localhost.')
        }
        this.context = new AudioContext({ latencyHint: 'playback' })
        this.setup = this.createNode(this.context)
      }
      // Call resume in the originating user gesture before awaiting module loading.
      await Promise.all([this.context.resume(), this.setup])
      if (!this.playing || this.closed || command !== this.command) return
      this.started = true
      this.setVolume(this.volume)
      this.reset()
    } catch (error) {
      if (!this.closed) this.fail(error)
    }
  }

  pause() {
    const wasActive = this.playing || this.started
    this.playing = false
    this.command += 1
    if (wasActive && this.started) this.reset()
    else if (wasActive) this.publish({ ...emptyState, position: this.position, underruns: this.underruns, deviceRate: this.context?.sampleRate })
  }

  seek(sample: number) {
    this.position = Math.max(0, Math.min(this.config.count, Math.round(sample)))
    if (this.playing && this.loop && (this.position < this.loop.start_sample || this.position >= this.loop.end_sample)) {
      this.position = this.loop.start_sample
    }
    if (this.started) this.reset()
    else this.publish({ ...emptyState, position: this.position, underruns: this.underruns, playing: this.playing, buffering: this.playing })
  }

  close() {
    this.closed = true
    this.clearBlocks()
    this.node?.disconnect()
    if (this.context && this.context.state !== 'closed') void this.context.close().catch(() => undefined)
  }
}

export function useLiveMix(projectID: string, config: LiveMixConfig, loop: Region | null, volume: number) {
  const engine = useRef<LiveMixer>(null)
  const [state, setState] = useState(emptyState)

  useEffect(() => {
    return () => {
      engine.current?.close()
      engine.current = null
    }
  }, [projectID])

  useEffect(() => { engine.current?.configure(config) }, [config])
  useEffect(() => { engine.current?.setLoop(loop) }, [loop])
  useEffect(() => { engine.current?.setVolume(volume) }, [volume])

  return {
    state,
    position: () => engine.current?.audioPosition() ?? 0,
    play: (sample?: number, nextLoop: Region | null = loop) => {
      if (!engine.current) {
        engine.current = new LiveMixer(projectID, config, setState)
        engine.current.setVolume(volume)
      }
      engine.current.setLoop(nextLoop)
      void engine.current.play(sample)
    },
    pause: () => engine.current?.pause(),
    seek: (sample: number) => engine.current?.seek(sample),
  }
}
