import { lazy, Suspense, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, BarChart3, Check, ChevronDown, Circle, Clock3, Copy, Database, Download, ExternalLink, FileQuestion, LoaderCircle, Menu, MoreHorizontal, Pencil, RefreshCw, Search, Send, Share2, ThumbsDown, ThumbsUp, Trash2, X } from 'lucide-react'
import { api, subscribeToRun } from './api'
import { initialStreamState, latestArtifact, streamReducer } from './runState'
import type { AnswerPayload, DatasetDefinition, RunEvent, RunSnapshot, RunStatus } from './types'

const ResultChart = lazy(() => import('./Chart').then((module) => ({ default: module.ResultChart })))

const examples = [
  { label: 'Find a number', question: "What is Malaysia's latest population?" },
  { label: 'Compare places', question: 'Compare Johor and Selangor population in 2025.' },
  { label: 'View a trend', question: 'Show unemployment trends in Johor since 2020.' },
  { label: 'Tanya dalam BM', question: 'Negeri mana mempunyai penduduk paling ramai pada tahun 2025?' },
]

const nodeLabels: Record<string, string> = {
  parse_question: 'Understanding your question', search_catalogue: 'Finding official data', select_dataset: 'Choosing the best dataset',
  inspect_schema: 'Checking the source', build_query_plan: 'Preparing the data request', execute_query: 'Retrieving figures',
  analyze_result: 'Working out the answer', validate_result: 'Checking the result', generate_visualization: 'Preparing the chart',
  generate_response: 'Writing the answer', graceful_failure: 'Preparing a helpful response',
}

const publicSteps = [
  { label: 'Understanding your question', description: 'Identifying the topic, place and time period.', nodes: ['parse_question'] },
  { label: 'Finding the right official data', description: 'Matching your question with a curated DOSM dataset.', nodes: ['search_catalogue', 'select_dataset'] },
  { label: 'Checking the source', description: 'Confirming the available fields and data freshness.', nodes: ['inspect_schema'] },
  { label: 'Working out the answer', description: 'Retrieving, calculating and checking the figures.', nodes: ['build_query_plan', 'execute_query', 'analyze_result', 'validate_result'] },
  { label: 'Preparing your result', description: 'Presenting the answer and chart clearly.', nodes: ['generate_visualization', 'generate_response', 'graceful_failure'] },
] as const

function StatusPill({ status }: { status: RunStatus }) {
  const labels: Record<RunStatus, string> = { queued: 'Waiting', running: 'Working', completed: 'Verified', failed: 'Needs attention', interrupted: 'Stopped' }
  const colors: Record<RunStatus, string> = { queued: 'bg-amber-100 text-amber-800', running: 'bg-blue-100 text-blue-800', completed: 'bg-emerald-100 text-emerald-800', failed: 'bg-red-100 text-red-800', interrupted: 'bg-slate-200 text-slate-700' }
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${colors[status]}`}>{labels[status]}</span>
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return new Intl.NumberFormat('en-MY', { maximumFractionDigits: 2 }).format(value)
  const text = String(value)
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) {
    const date = new Date(text)
    if (!Number.isNaN(date.valueOf())) return new Intl.DateTimeFormat('en-MY', { year: 'numeric', month: 'short', day: 'numeric' }).format(date)
  }
  return text
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat('en-MY', { year: 'numeric', month: 'short', day: 'numeric' }).format(date)
}

function formatPeriod(period?: string | null): string {
  if (!period) return 'Not specified'
  const [start, end] = period.split(/\s+to\s+/i)
  if (!end || start === end) return formatDate(start)
  return `${formatDate(start)} to ${formatDate(end)}`
}

function formatChatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return ''
  const today = new Date()
  const sameDay = date.toDateString() === today.toDateString()
  return sameDay
    ? new Intl.DateTimeFormat('en-MY', { hour: 'numeric', minute: '2-digit' }).format(date)
    : new Intl.DateTimeFormat('en-MY', { day: 'numeric', month: 'short' }).format(date)
}

function friendlyAnswer(answer: AnswerPayload): string {
  return answer.answer.replace(/([\d,]+(?:\.\d+)?)\s+thousand\s+(people|persons)/gi, (match, raw: string, noun: string) => {
    const value = Number(raw.replaceAll(',', ''))
    if (!Number.isFinite(value) || Math.abs(value) < 1000) return match
    return `${new Intl.NumberFormat('en-MY', { maximumFractionDigits: 2 }).format(value / 1000)} million ${noun}`
  })
}

function headlineValue(answer: AnswerPayload): { value: string; label: string } | null {
  if (answer.table_rows.length !== 1) return null
  const entry = Object.entries(answer.table_rows[0]).find(([, value]) => typeof value === 'number')
  if (!entry) return null
  const [key, raw] = entry as [string, number]
  const unit = answer.source?.unit || ''
  if (/thousand (people|persons)/i.test(unit) && Math.abs(raw) >= 1000) return { value: `${new Intl.NumberFormat('en-MY', { maximumFractionDigits: 2 }).format(raw / 1000)} million`, label: unit.replace(/thousand /i, '') }
  return { value: formatCell(raw), label: unit || key.replaceAll('_', ' ') }
}

function csvValue(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

function downloadRows(answer: AnswerPayload, runId: string) {
  if (!answer.table_rows.length) return
  const columns = Object.keys(answer.table_rows[0])
  const csv = [columns.join(','), ...answer.table_rows.map((row) => columns.map((column) => csvValue(row[column])).join(','))].join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `tanyadosm-${runId}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}

