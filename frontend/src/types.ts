export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'interrupted'

export interface VisualizationSpec {
  kind: 'none' | 'line' | 'bar' | 'ranking_bar' | 'table'
  x?: string | null
  y?: string | null
  color?: string | null
  title?: string | null
}

export interface TokenUsage {
  model: string
  prompt_tokens: number
  cached_prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  estimated_cost_usd: number
  input_price_per_m: number
  cached_input_price_per_m: number
  output_price_per_m: number
}

export interface ExecutionTrace {
  intent?: Record<string, unknown> | null
  selection_reason?: string | null
  query_plan?: Record<string, unknown> | null
  calculation?: string | null
  rows_used?: number
  validation?: Record<string, unknown> | null
  retry_count?: number
  token_usage?: TokenUsage | null
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
  sources?: Array<{
    dataset_id: string
    title: string
    agency: string
    url: string
    period?: string | null
    unit: string
    cache_freshness?: string | null
  }>
  trace: ExecutionTrace
  error?: string | null
  follow_ups?: string[]
  assumptions?: string[]
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
  busy?: boolean
  queue_depth?: number
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
  start_date?: string | null
  end_date?: string | null
  row_count?: number | null
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
