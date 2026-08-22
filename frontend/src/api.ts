import type { DatasetDefinition, HealthStatus, RunEvent, RunSnapshot, RunSummary } from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(detail.detail || 'Request failed')
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

export const api = {
  health: () => request<HealthStatus>('/api/health'),
  datasets: () => request<DatasetDefinition[]>('/api/datasets'),
  listRuns: () => request<RunSummary[]>('/api/runs?limit=50'),
  getRun: (id: string) => request<RunSnapshot>(`/api/runs/${id}`),
  createRun: (question: string) =>
    request<RunSnapshot>('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    }),
  deleteRun: (id: string) => request<void>(`/api/runs/${id}`, { method: 'DELETE' }),
}

export function subscribeToRun(
  id: string,
  onEvent: (event: RunEvent) => void,
  onError: () => void,
): () => void {
  const source = new EventSource(`/api/runs/${id}/events`)
  const receive = (message: MessageEvent<string>) => {
    const event = JSON.parse(message.data) as RunEvent
    onEvent(event)
    if (event.type === 'run.completed' || event.type === 'run.failed') source.close()
  }
  const eventTypes = [
    'run.queued', 'run.started', 'run.completed', 'run.failed',
    'node.started', 'node.completed', 'node.failed', 'intent', 'candidates',
    'selection', 'schema', 'query_plan', 'data_summary', 'analysis',
    'validation', 'retry', 'visualization', 'result',
  ]
  eventTypes.forEach((type) => source.addEventListener(type, receive as EventListener))
  source.onerror = onError
  return () => source.close()
}
