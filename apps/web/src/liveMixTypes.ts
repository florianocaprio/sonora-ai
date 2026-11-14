import type { AutomationPoint, Region, Stem, TrackSettings } from './api'

export type LiveStem = Exclude<Stem, 'master' | 'difference'>

export type LiveChannelSettings = Pick<TrackSettings, 'trim_db' | 'eq' | 'compressor' | 'bypass'>
export type LiveMasterSettings = LiveChannelSettings & Pick<TrackSettings, 'ceiling_dbtp' | 'limiter'>

export interface LiveTrack {
  stem: LiveStem
  assetId: string
  channels: 1 | 2
  gainDb: number
  pan: number
  mute: boolean
  solo: boolean
  invert: boolean
  dsp?: LiveChannelSettings
  automation?: Partial<Record<'gain_db' | 'pan' | 'mute', AutomationPoint[]>>
}

export interface LiveMixConfig {
  rate: number
  count: number
  tracks: LiveTrack[]
  masterDb: number
  masterDsp?: LiveMasterSettings
}

export interface LiveState {
  position: number
  playing: boolean
  buffering: boolean
  peaks: Partial<Record<LiveStem | 'master', number>>
  underruns: number
  deviceRate?: number
  limiterDelayMs?: number
  error?: string
}

export type MixMessage =
  | { type: 'reset'; generation: number; position: number; config: LiveMixConfig; loop: Region | null; playing: boolean }
  | { type: 'block'; generation: number; start: number; length: number; tracks: ArrayBuffer[] }
  | { type: 'retain'; generation: number; starts: number[] }
  | { type: 'settings'; config: LiveMixConfig }
  | { type: 'loop'; loop: Region | null }
  | { type: 'volume'; value: number }

export interface MixStatus extends LiveState {
  generation: number
  readPosition: number
}

export type MixEvent = MixStatus | { type: 'block-ready'; generation: number; start: number }
