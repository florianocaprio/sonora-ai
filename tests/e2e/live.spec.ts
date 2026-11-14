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
  const workletURL = await page.evaluate(async () => {
    // AudioWorklet requests are not exposed as page-level Playwright responses.
    const script = document.querySelector<HTMLScriptElement>('script[type=module][src]')
    if (!script) throw new Error('Manca il modulo del portale.')
    const bundle = await (await fetch(script.src)).text()
    const path = bundle.match(/\/assets\/liveMixProcessor[-_a-zA-Z0-9]*\.js/)?.[0]
    if (!path) throw new Error('Manca l’URL del processore nel build.')
    return new URL(path, location.href).href
  })
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
