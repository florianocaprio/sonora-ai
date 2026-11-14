import type { Compressor, Equalizer } from './api'
import type { LiveChannelSettings, LiveMasterSettings } from './liveMixTypes'

export function bounded(value: number | undefined, min: number, max: number, fallback = 0) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback
}

export function dbGain(db: number) {
  return 10 ** (db / 20)
}

function eqSettings(value: Equalizer[] | undefined, rate: number): Equalizer[] {
  // The renderer also accepts a single band in older saved mixer settings.
  const bands = Array.isArray(value) ? value : value ? [value as unknown as Equalizer] : []
  return bands.slice(0, 8).filter(band => band && typeof band === 'object').map(band => ({
    frequency_hz: bounded(band.frequency_hz, 10, rate * 0.49, Math.min(1000, rate * 0.49)),
    gain_db: bounded(band.gain_db, -24, 24),
    q: bounded(band.q, 0.1, 25, 1),
  })).filter(band => band.gain_db !== 0)
}

function compressorSettings(settings?: Compressor): Compressor | undefined {
  if (!settings || typeof settings !== 'object') return undefined
  return {
    threshold_db: bounded(settings.threshold_db, -80, 0, -18),
    ratio: bounded(settings.ratio, 1, 20, 3),
    knee_db: bounded(settings.knee_db, 0, 40, 6),
    attack_ms: bounded(settings.attack_ms, 0.1, 1000, 10),
    release_ms: bounded(settings.release_ms, 0.1, 5000, 100),
    makeup_db: bounded(settings.makeup_db, -24, 24),
  }
}

export function liveChannelSettings(settings: LiveChannelSettings, rate: number): LiveChannelSettings {
  return {
    trim_db: bounded(settings.trim_db, -80, 24),
    eq: eqSettings(settings.eq, rate),
    compressor: compressorSettings(settings.compressor),
    bypass: settings.bypass === true,
  }
}

export function liveLimiterTiming(settings?: LiveMasterSettings) {
  return settings?.limiter?.enabled === true && settings.bypass !== true
    ? bounded(settings.limiter.lookahead_ms, 1, 20, 5)
    : 0
}

class Biquad {
  private readonly b0: number
  private readonly b1: number
  private readonly b2: number
  private readonly a2: number
  private left1 = 0
  private left2 = 0
  private right1 = 0
  private right2 = 0
  left = 0
  right = 0

  constructor(band: Equalizer, rate: number) {
    const amplitude = 10 ** (band.gain_db / 40)
    const omega = 2 * Math.PI * band.frequency_hz / rate
    const alpha = Math.sin(omega) / (2 * band.q)
    const a0 = 1 + alpha / amplitude
    this.b0 = (1 + alpha * amplitude) / a0
    this.b1 = -2 * Math.cos(omega) / a0
    this.b2 = (1 - alpha * amplitude) / a0
    this.a2 = (1 - alpha / amplitude) / a0
  }

  process(left: number, right: number) {
    this.left = this.b0 * left + this.left1
    this.right = this.b0 * right + this.right1
    this.left1 = this.b1 * (left - this.left) + this.left2
    this.right1 = this.b1 * (right - this.right) + this.right2
    this.left2 = this.b2 * left - this.a2 * this.left
    this.right2 = this.b2 * right - this.a2 * this.right
  }
}

class FilterBank {
  private readonly filters: Biquad[]
  left = 0
  right = 0

  constructor(bands: Equalizer[], rate: number) {
    this.filters = bands.map(band => new Biquad(band, rate))
  }

  process(left: number, right: number) {
    for (const filter of this.filters) {
      filter.process(left, right)
      left = filter.left
      right = filter.right
    }
    this.left = left
    this.right = right
  }
}

class CompressorEnvelope {
  private settings?: Compressor
  private attack = 0
  private release = 0
  private reduction = 0
  private makeup = 0
  private readonly makeupSmoothing: number

  constructor(private readonly rate: number) {
    this.makeupSmoothing = 1 - Math.exp(-1000 / (8 * rate))
  }

  configure(settings?: Compressor) {
    if (!this.settings && settings) this.makeup = settings.makeup_db
    this.settings = settings
    if (!settings) {
      this.reduction = 0
      return
    }
    this.attack = Math.exp(-1000 / (settings.attack_ms * this.rate))
    this.release = Math.exp(-1000 / (settings.release_ms * this.rate))
  }

