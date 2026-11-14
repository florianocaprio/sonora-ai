export const API = '/api/v1'

export type Stem = 'original' | 'dialogue' | 'music' | 'effects' | 'residual' | 'master' | 'difference'
export type Profile = 'basic' | 'medium' | 'high'
export const restorationProfiles: Record<Profile, string> = { basic: 'Basic', medium: 'Medium', high: 'High' }
export type Depth = 'quick' | 'standard' | 'deep'
export type OperationType = 'dc_remove' | 'dehum' | 'declick' | 'peq' | 'microgap' | 'inpaint'
export type Region = { start_sample: number; end_sample: number }
export type Metric = string | number | boolean | null | Metric[] | { [key: string]: Metric }

export interface Operation extends Region {
  type: OperationType
  wet: number
  bypass?: boolean
  params: Record<string, number>
}

export interface AudioAsset {
  id: string
  stem: Stem
  kind: 'original' | 'separated' | 'restored' | 'preview' | 'difference'
  status: 'approved' | 'proposed' | 'rejected'
  parent_id: string | null
  name: string
  created_at: string
  metadata: {
    sample_rate: number
    sample_count: number
    start_sample?: number
    profile?: Profile
    channels?: number
    codec?: string
    original_filename?: string
    metrics?: Record<string, Metric>
    sample_peak_dbfs?: number | null
    rms_dbfs?: number | null
    true_peak_dbtp?: number | null
    loudness?: Record<string, Metric>
    generated_regions?: (Region & { model_id?: string; classification?: 'generated' })[]
    tracks?: Partial<Record<Stem, Record<string, Metric>>>
    gain_reduction_db?: number | null
    stereo_correlation?: number | null
    [key: string]: unknown
  }
}

export interface Defect extends Region {
  id: string
  type: string
  severity: string | number
  confidence: number
  status: 'unreviewed' | 'confirmed' | 'dismissed' | 'repaired'
  note?: string | null
  origin?: string
  evidence?: Record<string, Metric>
  proposal?: Operation | string | null
  proposed_operation?: Operation | string | null
}

export interface Analysis {
  id: string
  asset_id: string
  metrics: Record<string, Metric>
  events: Defect[]
}

export type JobStatus = 'queued' | 'running' | 'cancelling' | 'cancelled' | 'succeeded' | 'failed' | 'blocked'

export interface Job {
  id: string
  project_id: string | null
  attempts?: number
  type: string
  status: JobStatus
  stage?: string | null
  processed: number
  total?: number | null
  error?: string | { detail?: string; message?: string } | null
  result?: unknown
  created_at: string
}

export interface Model {
  id: string
  task?: 'separation' | 'inpainting'
  name: string
  status: string
  status_detail?: string
  backends: string[]
  checkpoint?: string
  download_bytes?: number
  size_bytes?: number
  stereo_warning?: string
  native_sample_rate?: number
  native_channels?: number
  backend_detail?: string
  code_revision?: string
  weights_revision?: string
  license?: string
  code_license?: string
  weights_license?: string
  sha256?: string
  can_install?: boolean
  checkpoint_required?: boolean
  stems?: Stem[]
  min_gap_ms?: number
  max_gap_ms?: number
  min_context_ms_per_side?: number
}

export interface Health {
  platform: string
  machine: string
  memory_bytes?: number | null
  mps?: boolean | null
  ffmpeg?: boolean
  data_dir: string
  disk_free_bytes?: number
  max_upload_bytes?: number
}

export interface ExportRecord {
  id: string
  created_at: string
  artifacts: { name: string; size: number; sha256: string; url: string }[]
  warnings: string[]
}

export interface Equalizer {
  frequency_hz: number
  gain_db: number
  q: number
}

export interface Compressor {
  threshold_db: number
  ratio: number
  knee_db: number
  attack_ms: number
  release_ms: number
  makeup_db: number
}

export interface AutomationPoint {
  sample: number
  value: number | boolean
}

export interface TrackSettings {
  asset_id?: string
  gain_db?: number
  ceiling_dbtp?: number
  trim_db?: number
  pan?: number
  mute?: boolean
  solo?: boolean
  polarity?: boolean
  bypass?: boolean
  eq?: Equalizer[]
  compressor?: Compressor
  limiter?: { enabled: boolean; lookahead_ms: number; release_ms: number }
  automation?: Partial<Record<'gain_db' | 'pan' | 'mute', AutomationPoint[]>>
}

export interface MixerSettings {
  tracks: Partial<Record<Stem, TrackSettings>>
  master: Omit<TrackSettings, 'asset_id'>
}

export interface Project {
  id: string
  name: string
  archived: boolean
  created_at: string
  updated_at: string
  assets: AudioAsset[]
  jobs: Job[]
  analyses: Analysis[]
  exports: ExportRecord[]
  mixer: MixerSettings | null
}

let session: Promise<string> | undefined

function token(): Promise<string> {
  if (!session) {
    session = fetch(`${API}/session`, { credentials: 'same-origin' })
      .then(async response => {
        if (!response.ok) throw new Error('Sessione locale non disponibile. Verifica che SONORA AI sia avviato.')
        const value: { token: string } = await response.json()
        return value.token
      })
      .catch(error => {
        session = undefined
        throw error
      })
  }
  return session
}

