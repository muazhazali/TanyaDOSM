import type { RunEvent } from './types'

export interface StreamState {
  events: RunEvent[]
  connected: boolean
}

export type StreamAction =
  | { type: 'reset' }
  | { type: 'connected'; value: boolean }
  | { type: 'event'; event: RunEvent }

export const initialStreamState: StreamState = { events: [], connected: false }

export function streamReducer(state: StreamState, action: StreamAction): StreamState {
  if (action.type === 'reset') return initialStreamState
  if (action.type === 'connected') return { ...state, connected: action.value }
  if (state.events.some((event) => event.sequence === action.event.sequence)) return state
  return {
    ...state,
    connected: true,
    events: [...state.events, action.event].sort((a, b) => a.sequence - b.sequence),
  }
}

export function latestArtifact(events: RunEvent[], type: string): RunEvent | undefined {
  return [...events].reverse().find((event) => event.type === type)
}