function ResultTable({ answer }: { answer: AnswerPayload }) {
  const columns = answer.table_rows.length ? Object.keys(answer.table_rows[0]) : []
  const [sort, setSort] = useState<{ column: string; direction: 'asc' | 'desc' } | null>(null)
  const rows = useMemo(() => {
    if (!sort) return answer.table_rows
    return [...answer.table_rows].sort((a, b) => {
      const left = a[sort.column]; const right = b[sort.column]
      const result = typeof left === 'number' && typeof right === 'number' ? left - right : String(left ?? '').localeCompare(String(right ?? ''))
      return sort.direction === 'asc' ? result : -result
    })
  }, [answer.table_rows, sort])
  if (!rows.length) return null
  return <details className="rounded-2xl border border-slate-200 bg-white">
    <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700">View data used ({rows.length} {rows.length === 1 ? 'row' : 'rows'})</summary>
    <div className="max-h-96 overflow-auto border-t border-slate-200"><table className="min-w-full divide-y divide-slate-200 text-sm">
      <caption className="sr-only">Official data rows used to prepare this answer</caption>
      <thead className="sticky top-0 bg-slate-50"><tr>{columns.map((column) => <th key={column} scope="col" className="px-4 py-3 text-left font-semibold"><button onClick={() => setSort((current) => ({ column, direction: current?.column === column && current.direction === 'asc' ? 'desc' : 'asc' }))} className="capitalize hover:text-emerald-700">{column.replaceAll('_', ' ')}</button></th>)}</tr></thead>
      <tbody className="divide-y divide-slate-100">{rows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column} className="whitespace-nowrap px-4 py-3">{formatCell(row[column])}</td>)}</tr>)}</tbody>
    </table></div>
  </details>
}