type RequestSettings = { method?: 'GET' | 'POST' | 'PATCH'; data?: unknown; signal?: AbortSignal }

export async function request<T>(path: string, { method = 'GET', data, signal }: RequestSettings = {}): Promise<T> {
  const headers = new Headers({ 'X-Sonora-Token': await token() })
  const form = data instanceof FormData
  if (data !== undefined && !form) headers.set('Content-Type', 'application/json')
  if (method === 'POST') headers.set('Idempotency-Key', crypto.randomUUID())
  const response = await fetch(API + path, {
    method,
    headers,
    signal,
    credentials: 'same-origin',
    body: form ? data : data === undefined ? undefined : JSON.stringify(data),
  })
  if (response.status === 401) session = undefined
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(error => error.msg).join(' · ') : payload?.message
    throw new Error(message || `Richiesta locale non riuscita (HTTP ${response.status}).`)
  }
  return await response.json() as T
}

export async function requestPCM(projectId: string, assetId: string, startSample: number, frames: number, signal?: AbortSignal): Promise<ArrayBuffer> {
  const query = new URLSearchParams({ start_sample: String(startSample), frames: String(frames) })
  const path = API + assetPath(projectId, assetId) + '/pcm?' + query
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      headers: { 'X-Sonora-Token': await token() },
      signal,
    })
    if (response.status === 401 && attempt === 0) {
      session = undefined
      continue
    }
    if (!response.ok) throw new Error(`Lettura PCM non riuscita (HTTP ${response.status}).`)
    return response.arrayBuffer()
  }
  throw new Error('Sessione PCM non disponibile.')
}

export const projectPath = (projectId: string) => `/projects/${encodeURIComponent(projectId)}`
export const assetPath = (projectId: string, assetId: string) => `${projectPath(projectId)}/assets/${encodeURIComponent(assetId)}`
export const jobPath = (jobId: string) => `/jobs/${encodeURIComponent(jobId)}`
export const modelPath = (modelId: string) => `/models/${encodeURIComponent(modelId)}`
export const isActive = (job: Job) => ['queued', 'running', 'cancelling'].includes(job.status)

export function localArtifactUrl(url: string): string | undefined {
  try {
    const target = new URL(url, window.location.origin)
    if (target.origin === window.location.origin && target.pathname.startsWith(API + '/')) return target.pathname + target.search
  } catch {
    return undefined
  }
}

export function audioMetrics(asset?: AudioAsset): Record<string, Metric> | undefined {
  if (!asset) return undefined
  const values = asset.metadata
  if (values.metrics) return values.metrics
  if (values.sample_peak_dbfs === undefined && values.loudness === undefined && values.rms_dbfs === undefined) return undefined
  return Object.fromEntries(
    Object.entries({
      sample_peak_dbfs: values.sample_peak_dbfs,
      rms_dbfs: values.rms_dbfs,
      true_peak_dbtp: values.true_peak_dbtp,
      stereo_correlation: values.stereo_correlation,
      gain_reduction_db: values.gain_reduction_db,
      loudness: values.loudness,
    }).filter((entry): entry is [string, number | Record<string, Metric> | null] => entry[1] !== undefined),
  )
}

export function preferredAsset(assets: AudioAsset[], stem: Stem): AudioAsset | undefined {
  const candidates = assets.filter(asset => asset.stem === stem && asset.status === 'approved' && asset.kind !== 'preview')
  return candidates.sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
}

export function restorationVersionLabels(assets: AudioAsset[]): Map<string, string> {
  const counts: Partial<Record<Stem, number>> = {}
  const labels = new Map<string, string>()
  for (const asset of assets) {
    if (asset.kind !== 'restored') continue
    const number = (counts[asset.stem] ?? 0) + 1
    counts[asset.stem] = number
    const profile = asset.metadata.profile && restorationProfiles[asset.metadata.profile]
    labels.set(asset.id, `Restauro ${String(number).padStart(2, '0')}${profile ? ` · ${profile}` : ''}`)
  }
  return labels
}

export function formatTime(samples: number, rate: number): string {
  if (!rate) return '00:00.000'
  const totalMs = Math.max(0, Math.floor(samples / rate * 1000))
  const hours = Math.floor(totalMs / 3_600_000)
  const minutes = Math.floor(totalMs / 60_000) % 60
  const seconds = Math.floor(totalMs / 1000) % 60
  const pad = (value: number, size = 2) => String(value).padStart(size, '0')
  return `${hours ? pad(hours) + ':' : ''}${pad(minutes)}:${pad(seconds)}.${pad(totalMs % 1000, 3)}`
}

export const formatNumber = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 2 })

export function fileSize(bytes?: number | null): string {
  if (!bytes) return '—'
  if (bytes >= 1024 ** 3) return `${formatNumber.format(bytes / (1024 ** 3))} GiB`
  if (bytes >= 1024 ** 2) return `${formatNumber.format(bytes / (1024 ** 2))} MiB`
  return `${formatNumber.format(bytes / 1024)} KiB`
}

export const stemNames: Record<Stem, string> = {
  original: 'Originale',
  dialogue: 'Dialoghi',
  music: 'Musica',
  effects: 'Effetti',
  residual: 'Residuo',
  master: 'Master',
  difference: 'Differenza',
}
