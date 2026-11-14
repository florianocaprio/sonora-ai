import type { AutomationPoint, Region } from './api'
import type { LiveMixConfig, LiveState, MixMessage, MixStatus } from './liveMixTypes'
import { dbGain, LiveChannelDSP, LivePeakLimiter, liveLimiterTiming } from './liveMixDSP'

// These globals exist in AudioWorkletGlobalScope rather than the window DOM types.
declare const sampleRate: number
declare const AudioWorkletProcessor: { new(): { port: MessagePort } }
declare function registerProcessor(name: string, processor: typeof AudioWorkletProcessor): void

interface Block {
  start: number
  end: number
  tracks: Float32Array[]
}

function automationValue(points: AutomationPoint[] | undefined, position: number, fallback: number, fade = 0) {
  if (!points?.length) return fallback
  let left = 0
  let right = points.length - 1
  while (right - left > 1) {
    const middle = (left + right) >>> 1
    if (points[middle].sample <= position) left = middle
    else right = middle
  }
  const first = points[left]
  const last = points[right]
  if (fade) {
    const current = last.sample <= position ? right : left
    const point = points[current]
    if (!current) return Number(point.value)
    const previous = Number(points[current - 1].value)
    const end = Math.min(point.sample + fade, points[current + 1]?.sample ?? Infinity)
    const fraction = Math.max(0, Math.min(1, (position - point.sample) / (end - point.sample)))
    return previous + (Number(point.value) - previous) * fraction
  }
  if (position <= first.sample) return Number(first.value)
  if (position >= last.sample) return Number(last.value)
  return Number(first.value) + (Number(last.value) - Number(first.value)) *
    ((position - first.sample) / (last.sample - first.sample))
}

class LiveMixProcessor extends AudioWorkletProcessor {
  private generation = 0
  private cursor = 0
  private audibleCursor = 0
  private draining = 0
  private phase = 0
  private config: LiveMixConfig = { rate: sampleRate, count: 0, tracks: [], masterDb: 0 }
  private loop: Region | null = null
  private blocks: Block[] = []
  private playing = false
  private buffering = false
  private hasRendered = false
  private underruns = 0
  private reportIn = 0
  private volume = 0.8
  private monitorGain = 0.8
  private masterGain = 1
  private controls: { manualGain: number; gain: number; pan: number; targetGate: number; dsp: LiveChannelDSP }[] = []
  private master = new LiveChannelDSP(sampleRate)
  private limiter?: LivePeakLimiter
  private limiterTiming = 0
  private peaks: number[] = []
  private masterPeak = 0
  private readonly smoothing = 1 - Math.exp(-1 / (0.003 * sampleRate))

  constructor() {
    super()
    this.port.onmessage = (event: MessageEvent<MixMessage>) => this.handle(event.data)
  }

  private configure(config: LiveMixConfig, reset: boolean) {
    const solo = config.tracks.some(track => track.solo)
    this.controls = config.tracks.map((track, index) => {
      const gate = Number(!track.mute && (!solo || track.solo))
      const manualGain = dbGain(track.gainDb) * (track.invert ? -1 : 1)
      const existing = reset ? undefined : this.controls[index]?.dsp
      const dsp = existing ?? new LiveChannelDSP(sampleRate, track.dsp)
      existing?.configure(track.dsp)
      return {
        dsp, manualGain,
        gain: reset ? gate * manualGain : this.controls[index]?.gain ?? gate * manualGain,
        pan: reset ? track.pan : this.controls[index]?.pan ?? track.pan,
        targetGate: gate,
      }
    })
    const timing = liveLimiterTiming(config.masterDsp)
    if (reset || timing !== this.limiterTiming) {
      this.limiter = timing ? new LivePeakLimiter(sampleRate, timing, config.masterDsp) : undefined
      this.limiterTiming = timing
    } else this.limiter?.configure(config.masterDsp)
    if (reset) {
      this.master = new LiveChannelDSP(sampleRate, config.masterDsp)
      this.peaks = config.tracks.map(() => 0)
      this.masterPeak = 0
      this.masterGain = dbGain(config.masterDb)
      this.monitorGain = this.volume
    } else this.master.configure(config.masterDsp)
    this.config = config
  }

  private handle(message: MixMessage) {
    if (message.type === 'reset') {
      this.generation = message.generation
      this.cursor = message.position
      this.audibleCursor = message.position
      this.draining = 0
      this.phase = 0
      this.loop = message.loop
      this.playing = message.playing
      this.buffering = false
      this.hasRendered = false
      this.blocks = []
      this.reportIn = 0
      this.configure(message.config, true)
      return
    }
    if ('generation' in message && message.generation !== this.generation) return
    switch (message.type) {
      case 'block':
        if (!this.blocks.some(block => block.start === message.start)) {
          this.blocks.push({
            start: message.start,
            end: message.start + message.length,
            tracks: message.tracks.map(buffer => new Float32Array(buffer)),
          })
          this.port.postMessage({ type: 'block-ready', generation: this.generation, start: message.start })
        }
        break
      case 'retain':
        this.blocks = this.blocks.filter(block => message.starts.includes(block.start))
        break
      case 'settings':
        this.configure(message.config, false)
        break
      case 'loop':
        this.loop = message.loop
        break
      case 'volume':
        this.volume = message.value
        break
    }
  }