function Results({ answer, runId, question, onFollowUp }: { answer: AnswerPayload; runId: string; question: string; onFollowUp?: (value: string) => void }) {
  const [copied, setCopied] = useState<'answer' | 'link' | null>(null)
  const [feedback, setFeedback] = useState<boolean | null>(null)
  const feedbackMutation = useMutation({ mutationFn: (helpful: boolean) => api.saveFeedback(runId, helpful) })
  const headline = headlineValue(answer)
  const rowsUsed = Number(answer.trace.rows_used ?? answer.table_rows.length)
  const showChart = answer.table_rows.length > 1 && !['none', 'table'].includes(answer.visualization.kind) && answer.visualization.x && answer.visualization.y
  const copy = async (kind: 'answer' | 'link') => {
    const value = kind === 'answer' ? friendlyAnswer(answer) : `${window.location.origin}${window.location.pathname}?run=${runId}`
    await navigator.clipboard.writeText(value)
    setCopied(kind)
    window.setTimeout(() => setCopied(null), 1800)
  }
  const sendFeedback = (helpful: boolean) => { setFeedback(helpful); feedbackMutation.mutate(helpful) }
  return <section className="space-y-5" aria-live="polite">
    <div className={`rounded-2xl border p-5 ${answer.error ? 'border-amber-200 bg-amber-50' : 'border-emerald-200 bg-gradient-to-br from-emerald-50 to-white'}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Answer</p>
      {headline && !answer.error && <div className="mt-3"><p className="text-4xl font-bold tracking-tight text-emerald-900">{headline.value}</p><p className="mt-1 text-sm font-medium text-emerald-700">{headline.label}</p></div>}
      <p className={`${headline ? 'mt-4 text-base' : 'mt-2 text-lg'} leading-relaxed text-slate-900`}>{friendlyAnswer(answer)}</p>
    </div>
    {showChart && <Suspense fallback={<div className="h-80 animate-pulse rounded-2xl bg-slate-100" aria-label="Loading chart" />}><ResultChart answer={answer} /></Suspense>}
    <ResultTable answer={answer} />
    {answer.source && <div className="rounded-2xl border border-slate-200 bg-white p-4 text-sm text-slate-600">
      <div className="mb-2 flex items-center gap-2 font-semibold text-slate-800"><Database size={16} /> Official source</div>
      <a className="font-medium text-emerald-700 underline" href={answer.source.url} target="_blank" rel="noreferrer">{answer.source.title}</a>
      <p className="mt-1">{answer.source.agency} · Data date: {formatPeriod(answer.source.period)}</p>
      <p className="mt-1 text-xs text-slate-500">Unit: {answer.source.unit} · Based on {rowsUsed} verified {rowsUsed === 1 ? 'row' : 'rows'}.</p>
    </div>}
    {!answer.error && <div className="flex flex-wrap items-center gap-2 border-t border-slate-200 pt-4">
      <button onClick={() => void copy('answer')} className="action-button"><Copy size={15} /> {copied === 'answer' ? 'Copied' : 'Copy answer'}</button>
      {answer.source && <a href={answer.source.url} target="_blank" rel="noreferrer" className="action-button"><ExternalLink size={15} /> Open source</a>}
      <div className="hidden gap-2 sm:flex">
        {answer.table_rows.length > 0 && <button onClick={() => downloadRows(answer, runId)} className="action-button"><Download size={15} /> Download CSV</button>}
        <button onClick={() => void copy('link')} className="action-button"><Share2 size={15} /> {copied === 'link' ? 'Link copied' : 'Share result'}</button>
      </div>
      <details className="relative sm:hidden">
        <summary className="action-button cursor-pointer list-none"><MoreHorizontal size={15} /> More</summary>
        <div className="absolute left-0 top-11 z-10 min-w-40 space-y-1 rounded-xl border border-slate-200 bg-white p-2 shadow-lg">
          {answer.table_rows.length > 0 && <button onClick={() => downloadRows(answer, runId)} className="action-button w-full border-0"><Download size={15} /> Download CSV</button>}
          <button onClick={() => void copy('link')} className="action-button w-full border-0"><Share2 size={15} /> {copied === 'link' ? 'Link copied' : 'Share result'}</button>
        </div>
      </details>
      <span className="ml-auto text-xs text-slate-500">Useful?</span>
      <button disabled={feedback !== null} aria-label="This answer was useful" onClick={() => sendFeedback(true)} className={`icon-button ${feedback === true ? 'bg-emerald-100 text-emerald-700' : ''}`}><ThumbsUp size={16} /></button>
      <button disabled={feedback !== null} aria-label="This answer was not useful" onClick={() => sendFeedback(false)} className={`icon-button ${feedback === false ? 'bg-amber-100 text-amber-700' : ''}`}><ThumbsDown size={16} /></button>
    </div>}
    {onFollowUp && !answer.error && <div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Continue exploring</p><div className="mt-2 flex flex-wrap gap-2">{(answer.follow_ups ?? ['Show this as a trend over time.', 'Compare this with another state.']).map((s) => <button key={s} onClick={() => onFollowUp(s)} className="action-button">{s}</button>)}</div></div>}
    <p className="sr-only">Question answered: {question}</p>
  </section>
}

function FriendlyFailure({ error, question, onRetry }: { error?: string | null; question: string; onRetry: () => void }) {
  const lowered = `${error || ''} ${question}`.toLowerCase()
  let title = 'We could not complete that request'
  let message = 'Try asking about one measure, place and time period using one of the available datasets.'
  if (lowered.includes('provider') || lowered.includes('service') || lowered.includes('model')) { title = 'The answer service is temporarily unavailable'; message = 'Your question is safe. Wait a moment and try it again.' }
  else if (lowered.includes('multi') || lowered.includes('more than one dataset') || lowered.includes('forecast')) { title = 'That analysis is not supported yet'; message = 'TanyaDOSM currently answers questions from one curated dataset at a time and does not produce forecasts.' }
  else if (lowered.includes('record') || lowered.includes('match') || lowered.includes('date')) { title = 'No matching official data was found'; message = 'Try a different year, place, or a broader time period.' }
  return <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5" role="alert"><div className="flex gap-3"><AlertCircle className="mt-0.5 shrink-0 text-amber-700" /><div><h3 className="font-semibold text-amber-950">{title}</h3><p className="mt-1 text-sm leading-relaxed text-amber-900">{message}</p></div></div><button onClick={onRetry} className="mt-4 inline-flex items-center gap-2 rounded-xl bg-amber-900 px-3 py-2 text-sm font-semibold text-white"><RefreshCw size={15} /> Edit and try again</button></div>
}

function Timeline({ events }: { events: RunEvent[] }) {
  const nodeEvents = events.filter((event) => event.type.startsWith('node.'))
  if (!nodeEvents.length) return <p className="text-sm text-slate-500">Progress appears here while an answer is prepared.</p>
  const steps = publicSteps.map((step) => {
    const relevant = nodeEvents.filter((event) => event.node && step.nodes.some((node) => node === event.node))
    const completedNodes = new Set(relevant.filter((event) => event.type === 'node.completed').map((event) => event.node))
    const failed = relevant.some((event) => event.type === 'node.failed')
    const completed = !failed && relevant.length > 0 && relevant.every((event) => event.type !== 'node.started' || completedNodes.has(event.node))
    const active = !failed && !completed && relevant.some((event) => event.type === 'node.started')
    return { ...step, failed, completed, active }
  })
  const visible = steps.filter((step, index) => step.completed || step.active || step.failed || steps.slice(index + 1).some((later) => later.completed || later.active || later.failed))
  return <ol className="mt-4 space-y-1">{visible.map((step) => <li key={step.label} className={`flex gap-3 rounded-xl p-3 ${step.active ? 'bg-blue-50' : step.failed ? 'bg-red-50' : ''}`}><span className="mt-0.5" aria-hidden="true">{step.failed ? <AlertCircle size={20} className="text-red-600" /> : step.completed ? <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-600 text-white"><Check size={13} /></span> : step.active ? <LoaderCircle size={20} className="animate-spin text-blue-600" /> : <Circle size={20} className="text-slate-300" />}</span><div><p className="text-sm font-semibold text-slate-800">{step.label}</p><p className="mt-0.5 text-xs text-slate-500">{step.failed ? 'This step could not be completed.' : step.active ? step.description : 'Checked'}</p></div></li>)}</ol>
}

function ProcessDetails({ events, snapshot }: { events: RunEvent[]; snapshot?: RunSnapshot }) {
  const artifacts = useMemo(() => [['Question understood', 'intent'], ['Dataset candidates', 'candidates'], ['Dataset selected', 'selection'], ['Source checked', 'schema'], ['Data request', 'query_plan'], ['Rows retrieved', 'data_summary'], ['Calculation', 'analysis'], ['Result validation', 'validation'], ['Retry', 'retry']] as const, [])
  return <details className="mt-6 rounded-2xl border border-slate-200 bg-white p-4"><summary className="flex cursor-pointer list-none items-center justify-between font-semibold text-slate-800">Why you can trust this answer <ChevronDown size={18} /></summary><p className="mt-2 text-sm text-slate-500">See how your question was matched with checked official data.</p><Timeline events={events} />{(artifacts.some(([, type]) => latestArtifact(events, type)) || snapshot?.answer?.trace) && <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3"><summary className="cursor-pointer text-sm font-semibold text-slate-700">Technical details</summary><p className="mt-2 text-xs text-slate-500">Structured records used to produce the answer. Prompts and private reasoning are never shown.</p><div className="mt-3 space-y-2">{artifacts.map(([label, type]) => { const artifact = latestArtifact(events, type); return artifact ? <details key={type} className="rounded-lg border bg-white p-3"><summary className="cursor-pointer text-xs font-semibold">{label}</summary><pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-slate-600">{JSON.stringify(artifact.payload, null, 2)}</pre></details> : null })}</div></details>}</details>
}

function DatasetGuide({ datasets, loading, onChoose }: { datasets?: DatasetDefinition[]; loading: boolean; onChoose: (question: string) => void }) {
  const [search, setSearch] = useState('')
  const [domain, setDomain] = useState('all')
  const [limit, setLimit] = useState(8)
  const domains = useMemo(() => [...new Set((datasets ?? []).map((dataset) => dataset.domain))].sort(), [datasets])
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (datasets ?? []).filter((dataset) => (domain === 'all' || dataset.domain === domain) && (!needle || [dataset.title, dataset.description, dataset.domain, ...dataset.aliases].join(' ').toLowerCase().includes(needle)))
  }, [datasets, domain, search])
  const examplesById: Record<string, string> = {
    population_malaysia: "What is Malaysia's latest population?",
    population_state: 'Compare the latest population of Johor and Selangor.',
    lfs_month: "How has Malaysia's unemployment rate changed since 2020?",
    lfs_qtr_state: 'Compare unemployment rates in Johor and Selangor.',
    cpi_state_inflation: 'Compare inflation in Johor and Selangor over the latest year.',
  }
  const exampleFor = (dataset: DatasetDefinition) => examplesById[dataset.dataset_id] || `What is the latest figure in ${dataset.title}?`
  return <details className="mt-8 rounded-2xl border border-slate-200 bg-white p-5"><summary className="flex cursor-pointer list-none items-center justify-between gap-4"><span><span className="flex items-center gap-2 font-bold"><Database size={18} className="text-emerald-700" /> What can I ask?</span><span className="mt-1 block text-sm font-normal text-slate-500">Search {datasets?.length ? `${datasets.length} ` : ''}registered official datasets and try a plain-language example.</span></span><ChevronDown className="shrink-0" /></summary>{loading && <p className="mt-4 text-sm text-slate-500">Loading available data…</p>}{!loading && <><div className="mt-5 grid gap-3 sm:grid-cols-[minmax(0,1fr)_14rem]"><label className="relative"><span className="sr-only">Search datasets</span><Search className="pointer-events-none absolute left-3 top-3 text-slate-400" size={17} /><input value={search} onChange={(event) => { setSearch(event.target.value); setLimit(8) }} placeholder="Search population, prices, jobs…" className="w-full rounded-xl border border-slate-300 py-2.5 pl-10 pr-3 text-sm outline-none focus:border-emerald-500" /></label><label><span className="sr-only">Filter by topic</span><select value={domain} onChange={(event) => { setDomain(event.target.value); setLimit(8) }} className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-emerald-500"><option value="all">All topics</option>{domains.map((item) => <option key={item} value={item}>{item.replaceAll('_', ' ')}</option>)}</select></label></div><p className="mt-3 text-xs text-slate-600">Showing {Math.min(filtered.length, limit)} of {filtered.length} matching datasets.</p><div className="mt-4 grid gap-3 sm:grid-cols-2">{filtered.slice(0, limit).map((dataset) => <article key={dataset.dataset_id} className="rounded-xl border border-slate-200 p-4"><h3 className="font-semibold">{dataset.title}</h3><p className="mt-1 text-xs capitalize text-slate-600">{dataset.geography_level} · {dataset.frequency} · {dataset.domain.replaceAll('_', ' ')}</p><p className="mt-2 line-clamp-3 text-sm text-slate-600">{dataset.description}</p><button onClick={() => onChoose(exampleFor(dataset))} className="mt-3 text-left text-sm font-semibold text-emerald-700 hover:underline">Try: “{exampleFor(dataset)}”</button></article>)}</div>{filtered.length === 0 && <p className="mt-5 rounded-xl bg-slate-50 p-4 text-sm text-slate-600">No matching datasets. Try a broader topic such as population, employment, prices, income, or health.</p>}{limit < filtered.length && <button onClick={() => setLimit((current) => current + 8)} className="mt-4 rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:border-emerald-400">Show 8 more</button>}</>}</details>
}

function WorkingState({ snapshot, connected, elapsed, onCancel }: { snapshot: RunSnapshot; connected: boolean; elapsed: number; onCancel: () => void }) {
  const queued = snapshot.status === 'queued'
  return <div className="mt-5 rounded-2xl border border-blue-200 bg-blue-50 p-5" role="status"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-semibold text-blue-950">{queued ? snapshot.queue_position && snapshot.queue_position > 1 ? `Waiting · position ${snapshot.queue_position}` : 'Waiting to start' : nodeLabels[snapshot.current_node || ''] || 'Preparing your answer'}</p><p className="mt-1 text-sm text-blue-800">{elapsed}s elapsed · Progress is saved if you refresh.</p></div>{queued && <button onClick={onCancel} className="rounded-lg border border-blue-300 px-3 py-1.5 text-sm font-semibold text-blue-900">Cancel</button>}</div>{!connected && <p className="mt-3 flex items-center gap-2 text-xs text-amber-800"><RefreshCw size={13} className="animate-spin" /> Reconnecting to live progress. Your request is still running.</p>}</div>
}

export default function App() {
  const queryClient = useQueryClient()
  const sharedRunId = useMemo(() => new URLSearchParams(window.location.search).get('run'), [])
  const [conversationId, setConversationId] = useState<string | null>(() => sharedRunId ? null : localStorage.getItem('tanyadosm-active-conversation'))
  const [selectedId, setSelectedId] = useState<string | null>(sharedRunId)
  const [question, setQuestion] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [stream, dispatch] = useReducer(streamReducer, initialStreamState)
  const [elapsed, setElapsed] = useState(0)
  const endRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const conversations = useQuery({ queryKey: ['conversations'], queryFn: api.listConversations, refetchInterval: 5000, enabled: !sharedRunId })
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30000, retry: false })
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: api.datasets, staleTime: 5 * 60 * 1000 })
  const selected = useQuery({ queryKey: ['run', selectedId], queryFn: () => api.getRun(selectedId!), enabled: !!selectedId, refetchInterval: selectedId ? 1000 : false })
  const conversation = useQuery({ queryKey: ['conversation', conversationId], queryFn: () => api.getConversation(conversationId!), enabled: !!conversationId && !sharedRunId, refetchInterval: conversationId ? 1000 : false, retry: false })

  useEffect(() => { if (conversationId) localStorage.setItem('tanyadosm-active-conversation', conversationId); else localStorage.removeItem('tanyadosm-active-conversation') }, [conversationId])
  useEffect(() => { const latest = conversation.data?.turns.at(-1); if (latest && !selectedId) setSelectedId(latest.id) }, [conversation.data, selectedId])
  useEffect(() => { if (conversation.data?.turns.length) endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [conversation.data?.turns.length])
  useEffect(() => {
    dispatch({ type: 'reset' })
    if (!selectedId) return
    return subscribeToRun(selectedId, (event) => {
      dispatch({ type: 'event', event })
      if (['run.completed', 'run.failed'].includes(event.type)) {
        void queryClient.invalidateQueries({ queryKey: ['run', selectedId] })
        void queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
        void queryClient.invalidateQueries({ queryKey: ['conversations'] })
      }
    }, () => dispatch({ type: 'connected', value: false }), () => dispatch({ type: 'connected', value: true }))
  }, [queryClient, selectedId, conversationId])
  const selectedCreatedAt = selected.data?.created_at
  const selectedStatus = selected.data?.status
  useEffect(() => {
    const started = selectedCreatedAt ? new Date(selectedCreatedAt).valueOf() : Date.now()
    const update = () => setElapsed(Math.max(0, Math.floor((Date.now() - started) / 1000)))
    update()
    if (!selectedStatus || !['queued', 'running'].includes(selectedStatus)) return
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [selectedCreatedAt, selectedStatus])

  const create = useMutation({ mutationFn: (value: string) => api.createRun({ question: value, conversationId }), onSuccess: (run) => { setConversationId(run.conversation_id); setSelectedId(run.id); setQuestion(''); setSidebarOpen(false); void queryClient.invalidateQueries({ queryKey: ['conversations'] }); void queryClient.invalidateQueries({ queryKey: ['conversation', run.conversation_id] }) } })
  const remove = useMutation({ mutationFn: api.deleteRun, onSuccess: (_, id) => { if (selectedId === id) setSelectedId(null); void queryClient.invalidateQueries({ queryKey: ['conversations'] }); void queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] }) } })
  const cancel = useMutation({ mutationFn: api.cancelRun, onSuccess: (run) => { queryClient.setQueryData(['run', run.id], run); void queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] }) } })
  const rename = useMutation({ mutationFn: ({ id, title }: { id: string; title: string }) => api.renameConversation(id, title), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['conversations'] }); void queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] }) } })
  const deleteConversation = useMutation({ mutationFn: api.deleteConversation, onSuccess: (_, id) => { if (conversationId === id) { setConversationId(null); setSelectedId(null) }; void queryClient.invalidateQueries({ queryKey: ['conversations'] }) } })
  const snapshot = selected.data
  const active = snapshot && ['queued', 'running'].includes(snapshot.status)
  const submit = () => { if (question.trim() && !create.isPending) create.mutate(question.trim()) }
  const startNew = () => { window.history.replaceState({}, '', window.location.pathname); setConversationId(null); setSelectedId(null); setQuestion(''); setSidebarOpen(false) }

  return <div className="min-h-screen bg-slate-50 text-slate-900">
    <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 lg:hidden"><button aria-label="Open recent chats" onClick={() => setSidebarOpen(true)}><Menu /></button><span className="font-bold">TanyaDOSM</span><span className="w-6" /></header>
    <div className="grid min-h-screen lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className={`${sidebarOpen ? 'fixed inset-0 z-30 block' : 'hidden'} border-r border-slate-200 bg-slate-950 text-white lg:static lg:block`}><div className="flex h-full flex-col p-5 lg:sticky lg:top-0 lg:h-screen">
        <div className="flex items-center justify-between"><div className="flex items-center gap-3"><BarChart3 className="text-emerald-400" /><div><p className="text-xl font-bold">TanyaDOSM</p><p className="text-xs text-slate-400">Official data, explained</p></div></div><button className="lg:hidden" aria-label="Close recent chats" onClick={() => setSidebarOpen(false)}><X /></button></div>
        <div className="mt-7 space-y-2 text-xs text-slate-400" aria-label="Service availability"><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${health.data?.llm === 'ready' ? 'bg-emerald-400' : 'bg-amber-400'}`} />Answer service: {health.data?.llm === 'ready' ? 'available' : 'limited'}</div><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${health.data?.catalogue === 'ready' ? 'bg-emerald-400' : 'bg-amber-400'}`} />Official data: {health.data?.catalogue === 'ready' ? 'available' : 'limited'}</div><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${health.data?.embeddings === 'ready' ? 'bg-emerald-400' : 'bg-slate-500'}`} />Enhanced search: {health.data?.embeddings === 'ready' ? 'available' : 'using standard search'}</div></div>
        <button onClick={startNew} className="mt-7 rounded-xl bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950">New chat</button>
        {!sharedRunId && <><h2 className="mt-8 flex items-center gap-2 text-sm font-semibold text-slate-300"><Clock3 size={16} /> Recent chats</h2><nav className="mt-3 flex-1 space-y-2 overflow-y-auto" aria-label="Recent chats">{conversations.data?.map((chat) => <div key={chat.id} className={`group rounded-xl ${conversationId === chat.id ? 'bg-slate-800' : 'hover:bg-slate-900'}`}><button onClick={() => { setConversationId(chat.id); setSelectedId(null); setSidebarOpen(false) }} className="w-full p-3 text-left text-sm"><div className="line-clamp-2 pr-10">{chat.title}</div><div className="mt-2 flex items-center justify-between"><StatusPill status={chat.latest_status} /><span className="text-xs text-slate-400">{formatChatDate(chat.updated_at)} · {chat.turn_count} {chat.turn_count === 1 ? 'turn' : 'turns'}</span></div></button><div className="-mt-11 mb-2 mr-2 flex justify-end gap-1 opacity-100 lg:opacity-0 lg:group-hover:opacity-100"><button aria-label={`Rename ${chat.title}`} onClick={() => { const title = window.prompt('Rename this chat', chat.title)?.trim(); if (title) rename.mutate({ id: chat.id, title }) }} className="rounded p-1.5 text-slate-400 hover:bg-slate-700 hover:text-white"><Pencil size={14} /></button><button aria-label={`Delete ${chat.title}`} onClick={() => { if (window.confirm('Delete this chat and all its turns?')) deleteConversation.mutate(chat.id) }} className="rounded p-1.5 text-slate-400 hover:bg-red-950 hover:text-red-300"><Trash2 size={14} /></button></div></div>)}{!conversations.data?.length && <p className="py-4 text-sm text-slate-500">No chats yet.</p>}</nav><p className="mt-4 text-xs leading-relaxed text-slate-400">Chats expire after seven days. Each question is answered independently from official data.</p></>}
      </div></aside>
      <main className="min-w-0 p-5 md:p-8"><div className="mx-auto max-w-5xl">
        <div className="mb-8"><p className="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-700">Malaysian public statistics</p><h1 className="mt-2 text-3xl font-bold md:text-4xl">{sharedRunId ? 'Shared official-data result' : 'Ask the data. Get a clear answer.'}</h1><p className="mt-3 text-slate-600">Ask in English or Bahasa Melayu about population, employment, prices, income, health, and other registered official statistics.</p></div>
        {conversation.isError && !sharedRunId && <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5"><h3 className="font-semibold">This chat is no longer available</h3><p className="mt-1 text-sm text-slate-600">Chats expire after seven days. Start a new chat to continue.</p><button onClick={startNew} className="mt-3 rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white">Start new chat</button></div>}
        {sharedRunId && selected.isLoading && <p className="text-sm text-slate-500">Loading shared result…</p>}
        {sharedRunId && selected.isError && <FriendlyFailure error="This shared result was not found or has expired." question="" onRetry={startNew} />}
        {sharedRunId && snapshot && <article className="rounded-2xl border border-slate-200 bg-white p-5"><div className="mb-4 rounded-xl bg-slate-100 p-4 text-slate-800"><span className="text-xs font-semibold uppercase text-slate-500">Question</span><p className="mt-1">{snapshot.question}</p></div>{snapshot.answer && !snapshot.answer.error ? <Results answer={snapshot.answer} runId={snapshot.id} question={snapshot.question} /> : <FriendlyFailure error={snapshot.answer?.error || snapshot.error} question={snapshot.question} onRetry={startNew} />}</article>}
        {!sharedRunId && conversation.data?.turns.map((turn) => <div key={turn.id} className="mb-6 space-y-3"><div className="ml-auto max-w-2xl rounded-2xl bg-slate-900 p-4 text-white">{turn.question}</div><article className={`rounded-2xl border bg-white p-4 sm:p-5 ${selectedId === turn.id ? 'border-emerald-400 shadow-sm' : 'border-slate-200'}`}><button onClick={() => setSelectedId(turn.id)} className="mb-4 flex w-full items-center justify-between text-left"><StatusPill status={turn.status} /><span className="text-xs font-medium text-slate-600">Why you can trust this</span></button>{turn.answer && !turn.answer.error ? <Results answer={turn.answer} runId={turn.id} question={turn.question} onFollowUp={(value) => { setQuestion(value); textareaRef.current?.focus() }} /> : turn.answer?.error || ['failed', 'interrupted'].includes(turn.status) ? <FriendlyFailure error={turn.answer?.error || turn.error} question={turn.question} onRetry={() => { setQuestion(turn.question); textareaRef.current?.focus() }} /> : <p className="text-sm text-slate-500">Preparing this answer…</p>}{['completed', 'failed', 'interrupted'].includes(turn.status) && <button aria-label="Delete this turn" onClick={() => { if (window.confirm('Delete this turn?')) remove.mutate(turn.id) }} className="mt-4 text-xs text-slate-500 hover:text-red-600"><Trash2 className="inline" size={13} /> Delete turn</button>}</article></div>)}
        {!sharedRunId && <><form className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm" onSubmit={(event) => { event.preventDefault(); submit() }}><label htmlFor="question" className="sr-only">Question</label><textarea ref={textareaRef} id="question" value={question} maxLength={500} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit() } }} placeholder={conversationId ? 'Ask another question…' : 'What would you like to know?'} className="min-h-24 w-full resize-none p-3 outline-none" /><div className="flex items-center justify-between border-t border-slate-100 pt-3"><span className="text-xs text-slate-600">Enter to ask · Shift+Enter for a new line · {question.length}/500</span><button disabled={!question.trim() || create.isPending} className="flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 font-semibold text-white disabled:opacity-40"><Send size={16} />{create.isPending ? 'Submitting…' : 'Ask'}</button></div></form>{create.error && <FriendlyFailure error={create.error.message} question={question} onRetry={() => textareaRef.current?.focus()} />}{!conversationId && <section className="mt-8"><h2 className="text-sm font-semibold text-slate-600">Start with a common task</h2><div className="mt-3 grid gap-3 sm:grid-cols-2">{examples.map((example) => <button key={example.label} onClick={() => { setQuestion(example.question); textareaRef.current?.focus() }} className="rounded-xl border border-slate-200 bg-white p-4 text-left hover:border-emerald-400"><span className="flex items-center gap-2 text-sm font-semibold text-emerald-800"><FileQuestion size={16} />{example.label}</span><span className="mt-2 block text-sm text-slate-600">{example.question}</span></button>)}</div></section>}{active && <WorkingState snapshot={snapshot} connected={stream.connected} elapsed={elapsed} onCancel={() => { if (window.confirm('Cancel this queued request?')) cancel.mutate(snapshot.id) }} />}{snapshot && <ProcessDetails events={stream.events} snapshot={snapshot} />}<DatasetGuide datasets={datasets.data} loading={datasets.isLoading} onChoose={(value) => { setQuestion(value); textareaRef.current?.focus() }} /></>}
        <div ref={endRef} />
      </div></main>
    </div>
  </div>
}
