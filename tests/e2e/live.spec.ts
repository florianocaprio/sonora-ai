import { expect, test, type Page } from '@playwright/test'

function stereoFixture() {
  const rate = 48_000
  const frames = rate * 10
  const audio = Buffer.alloc(44 + frames * 4)
  audio.write('RIFF', 0)
  audio.writeUInt32LE(audio.length - 8, 4)
  audio.write('WAVEfmt ', 8)
  audio.writeUInt32LE(16, 16)
  audio.writeUInt16LE(1, 20)
  audio.writeUInt16LE(2, 22)
  audio.writeUInt32LE(rate, 24)
  audio.writeUInt32LE(rate * 4, 28)
  audio.writeUInt16LE(4, 32)
  audio.writeUInt16LE(16, 34)
  audio.write('data', 36)
  audio.writeUInt32LE(frames * 4, 40)
  for (let sample = 0; sample < frames; sample += 1) {
    const time = sample / rate
    const envelope = 0.7 + 0.3 * Math.cos(2 * Math.PI * time)
    audio.writeInt16LE(Math.round(4000 * Math.sin(440 * 2 * Math.PI * time) * envelope), 44 + sample * 4)
    audio.writeInt16LE(Math.round(2500 * Math.sin(613 * 2 * Math.PI * time) * envelope), 46 + sample * 4)
  }
  return audio
}

async function completed(page: Page, label: string) {
  const row = page.locator('.jobs-list > li').filter({ has: page.getByText(label, { exact: true }) }).first()
  await expect(row).toHaveText(/Completato/, { timeout: 120_000 })
}

async function processorURL(page: Page) {
  return page.evaluate(async () => {
    // AudioWorklet requests are not exposed as page-level Playwright responses.
    const script = document.querySelector<HTMLScriptElement>('script[type=module][src]')
    if (!script) throw new Error('Manca il modulo del portale.')
    const bundle = await (await fetch(script.src)).text()
    const path = bundle.match(/\/assets\/liveMixProcessor[-_a-zA-Z0-9]*\.js/)?.[0]
    if (!path) throw new Error('Manca l’URL del processore nel build.')
    return new URL(path, location.href).href
  })
}

const model = process.env.SONORA_LIVE_TEST_MODEL
const backend = process.env.SONORA_LIVE_TEST_BACKEND ?? 'mps'
const readyProject = process.env.SONORA_LIVE_TEST_PROJECT
const monitorStart = Number(process.env.SONORA_LIVE_TEST_START_SAMPLE ?? 0)
const farSeek = Number(process.env.SONORA_LIVE_TEST_END_SAMPLE ?? 0)