  gain(left: number, right: number) {
    const settings = this.settings
    if (!settings) return 1
    const peak = Math.max(Math.abs(left), Math.abs(right), 1e-12)
    const above = 20 * Math.log10(peak) - settings.threshold_db
    const halfKnee = settings.knee_db / 2
    const factor = 1 / settings.ratio - 1
    const target = halfKnee > 0 && Math.abs(above) < halfKnee
      ? factor * (above + halfKnee) ** 2 / (4 * halfKnee)
      : factor * Math.max(above, 0)
    const factorTime = target < this.reduction ? this.attack : this.release
    this.reduction = target + (this.reduction - target) * factorTime
    this.makeup += (settings.makeup_db - this.makeup) * this.makeupSmoothing
    return dbGain(this.reduction + this.makeup)
  }
}

export class LiveChannelDSP {
  private filters: FilterBank
  private previousFilters?: FilterBank
  private filterKey = ''
  private crossfade = 1
  private readonly fadeStep: number
  private compressor: CompressorEnvelope
  private settings?: Compressor
  private previousCompressor?: CompressorEnvelope
  private compressorKey?: string
  private compressorFade = 1
  private trim = 1
  private targetTrim = 1
  private wet = 1
  private targetWet = 1
  left = 0
  right = 0

  constructor(private readonly rate: number, settings?: LiveChannelSettings) {
    this.filters = new FilterBank([], rate)
    this.compressor = new CompressorEnvelope(rate)
    this.fadeStep = 1 / Math.max(1, Math.round(rate * 0.008))
    this.configure(settings, true)
  }

  configure(input: LiveChannelSettings | undefined, reset = false) {
    const settings = liveChannelSettings(input ?? {}, this.rate)
    this.targetTrim = dbGain(settings.trim_db ?? 0)
    this.targetWet = settings.bypass ? 0 : 1
    const eq = settings.eq ?? []
    const key = JSON.stringify(eq)
    if (key !== this.filterKey) {
      this.filterKey = key
      this.previousFilters = reset ? undefined : this.filters
      this.filters = new FilterBank(eq, this.rate)
      this.crossfade = reset ? 1 : 0
    }
    const compressorKey = JSON.stringify(settings.compressor)
    if (compressorKey !== this.compressorKey) {
      if (!reset && Boolean(settings.compressor) !== Boolean(this.settings)) {
        this.previousCompressor = this.compressor
        this.compressor = new CompressorEnvelope(this.rate)
        this.compressorFade = 0
      }
      this.compressorKey = compressorKey
      this.settings = settings.compressor
      this.compressor.configure(settings.compressor)
    }
    if (reset) {
      this.trim = this.targetTrim
      this.wet = this.targetWet
    }
  }

  process(left: number, right: number) {
    this.trim += (this.targetTrim - this.trim) * this.fadeStep
    this.wet += Math.max(-this.fadeStep, Math.min(this.fadeStep, this.targetWet - this.wet))
    const dryLeft = left * this.trim
    const dryRight = right * this.trim
    this.filters.process(dryLeft, dryRight)
    left = this.filters.left
    right = this.filters.right
    if (this.previousFilters) {
      this.previousFilters.process(dryLeft, dryRight)
      this.crossfade = Math.min(1, this.crossfade + this.fadeStep)
      left = this.previousFilters.left + (left - this.previousFilters.left) * this.crossfade
      right = this.previousFilters.right + (right - this.previousFilters.right) * this.crossfade
      if (this.crossfade === 1) this.previousFilters = undefined
    }
    let gain = this.compressor.gain(left, right)
    if (this.previousCompressor) {
      const previous = this.previousCompressor.gain(left, right)
      this.compressorFade = Math.min(1, this.compressorFade + this.fadeStep)
      gain = previous + (gain - previous) * this.compressorFade
      if (this.compressorFade === 1) this.previousCompressor = undefined
    }
    this.left = dryLeft + (left * gain - dryLeft) * this.wet
    this.right = dryRight + (right * gain - dryRight) * this.wet
  }
}

const PHASES = 4
const RADIUS = 12
const TAPS = 2 * RADIUS + 1
const MARGIN_DB = 0.5

function detectorCoefficients() {
  const coefficients = new Float64Array((PHASES - 1) * TAPS)
  for (let phase = 1; phase < PHASES; phase += 1) {
    const first = (phase - 1) * TAPS
    let sum = 0
    for (let tap = 0; tap < TAPS; tap += 1) {
      const distance = tap - RADIUS - phase / PHASES
      const angle = Math.PI * distance / (RADIUS + 1)
      const window = 0.42 + 0.5 * Math.cos(angle) + 0.08 * Math.cos(2 * angle)
      const coefficient = Math.sin(Math.PI * distance) / (Math.PI * distance) * window
      sum += coefficient
      coefficients[first + tap] = coefficient
    }
    for (let tap = 0; tap < TAPS; tap += 1) coefficients[first + tap] /= sum
  }
  return coefficients
}

