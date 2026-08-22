import { describe, expect, it } from 'vitest'
import { initialStreamState, latestArtifact, streamReducer } from './runState'
import type { RunEvent } from './types'

const event = (sequence: number, type = 'intent'): RunEvent => ({
  run_id: 'run-1', sequence, type, timestamp: '2026-01-01T00:00:00Z', payload: { sequence },
})

describe('streamReducer', () => {
  it('orders replayed events and ignores duplicates', () => {
    let state = streamReducer(initialStreamState, { type: 'event', event: event(2) })
    state = streamReducer(state, { type: 'event', event: event(1) })
    state = streamReducer(state, { type: 'event', event: event(2) })
    expect(state.events.map((item) => item.sequence)).toEqual([1, 2])
  })

  it('returns the newest artifact of a type', () => {
    expect(latestArtifact([event(1), event(2)], 'intent')?.sequence).toBe(2)
  })
})
