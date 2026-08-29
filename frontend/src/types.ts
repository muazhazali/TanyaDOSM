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
  conversation_id: string
  question: string
  resolved_question?: string | null
  status: RunStatus
  current_node?: string | null
  error?: string | null
  created_at: string
  updated_at: string
  queue_position?: number | null
}

export interface ConversationSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  turn_count: number
  latest_status: RunStatus
}

export interface ConversationSnapshot extends ConversationSummary {
  turns: RunSnapshot[]
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
  llm: string
  embeddings: string
}

export interface DatasetDefinition {
  dataset_id: string
  title: string
  description: string
  domain: string
  aliases: string[]
  dimensions: string[]
  measures: Array<{ name: string; aliases: string[]; unit: string }>
  frequency: 'monthly' | 'quarterly' | 'annual'
  geography_level: 'national' | 'state' | 'district'
  source_agency: string
  source_url: string
  caveats: string[]
}

export interface CatalogueMonitorState {
  last_checked?: string | null
  registered: Record<string, {
    dataset_id: string
    last_checked?: string | null
    last_changed?: string | null
    status: string
    error?: string | null
  }>
  discovered: Array<{
    dataset_id: string
    title?: string | null
    source_url?: string | null
    discovered_at: string
  }>
  discovery_error?: string | null
}