test('monitor streaming, multitraccia sincrona e ricampionamento', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Progetti', exact: true })).toBeVisible()
  if (readyProject) {
    await page.getByRole('button', { name: new RegExp(readyProject) }).click()
  } else {
    await page.getByLabel('Nome progetto').fill(`Verifica mix live ${Date.now()}`)
    await page.getByRole('button', { name: 'Crea progetto' }).click()
    await page.locator('input[type=file]').setInputFiles({ name: 'monitor.wav', mimeType: 'audio/wav', buffer: stereoFixture() })
    await completed(page, 'Importazione')
    if (model) {
      await page.getByLabel('Modello di separazione').selectOption(model)
      await page.getByLabel('Backend di separazione').selectOption(backend)
      await page.getByRole('button', { name: 'Separa tracce' }).click()
      await completed(page, 'Separazione')
    }
  }

  const pcm: URL[] = []
  page.on('response', response => {
    const url = new URL(response.url())
    if (url.pathname.endsWith('/pcm') && response.status() === 200) pcm.push(url)
  })
  const position = page.getByRole('slider', { name: 'Posizione in campioni' })
  const master = page.locator('meter[aria-label="Picco live Master"]')
  const sourceStem = model || readyProject ? 'dialogue' : 'original'
  const source = page.locator(`.channel-strip.track-${sourceStem}`)
  const transport = page.getByRole('region', { name: 'Trasporto' })
  const samples = Number(await position.getAttribute('max'))
  const live = page.getByRole('button', { name: 'Ascolta mix live' })

  if (monitorStart > 0) await position.fill(String(monitorStart))
  const workletURL = await processorURL(page)
  await live.click()
  await expect(transport.getByRole('status').filter({ hasText: 'Mix live' })).toContainText('Mix live')
  await expect.poll(async () => Number(await position.inputValue())).toBeGreaterThan(monitorStart + 1000)
  await expect.poll(async () => Number(await master.getAttribute('value'))).toBeGreaterThan(-75)
  expect(await page.locator('audio').evaluate(audio => audio.paused)).toBe(true)
  await expect.poll(() => new Set(pcm.map(url => url.pathname)).size).toBeGreaterThanOrEqual(model || readyProject ? 3 : 1)
  expect(pcm.every(url => Number(url.searchParams.get('frames')) <= 131072)).toBeTruthy()

  await source.getByRole('button', { name: 'Solo' }).click()
  await source.getByRole('button', { name: 'Mute' }).click()
  await expect.poll(async () => Number(await master.getAttribute('value'))).toBe(-90)
  await source.getByRole('button', { name: 'Mute' }).click()
  await source.getByRole('button', { name: 'Solo' }).click()
  await expect.poll(async () => Number(await master.getAttribute('value'))).toBeGreaterThan(-75)

  const masterStrip = page.locator('.channel-strip.track-master')
  await masterStrip.getByText('Processori', { exact: true }).click()
  const limiterControl = masterStrip.getByLabel('Limiter true peak', { exact: true })
  const ceilingControl = masterStrip.getByRole('spinbutton', { name: 'Ceiling (dBTP)' })
  const savedCeiling = await ceilingControl.inputValue()
  const savedLimiter = await limiterControl.isChecked()
  await ceilingControl.fill('-30')
  await limiterControl.check()
  await expect.poll(async () => Number(await master.getAttribute('value'))).toBeLessThanOrEqual(-30)
  await expect.poll(async () => Number(await master.getAttribute('value'))).toBeGreaterThan(-75)

  if (!model && !readyProject) {
    await limiterControl.uncheck()
    // Use the original stereo fixture while playback runs. Bypass must undo
    // live compression without a previously rendered master.
    await source.getByText('Processori', { exact: true }).click()
    await source.getByLabel('Compressore', { exact: true }).check()
    await source.getByRole('spinbutton', { name: 'Soglia (dB)' }).fill('-48')
    await source.getByRole('spinbutton', { name: 'Rapporto' }).fill('12')
    await expect.poll(async () => Number(await master.getAttribute('value'))).toBeLessThan(-37)
    await source.getByLabel('Bypass processori').check()
    await expect.poll(async () => Number(await master.getAttribute('value'))).toBeGreaterThan(-27)
    await source.getByLabel('Compressore', { exact: true }).uncheck()
    await source.getByLabel('Bypass processori').uncheck()
    await limiterControl.check()
  }

  // A live seek across block boundaries must obtain new PCM without restarting audio.
  await position.fill(String(Math.floor(samples / 2)))
  await expect.poll(async () => Number(await position.inputValue())).toBeGreaterThan(samples / 2)
  await expect.poll(async () => Number(await master.getAttribute('value'))).toBeGreaterThan(-90)
  if (farSeek > 0) {
    expect(farSeek).toBeLessThan(samples - 5000)
    await position.fill(String(farSeek))
    await expect.poll(async () => Number(await position.inputValue())).toBeGreaterThan(farSeek + 1000)
    await expect.poll(() => pcm.some(url => Number(url.searchParams.get('start_sample')) >= farSeek - 131072)).toBeTruthy()
  }
  await page.getByRole('button', { name: 'Pausa', exact: true }).click()
  const paused = await position.inputValue()
  await expect.poll(() => position.inputValue()).toBe(paused)
  await expect(page.locator('audio')).toHaveJSProperty('paused', true)
  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await expect(position).toHaveValue('0')

  const loopStart = Math.round(samples / 2)
  const loopEnd = loopStart + 9600
  const loopFrom = page.getByRole('spinbutton', { name: 'Inizio', exact: true })
  const loopTo = page.getByRole('spinbutton', { name: 'Fine', exact: true })
  await loopFrom.fill(String(loopStart))
  await loopFrom.press('Enter')
  await loopTo.fill(String(loopEnd))
  await loopTo.press('Enter')
  await page.getByRole('button', { name: 'Loop', exact: true }).click()
  await live.click()
  await expect(page.getByRole('button', { name: 'Loop', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect.poll(async () => Number(await position.inputValue())).toBeGreaterThan(loopStart)
  await page.waitForTimeout(500)
  expect(Number(await position.inputValue())).toBeLessThanOrEqual(loopEnd)
  expect(Number(await position.inputValue())).toBeGreaterThanOrEqual(loopStart)
  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await limiterControl.setChecked(savedLimiter)
  await ceilingControl.fill(savedCeiling)

  // A real AudioWorklet in an offline context verifies both stems share the
  // same sample and phase accumulator, even at a different output clock rate.
  const waveform = await page.evaluate(async url => {
    const outputRate = 44100
    const projectRate = 48000
    const length = 2048
    const offset = 500
    const generation = 1
    const quantum = 128
    const context = new OfflineAudioContext(2, length + quantum, outputRate)
    await context.audioWorklet.addModule(url)
    const node = new AudioWorkletNode(context, 'sonora-live-mix', { numberOfInputs: 0, outputChannelCount: [2] })
    node.connect(context.destination)
    const suspend = context.suspend(quantum / outputRate)
    const rendering = context.startRendering()
    await suspend

    const makeTrack = (stem: string) => ({ stem, channels: 2, gainDb: 0, pan: 0, mute: false, solo: false, invert: false })
    const signal = (sample: number) => (sample - offset) / 8192
    const first = new Float32Array(8192)
    const second = new Float32Array(first.length)
    for (let sample = offset; sample < first.length / 2; sample += 1) {
      first[sample * 2] = signal(sample)
      first[sample * 2 + 1] = signal(sample) * 0.5
      second[sample * 2] = -first[sample * 2]
      second[sample * 2 + 1] = first[sample * 2 + 1]
    }
    node.port.postMessage({ type: 'volume', value: 1 })
    node.port.postMessage({
      type: 'reset', generation, position: offset, playing: true, loop: null,
      config: { rate: projectRate, count: first.length / 2, masterDb: 0, tracks: [makeTrack('dialogue'), makeTrack('music')] },
    })
    node.port.postMessage({
      type: 'block', generation: generation - 1, start: 0, length: first.length / 2,
      tracks: [new Float32Array(first.length).fill(1).buffer, new Float32Array(first.length).fill(1).buffer],
    })
    const ready = new Promise<void>(resolve => {
      node.port.onmessage = ({ data }) => {
        if (data.type === 'block-ready' && data.generation === generation) resolve()
      }
    })
    node.port.postMessage({
      type: 'block', generation, start: 0, length: first.length / 2, tracks: [first.buffer, second.buffer],
    }, [first.buffer, second.buffer])
    await Promise.race([ready, new Promise((_, reject) => setTimeout(() => reject(new Error('PCM non confermato dal processore.')), 3000))])
    await context.resume()
    const output = await rendering
    const right = output.getChannelData(1).slice(quantum)
    const left = output.getChannelData(0).slice(quantum)
    return {
      peakLeft: Math.max(...left.map(Math.abs)),
      peakRight: Math.max(...right),
      error: Math.max(...right.map((sample, frame) => Math.abs(sample - signal(offset + frame * projectRate / outputRate)))),
    }
  }, workletURL)
  expect(waveform.peakLeft).toBeLessThan(1e-7)
  expect(waveform.peakRight).toBeGreaterThan(0.2)
  expect(waveform.error).toBeLessThan(2e-7)
})

test('EQ, compressore e limiter elaborano realmente il mix nell’AudioWorklet', async ({ page }) => {
  await page.goto('/')
  const workletURL = await processorURL(page)
  const result = await page.evaluate(async url => {
    const rate = 48_000
    const quantum = 128
    const count = 32_768

    type Dsp = {
      bypass?: boolean
      eq?: { frequency_hz: number; gain_db: number; q: number }[]
      compressor?: {
        threshold_db: number; ratio: number; knee_db: number; attack_ms: number; release_ms: number; makeup_db: number
      }
      ceiling_dbtp?: number
      limiter?: { enabled: boolean; lookahead_ms: number; release_ms: number }
    }

    async function render(
      input: Float32Array,
      trackDsp?: Dsp,
      masterDsp?: Dsp,
      frameCount = count,
      timelineCount = count,
    ) {
      const context = new OfflineAudioContext(2, frameCount + quantum, rate)
      await context.audioWorklet.addModule(url)
      const node = new AudioWorkletNode(context, 'sonora-live-mix', { numberOfInputs: 0, outputChannelCount: [2] })
      node.connect(context.destination)
      const messages: { buffering: boolean; position: number; readPosition: number; underruns: number; limiterDelayMs?: number }[] = []
      let resolveBlock: () => void = () => undefined
      const blockReady = new Promise<void>(resolve => { resolveBlock = resolve })
      node.port.onmessage = ({ data }) => {
        if (data.type === 'block-ready' && data.generation === 1) resolveBlock()
        if (typeof data.position === 'number') messages.push(data)
      }
      const suspension = context.suspend(quantum / rate)
      const rendering = context.startRendering()
      await suspension
      node.port.postMessage({ type: 'volume', value: 1 })
      node.port.postMessage({
        type: 'reset', generation: 1, position: 0, playing: true, loop: null,
        config: {
          rate, count: timelineCount, masterDb: 0, masterDsp,
          tracks: [{
            stem: 'dialogue', channels: 2, gainDb: 0, pan: 0, mute: false, solo: false, invert: false, dsp: trackDsp,
          }],
        },
      })
      node.port.postMessage({ type: 'block', generation: 1, start: 0, length: input.length / 2, tracks: [input.buffer] }, [input.buffer])
      await Promise.race([
        blockReady,
        new Promise((_, reject) => setTimeout(() => reject(new Error('PCM non confermato dal processore.')), 3000)),
      ])
      await context.resume()
      const output = await rendering
      return {
        left: output.getChannelData(0).slice(quantum),
        right: output.getChannelData(1).slice(quantum),
        messages,
      }
    }

    function fixture(fn: (index: number) => [number, number], length = count) {
      const samples = new Float32Array(length * 2)
      for (let index = 0; index < length; index += 1) samples.set(fn(index), index * 2)
      return samples
    }

    const db = (linear: number) => 20 * Math.log10(linear)

    function toneAmplitude(samples: Float32Array, hz: number, start = 9600, frames = 14_400) {
      let real = 0
      let imaginary = 0
      for (let index = start; index < start + frames; index += 1) {
        const angle = 2 * Math.PI * hz * index / rate
        real += samples[index] * Math.cos(angle)
        imaginary += samples[index] * Math.sin(angle)
      }
      return 2 * Math.hypot(real, imaginary) / frames
    }

    function filteredReference(hz: number, { frequency_hz, gain_db, q }: NonNullable<Dsp['eq']>[number]) {
      const w = 2 * Math.PI * frequency_hz / rate
      const alpha = Math.sin(w) / (2 * q)
      const a = 10 ** (gain_db / 40)
      const coeffs = (scale: number) => [1 + alpha * scale, -2 * Math.cos(w), 1 - alpha * scale]
      const angle = 2 * Math.PI * hz / rate
      function magnitude(coefficients: number[]) {
        return Math.hypot(
          coefficients.reduce((sum, coefficient, index) => sum + coefficient * Math.cos(index * angle), 0),
          coefficients.reduce((sum, coefficient, index) => sum + coefficient * Math.sin(index * angle), 0),
        )
      }
      return db(magnitude(coeffs(a)) / magnitude(coeffs(1 / a)))
    }

    const bands = [{ frequency_hz: 1000, gain_db: 6, q: 1.2 }, { frequency_hz: 6000, gain_db: -5, q: 1.7 }]
    const eqFixture = () => fixture(index => [
      0.08 * (Math.sin(Math.PI * index / 24) + Math.sin(Math.PI * index / 4)),
      0.08 * Math.sin(Math.PI * index / 24),
    ])
    const equalized = await render(eqFixture(), { eq: [bands[0]] }, { eq: [bands[1]] })
    const bypassedEq = await render(eqFixture(), { eq: [bands[0]], bypass: true }, { eq: [bands[1]], bypass: true })
    const eqError = bands.map(({ frequency_hz: hz }) =>
      db(toneAmplitude(equalized.left, hz) / toneAmplitude(bypassedEq.left, hz))
      - bands.reduce((sum, band) => sum + filteredReference(hz, band), 0))
    const eqBypass = Math.max(...bands.map(({ frequency_hz: hz }) => Math.abs(db(toneAmplitude(bypassedEq.left, hz) / 0.08))))

    const compressor = { threshold_db: -18, ratio: 4, knee_db: 0, attack_ms: 6, release_ms: 40, makeup_db: 0 }
    const impulse = (index: number) => index % 2 ? 1 : -1
    const dynamicsFixture = () => fixture(index => [
      (index >= 4800 && index < 18_000 ? 0.8 : 0.05) * impulse(index),
      0.04 * impulse(index),
    ])
    const compressed = await render(dynamicsFixture(), { compressor })
    const masterCompressed = await render(dynamicsFixture(), undefined, { compressor })
    const bypassedComp = await render(dynamicsFixture(), { compressor, bypass: true }, { compressor, bypass: true })
    const expectedCompression = (db(0.8) - compressor.threshold_db) * (1 / compressor.ratio - 1)
    const dynamics = {
      trackError: db(Math.abs(compressed.left[14_000] / bypassedComp.left[14_000])) - expectedCompression,
      masterError: db(Math.abs(masterCompressed.left[14_000] / bypassedComp.left[14_000])) - expectedCompression,
      linked: db(Math.abs(compressed.left[14_000] * 0.04 / (compressed.right[14_000] * 0.8))),
      belowThreshold: db(Math.abs(compressed.left[3000] / bypassedComp.left[3000])),
      releaseAt40ms: db(Math.abs(compressed.left[19_920] / bypassedComp.left[19_920])),
      recovered: db(Math.abs(compressed.left[31_000] / bypassedComp.left[31_000])),
      attack: db(Math.abs(compressed.left[4800] / bypassedComp.left[4800])),
      bypass: db(Math.abs(bypassedComp.left[14_000] / 0.8)),
    }

    // Independent, finer 16× Lanczos interpolation on the actual output.
    // It uses a longer kernel than the live 4× peak detector.
    function truePeak(samples: Float32Array, start: number, end: number) {
      const radius = 36
      const factor = 16
      const sinc = (value: number) => value === 0 ? 1 : Math.sin(Math.PI * value) / (Math.PI * value)
      const kernels = Array.from({ length: factor - 1 }, (_, phase) => {
        const weights = Array.from({ length: 2 * radius + 1 }, (_, tap) => {
          const distance = tap - radius - (phase + 1) / factor
          return Math.abs(distance) >= radius ? 0 : sinc(distance) * sinc(distance / radius)
        })
        const sum = weights.reduce((total, weight) => total + weight, 0)
        return weights.map(weight => weight / sum)
      })
      let peak = 0
      for (let frame = start; frame < end; frame += 1) {
        peak = Math.max(peak, Math.abs(samples[frame]))
        for (const weights of kernels) {
          let value = 0
          for (let tap = 0; tap < weights.length; tap += 1) value += samples[frame + tap - radius] * weights[tap]
          peak = Math.max(peak, Math.abs(value))
        }
      }
      return db(peak)
    }

    const limiter = { enabled: true, lookahead_ms: 5, release_ms: 75 }
    const limiterFixture = () => fixture(index => {
      const tone = 0.99 * Math.sin(Math.PI * index / 2 + Math.PI / 4)
      return [tone, 0.2 * tone]
    })
    const limited = await render(limiterFixture(), undefined, { ceiling_dbtp: -1, limiter })
    const bypassedLimiter = await render(limiterFixture(), undefined, { ceiling_dbtp: -1, limiter, bypass: true })
    const activeDelay = limited.messages.find(message => (message.limiterDelayMs ?? 0) > 0)?.limiterDelayMs
    const reconPeak = db(toneAmplitude(limited.left, rate / 4))
    const untreatedPeak = db(toneAmplitude(bypassedLimiter.left, rate / 4))
    const untreatedSamplePeak = db(Math.max(...bypassedLimiter.left.slice(9600, 24_000).map(Math.abs)))
    const limiterLinking = db(toneAmplitude(limited.right, rate / 4) / (0.2 * toneAmplitude(limited.left, rate / 4)))
    const burst = () => fixture(index => {
      const start = 8000
      const end = 8400
      const distance = Math.min(index - start, end - index)
      const envelope = Math.max(0, Math.min(1, distance / 40))
      const waveform = Math.cos(Math.PI * index / 2 + Math.PI / 4) + 0.35 * Math.sin(0.85 * Math.PI * index)
      return [waveform * envelope, waveform * envelope * 0.1]
    })
    const combinedDsp = { eq: [{ frequency_hz: rate / 4, gain_db: 7, q: 2 }], compressor }
    const untreatedBurst = await render(burst(), combinedDsp)
    const limitedBurst = await render(burst(), combinedDsp, { ceiling_dbtp: -6, limiter })
    const burstIn = truePeak(untreatedBurst.left, 7800, 9000)
    const burstOut = truePeak(limitedBurst.left, 7800, 9500)
    const limitedPulse = await render(fixture(index => index === 1024 ? [0.125, 0.075] : [0, 0], 2048),
      undefined, { ceiling_dbtp: -1, limiter }, 4096, 4096)
    const impulseLeft = limitedPulse.left.findIndex(sample => Math.abs(sample) > 1e-8)
    const impulseRight = limitedPulse.right.findIndex(sample => Math.abs(sample) > 1e-8)

    return {
      eqError, eqBypass, dynamics, reconPeak, untreatedPeak, untreatedSamplePeak, limiterLinking, activeDelay, burstIn, burstOut,
      impulsePosition: impulseLeft, impulseRight,
      dropout: limitedPulse.messages.find(message => message.buffering && message.underruns > 0),
    }
  }, workletURL)

  for (const error of result.eqError) expect(Math.abs(error)).toBeLessThan(0.10)
  expect(result.eqBypass).toBeLessThan(0.01)
  expect(Math.abs(result.dynamics.trackError)).toBeLessThan(0.15)
  expect(Math.abs(result.dynamics.masterError)).toBeLessThan(0.15)
  expect(Math.abs(result.dynamics.linked)).toBeLessThan(0.01)
  expect(Math.abs(result.dynamics.belowThreshold)).toBeLessThan(0.01)
  expect(Math.abs(result.dynamics.bypass)).toBeLessThan(0.01)
  expect(result.dynamics.attack).toBeGreaterThan(-0.2)
  expect(result.dynamics.releaseAt40ms).toBeGreaterThan(-5.0)
  expect(result.dynamics.releaseAt40ms).toBeLessThan(-3.7)
  expect(result.dynamics.recovered).toBeGreaterThan(-0.1)
  expect(result.untreatedSamplePeak).toBeLessThan(-1)
  expect(result.untreatedPeak).toBeGreaterThan(-0.15)
  expect(result.reconPeak).toBeLessThanOrEqual(-1)
  expect(result.reconPeak).toBeGreaterThan(-2.2)
  expect(result.burstIn).toBeGreaterThan(-3)
  expect(result.burstOut).toBeLessThanOrEqual(-6)
  expect(Math.abs(result.limiterLinking)).toBeLessThan(0.01)
  expect(result.activeDelay).toBeGreaterThanOrEqual(5)
  expect(result.impulsePosition).toBe(1024 + Math.round(result.activeDelay! * 48))
  expect(result.impulseRight).toBe(result.impulsePosition)
  expect(result.dropout?.underruns).toBe(1)
  expect(result.dropout?.readPosition).toBe(2048)
  expect(result.dropout?.position).toBe(2048 - Math.round(result.activeDelay! * 48))
})