  private blockAt(position: number) {
    for (const block of this.blocks) {
      if (position >= block.start && position < block.end) return block
    }
  }

  private needBuffer() {
    // Drop both channels, and stop the shared clock, whenever any stem is unavailable.
    if (!this.buffering) {
      this.buffering = true
      if (this.hasRendered) this.underruns += 1
      this.reportIn = 0
    }
  }

  private report() {
    const peaks: LiveState['peaks'] = { master: this.masterPeak }
    this.config.tracks.forEach((track, index) => { peaks[track.stem] = this.peaks[index] })
    const message: MixStatus = {
      generation: this.generation, position: this.audibleCursor, readPosition: this.cursor, playing: this.playing,
      buffering: this.buffering, peaks, underruns: this.underruns, deviceRate: sampleRate,
      limiterDelayMs: (this.limiter?.delay ?? 0) * 1000 / sampleRate,
    }
    this.port.postMessage(message)
    this.masterPeak = 0
    this.peaks.fill(0)
  }

  private writeFrame(left: Float32Array, right: Float32Array, frame: number,
                     l: number, r: number, position: number) {
    if (this.limiter) {
      if (!this.limiter.process(l, r, position)) return
      l = this.limiter.left
      r = this.limiter.right
      position = this.limiter.position
    }
    // The meter measures the limited mix, before the monitor volume.
    this.masterPeak = Math.max(this.masterPeak, Math.abs(l), Math.abs(r))
    this.monitorGain += (this.volume - this.monitorGain) * this.smoothing
    left[frame] = l * this.monitorGain
    right[frame] = r * this.monitorGain
    this.audibleCursor = position
  }

  process(_inputs: Float32Array[][], outputs: Float32Array[][]) {
    const output = outputs[0]
    if (!output?.length) return true
    const [left, right] = output
    const { rate, count, tracks, masterDb } = this.config
    const targetMaster = dbGain(masterDb)
    const end = this.loop?.end_sample ?? count
    const start = this.loop?.start_sample ?? 0
    const length = end - start
    for (let frame = 0; this.playing && frame < left.length; frame += 1) {
      if (this.cursor >= end) {
        if (this.loop && length > 0) this.cursor = start + (this.cursor - end) % length
        else {
          this.cursor = count
          if (this.draining < (this.limiter?.delay ?? 0)) {
            this.writeFrame(left, right, frame, 0, 0, count)
            this.draining += 1
            continue
          }
          this.audibleCursor = count
          this.playing = false
          this.reportIn = 0
          break
        }
      }
      const position = this.cursor
      const fraction = this.phase / sampleRate
      const following = position + 1 < end ? position + 1 : this.loop ? start : position
      const block = this.blockAt(position)
      const next = fraction === 0 || following === position ? block : this.blockAt(following)
      if (!block || !next) {
        this.needBuffer()
        break
      }
      this.hasRendered = true
      if (this.buffering) {
        this.buffering = false
        this.reportIn = 0
      }
      const offset = position - block.start
      const nextOffset = fraction === 0 ? offset : following - next.start

      let mixedLeft = 0
      let mixedRight = 0
      for (let index = 0; index < tracks.length; index += 1) {
        const track = tracks[index]
        const control = this.controls[index]
        const lane = track.automation
        const gate = control.targetGate * (1 - automationValue(lane?.mute, position, 0, Math.round(rate * 0.005)))
        const gain = lane?.gain_db?.length
          ? dbGain(automationValue(lane.gain_db, position, track.gainDb)) * (track.invert ? -1 : 1)
          : control.manualGain
        control.gain += (gate * gain - control.gain) * this.smoothing
        const pan = automationValue(lane?.pan, position, track.pan)
        control.pan += (pan - control.pan) * this.smoothing
        const a = block.tracks[index]
        const b = next.tracks[index]
        let l = a[offset * track.channels]
        l += (b[nextOffset * track.channels] - l) * fraction
        let r = l
        if (track.channels === 2) {
          r = a[offset * 2 + 1]
          r += (b[nextOffset * 2 + 1] - r) * fraction
        }
        control.dsp.process(l, r)
        l = control.dsp.left * control.gain
        r = control.dsp.right * control.gain
        if (track.channels === 1) {
          const angle = (control.pan + 1) * Math.PI / 4
          r *= Math.sin(angle)
          l *= Math.cos(angle)
        } else {
          l *= 1 - Math.max(0, control.pan)
          r *= 1 + Math.min(0, control.pan)
        }
        this.peaks[index] = Math.max(this.peaks[index], Math.abs(l), Math.abs(r))
        mixedLeft += l
        mixedRight += r
      }
      this.masterGain += (targetMaster - this.masterGain) * this.smoothing
      this.master.process(mixedLeft, mixedRight)
      this.phase += rate
      this.cursor += Math.floor(this.phase / sampleRate)
      this.phase %= sampleRate
      const outputPosition = this.loop && this.cursor >= end ? start + (this.cursor - end) % length : Math.min(count, this.cursor)
      this.writeFrame(left, right, frame, this.master.left * this.masterGain, this.master.right * this.masterGain, outputPosition)
    }
    this.reportIn -= left.length
    if (this.generation > 0 && this.reportIn <= 0) {
      this.report()
      this.reportIn = sampleRate / 20
    }
    return true
  }
}

registerProcessor('sonora-live-mix', LiveMixProcessor)
