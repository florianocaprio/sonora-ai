import { expect, test, type Page } from '@playwright/test'

function fixture() {
  const rate = 48_000
  const count = rate * 2
  const buffer = Buffer.alloc(44 + 2 * count)
  buffer.write('RIFF', 0)
  buffer.writeUInt32LE(buffer.length - 8, 4)
  buffer.write('WAVEfmt ', 8)
  buffer.writeUInt32LE(16, 16)
  buffer.writeUInt16LE(1, 20)
  buffer.writeUInt16LE(1, 22)
  buffer.writeUInt32LE(rate, 24)
  buffer.writeUInt32LE(rate * 2, 28)
  buffer.writeUInt16LE(2, 32)
  buffer.writeUInt16LE(16, 34)
  buffer.write('data', 36)
  buffer.writeUInt32LE(count * 2, 40)
  for (let index = 0; index < count; index += 1) {
    const time = index / rate
    const signal = 0.07 * Math.sin(2 * Math.PI * 220 * time) + 0.025 * Math.sin(2 * Math.PI * 50 * time) + 0.04
    buffer.writeInt16LE(Math.round((index === 6000 ? 0.82 : signal) * 32767), 44 + index * 2)
  }
  return buffer
}

async function waitJob(page: Page, label: string) {
  const row = page.locator('.jobs-list > li').filter({ has: page.getByText(label, { exact: true }) }).first()
  await expect(row).toContainText('Completato', { timeout: 120_000 })
}

const model = process.env.SONORA_E2E_MODEL
const backend = process.env.SONORA_E2E_BACKEND ?? 'mps'

test(model ? 'flusso reale con checkpoint' : 'flusso di orchestrazione su fixture sintetica', async ({ page }) => {
  const name = `Verifica browser ${Date.now()}`
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Progetti', exact: true })).toBeVisible()
  await page.getByLabel('Nome progetto').fill(name)
  await page.getByRole('button', { name: 'Crea progetto' }).click()
  await expect(page.getByRole('button', { name: 'Importa audio' })).toBeVisible()
  await page.locator('input[type=file]').setInputFiles({ name: 'fixture.wav', mimeType: 'audio/wav', buffer: fixture() })
  await waitJob(page, 'Importazione')
  await expect(page.getByRole('button', { name: 'Riproduci' })).toBeEnabled()
  await page.getByRole('button', { name: 'Riproduci' }).click()
  await expect.poll(() => page.locator('audio').evaluate(element => element.currentTime)).toBeGreaterThan(0.02)
  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await page.getByRole('button', { name: 'Spettrogramma', exact: true }).click()
  await expect(page.getByRole('img', { name: /Magnitudine/ })).toBeVisible()
  if (model) {
    await page.getByLabel('Modello di separazione').selectOption(model)
    await page.getByLabel('Backend di separazione').selectOption(backend)
    await page.getByRole('button', { name: 'Separa tracce' }).click()
    await waitJob(page, 'Separazione')
    await page.getByRole('button', { name: 'Dialoghi', exact: true }).click()
  }
  await page.getByRole('button', { name: 'Analizza traccia' }).click()
  await waitJob(page, 'Analisi')
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  const startRestoration = inspector.getByRole('button', { name: 'Avvia restauro' })
  await expect(startRestoration).toBeVisible()
  await startRestoration.click()
  await expect(startRestoration).toBeDisabled()
  const processor = inspector.getByLabel('Processore di restauro')
  const add = inspector.getByRole('button', { name: 'Aggiungi', exact: true })
  const operations = inspector.locator('.operation')
  const presets = inspector.getByText('Preset personali', { exact: true })
  const presetName = inspector.getByLabel('Nome preset')
  const loadPreset = inspector.getByLabel('Carica preset')
  const savePreset = inspector.getByRole('button', { name: 'Salva', exact: true })
  await processor.selectOption('dc_remove')
  await add.click()
  await presets.click()
  await presetName.fill('Collaudo')
  await savePreset.click()
  await inspector.getByRole('button', { name: 'Medium', exact: true }).click()
  await expect(operations).toHaveCount(0)
  await expect(loadPreset.getByRole('option', { name: 'Collaudo' })).toHaveCount(0)
  await processor.selectOption('peq')
  await add.click()
  await presetName.fill('Collaudo')
  await savePreset.click()
  await inspector.getByRole('button', { name: 'High', exact: true }).click()
  await expect(operations).toHaveCount(0)
  await processor.selectOption('declick')
  await add.click()
  await inspector.getByRole('button', { name: 'Basic', exact: true }).click()
  await expect(operations.locator('summary strong')).toHaveText(['Rimozione DC'])
  await loadPreset.selectOption('Collaudo')
  await expect(operations.locator('summary strong')).toHaveText(['Rimozione DC'])
  await inspector.getByRole('button', { name: 'High', exact: true }).click()
  await expect(operations.locator('summary strong')).toHaveText(['Riparazione click'])
  await inspector.getByRole('button', { name: 'Medium', exact: true }).click()
  await expect(operations.locator('summary strong')).toHaveText(['Equalizzatore parametrico'])
  await processor.selectOption('dc_remove')
  await add.click()
  await operations.nth(1).locator('summary').click()
  await operations.nth(1).getByRole('button', { name: 'Sposta operazione in alto' }).click()
  await processor.selectOption('declick')
  await add.click()
  await operations.last().locator('summary').click()
  await operations.last().getByLabel('Bypass').check()
  await expect(operations.locator('summary strong')).toHaveText(['Rimozione DC', 'Equalizzatore parametrico', 'Riparazione click'])
  const restoration = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/restore'))
  await startRestoration.click()
  const started = await restoration
  expect(started.status()).toBe(202)
  expect(started.request().postDataJSON()).toMatchObject({
    profile: 'medium', operations: [{ type: 'dc_remove' }, { type: 'peq' }, { type: 'declick', bypass: true }],
  })
  await waitJob(page, 'Restauro')
  const job = await started.json()
  const refreshed = await page.request.get(started.url().replace(/\/restore$/, ''), {
    headers: { 'X-Sonora-Token': started.request().headers()['x-sonora-token'] },
  })
  expect(refreshed.ok()).toBeTruthy()
  const project = await refreshed.json()
  const restored = project.assets.find(asset => asset.kind === 'restored' && asset.metadata.job_id === job.id)
  expect(restored.status).toBe('proposed')
  expect(restored.metadata.operations.map(operation => operation.type)).toEqual(['dc_remove', 'peq'])
  await inspector.getByRole('button', { name: 'Approva', exact: true }).click()
  await expect(inspector.getByText('Approvata', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Render mix' }).click()
  await waitJob(page, 'Mix DSP')
  await page.getByRole('button', { name: 'Report', exact: true }).click()
  await page.getByRole('button', { name: 'Esporta master e stem' }).click()
  await waitJob(page, 'Esportazione')
  await expect(page.getByRole('link', { name: 'report.html' })).toBeVisible()
  const manifest = await page.getByRole('link', { name: 'manifest.json' }).getAttribute('href')
  expect(manifest).toBeTruthy()
  const response = await page.request.get(manifest!)
  const report = await response.json()
  expect(report.project_name).toBe(name)
  expect(report.tracks.master.measurement.sample_count).toBe(96_000)
  if (model) expect(Object.keys(report.tracks)).toEqual(expect.arrayContaining(['dialogue', 'music', 'effects']))
  await page.reload()
  await expect(page.getByText(name, { exact: true }).first()).toBeVisible()
})
