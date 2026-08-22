export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'interrupted'

export interface VisualizationSpec {
  kind: 'none' | 'line' | 'bar' | 'ranking_bar' | 'table'
  x?: string | null
  y?: string | null
  color?: string | null
  title?: string | null
}

export interface AnswerPayload {
  answer: string
  table_rows: Record<string, unknown>[]
  visualization: VisualizationSpec
  source?: {
    dataset_id: string
    title: string
    agency: string
    url: string
    period?: string | null
    unit: string
    cache_freshness?: string | null
  } | null
  trace: Record<string, unknown>
  error?: string | null
}

export interface RunSummary {
  id: string
  question: string
  status: RunStatus
  current_node?: string | null
  error?: string | null
  created_at: string
  updated_at: string
}

export interface RunSnapshot extends RunSummary {
  answer?: AnswerPayload | null
  last_sequence: number
}

export interface RunEvent {
  run_id: string
  sequence: number
  type: string
  timestamp: string
  node?: string | null
  duration_ms?: number | null
  payload: Record<string, unknown>
}

export interface HealthStatus {
  status: string
  database: string
  catalogue: string
  ollama: string
}