const detector = detectorCoefficients()

export class LivePeakLimiter {
  readonly delay: number
  private readonly lookahead: number
  private readonly samplesLeft: Float64Array
  private readonly samplesRight: Float64Array
  private readonly positions: Float64Array
  private readonly peakValues: Float64Array
  private readonly peakIndices: Float64Array
  private readonly gainTargets: Float64Array
  private targetSum = 0
  private incoming = 0
  private head = 0
  private tail = 0
  private gain = 1
  private limit = 1
  private release = 0
  left = 0
  right = 0
  position = 0

  constructor(private readonly rate: number, lookaheadMs: number, settings?: LiveMasterSettings) {
    this.lookahead = Math.max(1, Math.round(lookaheadMs * rate / 1000))
    this.delay = this.lookahead + RADIUS
    const capacity = Math.max(this.delay + 1, TAPS)
    this.samplesLeft = new Float64Array(capacity)
    this.samplesRight = new Float64Array(capacity)
    this.positions = new Float64Array(capacity)
    this.peakIndices = new Float64Array(this.lookahead + 2)
    this.peakValues = new Float64Array(this.peakIndices.length)
    this.gainTargets = new Float64Array(this.lookahead + 1)
    this.configure(settings)
  }

  configure(settings?: LiveMasterSettings) {
    this.limit = dbGain(bounded(settings?.ceiling_dbtp, -30, 0, -1) - MARGIN_DB)
    const releaseMs = bounded(settings?.limiter?.release_ms, 10, 1000, 80)
    this.release = Math.exp(-1000 / (releaseMs * this.rate))
  }

  private detect(index: number, latest: number) {
    const capacity = this.samplesLeft.length
    const head = index % capacity
    let peak = Math.max(Math.abs(this.samplesLeft[head]), Math.abs(this.samplesRight[head]))
    const first = Math.max(index - RADIUS, 0)
    let slot = first % capacity
    for (let phase = 0; phase < PHASES - 1; phase += 1) {
      let left = 0
      let right = 0
      let tap = slot
      let coefficient = phase * TAPS + first - index + RADIUS
      for (let at = first; at <= latest; at += 1) {
        const weight = detector[coefficient++]
        left += this.samplesLeft[tap] * weight
        right += this.samplesRight[tap] * weight
        if (++tap === capacity) tap = 0
      }
      peak = Math.max(peak, Math.abs(left), Math.abs(right))
    }
    return peak
  }

  process(left: number, right: number, position: number) {
    const index = this.incoming++
    const capacity = this.samplesLeft.length
    const write = index % capacity
    this.samplesLeft[write] = left
    this.samplesRight[write] = right
    this.positions[write] = position
    if (index < RADIUS) return false

    const measured = index - RADIUS
    const target = measured - this.lookahead
    const peak = this.detect(measured, index)
    const queueLength = this.peakIndices.length
    while (this.head < this.tail && this.peakIndices[this.head % queueLength] < target) this.head += 1
    while (this.head < this.tail && this.peakValues[(this.tail - 1) % queueLength] <= peak) this.tail -= 1
    this.peakIndices[this.tail % queueLength] = measured
    this.peakValues[this.tail++ % queueLength] = peak
    if (target < 0) return false

    const required = this.limit / Math.max(this.limit, this.peakValues[this.head % queueLength])
    const attackWindow = this.gainTargets.length
    if (target === 0) {
      this.gainTargets.fill(required)
      this.targetSum = required * attackWindow
    } else {
      const slot = target % attackWindow
      this.targetSum += required - this.gainTargets[slot]
      this.gainTargets[slot] = required
    }
    // The trailing mean smooths attack inside the lookahead. Each target in
    // the mean covers this frame, so the detector peak still bounds its gain.
    const attack = Math.min(1, Math.max(0, this.targetSum / attackWindow))
    const read = target % capacity
    const samplePeak = Math.max(Math.abs(this.samplesLeft[read]), Math.abs(this.samplesRight[read]))
    const sampleGuard = this.limit / Math.max(this.limit, samplePeak)
    this.gain = Math.min(sampleGuard, attack, 1 - (1 - this.gain) * this.release)
    this.left = this.samplesLeft[read] * this.gain
    this.right = this.samplesRight[read] * this.gain
    this.position = this.positions[read]
    return true
  }
}
