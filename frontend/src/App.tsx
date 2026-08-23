import { useEffect, useMemo, useReducer, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, BarChart3, Check, Circle, Clock3, Database, ExternalLink, LoaderCircle, Menu, Send, Trash2, X } from 'lucide-react'
import { api, subscribeToRun } from './api'
import { ResultChart } from './Chart'
import { initialStreamState, latestArtifact, streamReducer } from './runState'
import type { AnswerPayload, CatalogueMonitorState, DatasetDefinition, RunEvent, RunSnapshot, RunStatus } from './types'

const examples = [
  "What is Malaysia's latest population?",
  'Compare Johor and Selangor population in 2025.',
  'Show unemployment trends in Johor since 2020.',
  'Negeri mana mempunyai penduduk paling ramai pada tahun 2025?',
]

const nodeLabels: Record<string, string> = {
  parse_question: 'Understand question', search_catalogue: 'Search catalogue', select_dataset: 'Select dataset',
  inspect_schema: 'Inspect source schema', build_query_plan: 'Build query plan', execute_query: 'Retrieve rows',
  analyze_result: 'Calculate result', validate_result: 'Validate facts', generate_visualization: 'Choose visualization',
  generate_response: 'Prepare answer', graceful_failure: 'Prepare safe response',
}

const publicSteps = [
  { label: 'Understanding your question', description: 'Identifying the topic, place and time period you asked about.', nodes: ['parse_question'] },
  { label: 'Finding the right official data', description: 'Matching your question with the most relevant DOSM dataset.', nodes: ['search_catalogue', 'select_dataset'] },
  { label: 'Checking the source', description: 'Confirming the available fields and freshness of the data.', nodes: ['inspect_schema'] },
  { label: 'Working out the answer', description: 'Retrieving the relevant figures, calculating and checking the result.', nodes: ['build_query_plan', 'execute_query', 'analyze_result', 'validate_result'] },
  { label: 'Preparing your result', description: 'Presenting the answer clearly with a useful chart when appropriate.', nodes: ['generate_visualization', 'generate_response', 'graceful_failure'] },
] as const

function StatusPill({ status }: { status: RunStatus }) {
  const colors: Record<RunStatus, string> = {
    queued: 'bg-amber-100 text-amber-800', running: 'bg-blue-100 text-blue-800',
    completed: 'bg-emerald-100 text-emerald-800', failed: 'bg-red-100 text-red-800',
    interrupted: 'bg-slate-200 text-slate-700',
  }
  return <span className={`rounded-full px-2 py-1 text-xs font-semibold ${colors[status]}`}>{status}</span>
}

function Results({ answer }: { answer: AnswerPayload }) {
  const columns = answer.table_rows.length ? Object.keys(answer.table_rows[0]) : []
  return (
    <section className="space-y-5" aria-live="polite">
      <div className={`rounded-2xl border p-5 ${answer.error ? 'border-amber-200 bg-amber-50' : 'border-emerald-200 bg-emerald-50'}`}>
        <p className="text-lg leading-relaxed text-slate-900">{answer.answer}</p>
      </div>
      <ResultChart answer={answer} />
      {answer.table_rows.length > 0 && (
        <div className="overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50"><tr>{columns.map((column) => <th key={column} className="px-4 py-3 text-left font-semibold">{column.replaceAll('_', ' ')}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100">{answer.table_rows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column} className="whitespace-nowrap px-4 py-3">{String(row[column] ?? '')}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
      {answer.source && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 text-sm text-slate-600">
          <div className="mb-2 flex items-center gap-2 font-semibold text-slate-800"><Database size={16} /> Official source</div>
          <a className="text-blue-700 underline" href={answer.source.url} target="_blank" rel="noreferrer">{answer.source.title}</a>
          <p>{answer.source.agency} · Period: {answer.source.period || 'Not applicable'} · Unit: {answer.source.unit}</p>
          <p>Data cache: {answer.source.cache_freshness || 'Unknown'} · {answer.trace.calculation ? 'Calculated' : 'Retrieved'}</p>
        </div>
      )}
    </section>
  )
}

function Timeline({ events }: { events: RunEvent[] }) {
  const nodeEvents = events.filter((event) => event.type.startsWith('node.'))
  if (!nodeEvents.length) return <p className="text-sm text-slate-500">Your progress will appear here after you ask a question.</p>

  const steps = publicSteps.map((step) => {
    const relevant = nodeEvents.filter((event) => event.node && step.nodes.some((node) => node === event.node))
    const completedNodes = new Set(relevant.filter((event) => event.type === 'node.completed').map((event) => event.node))
    const failed = relevant.some((event) => event.type === 'node.failed')
    const completed = !failed && relevant.length > 0 && relevant.every((event) => event.type !== 'node.started' || completedNodes.has(event.node))
    const active = !failed && !completed && relevant.some((event) => event.type === 'node.started')
    const duration = relevant.reduce((total, event) => total + (event.type === 'node.completed' ? event.duration_ms || 0 : 0), 0)
    return { ...step, failed, completed, active, duration }
  })
  const visibleSteps = steps.filter((step, index) => step.completed || step.active || step.failed || steps.slice(index + 1).some((later) => later.completed || later.active || later.failed))

  return <ol className="space-y-1">{visibleSteps.map((step) => (
    <li key={step.label} className={`flex gap-3 rounded-xl p-3 ${step.active ? 'bg-blue-50' : step.failed ? 'bg-red-50' : ''}`}>
      <span className="mt-0.5 shrink-0" aria-hidden="true">
        {step.failed ? <AlertCircle size={20} className="text-red-600" /> : step.completed ? <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-600 text-white"><Check size={13} strokeWidth={3} /></span> : step.active ? <LoaderCircle size={20} className="animate-spin text-blue-600" /> : <Circle size={20} className="text-slate-300" />}
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2"><p className="text-sm font-semibold text-slate-800">{step.label}</p>{step.completed && step.duration > 0 && <span className="text-xs text-slate-400">{step.duration < 1000 ? `${Math.round(step.duration)} ms` : `${(step.duration / 1000).toFixed(1)} sec`}</span>}</div>
        <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{step.failed ? 'We could not complete this step.' : step.active ? step.description : 'Done'}</p>
      </div>
    </li>
  ))}</ol>
}

function Inspector({ events, snapshot }: { events: RunEvent[]; snapshot?: RunSnapshot }) {
  const artifacts = useMemo(() => [
    ['Normalized intent', 'intent'], ['Dataset candidates', 'candidates'], ['Dataset selection', 'selection'],
    ['Schema and cache', 'schema'], ['Sanitized query plan', 'query_plan'], ['Rows retrieved', 'data_summary'],
    ['Deterministic analysis', 'analysis'], ['Validation', 'validation'], ['Retry', 'retry'],
  ] as const, [])
  return (
    <aside className="space-y-5 border-l border-slate-200 bg-white p-5 lg:h-screen lg:overflow-y-auto">
      <div><h2 className="font-bold">How we found your answer</h2><p className="mt-1 text-sm leading-relaxed text-slate-500">Follow the steps from your question to verified official data.</p></div>
      <Timeline events={events} />
      {(artifacts.some(([, type]) => latestArtifact(events, type)) || snapshot?.answer?.trace) && <details className="rounded-xl border border-slate-200 bg-slate-50 p-3">
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">View technical details</summary>
        <p className="mt-2 text-xs leading-relaxed text-slate-500">For advanced users: structured data used to produce and verify this answer. Prompts and private reasoning are never shown.</p>
        <div className="mt-3 space-y-2">
          {artifacts.map(([label, type]) => {
            const artifact = latestArtifact(events, type)
            if (!artifact) return null
            return <details key={type} className="rounded-lg border border-slate-200 bg-white p-3"><summary className="cursor-pointer text-xs font-semibold">{label}</summary><pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-slate-600">{JSON.stringify(artifact.payload, null, 2)}</pre></details>
          })}
          {snapshot?.answer?.trace && <details className="rounded-lg border border-slate-200 bg-white p-3"><summary className="cursor-pointer text-xs font-semibold">Complete processing record</summary><pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-slate-600">{JSON.stringify(snapshot.answer.trace, null, 2)}</pre></details>}
        </div>
      </details>}
    </aside>
  )
}

function DatasetCatalogue({ datasets, monitor, loading }: { datasets?: DatasetDefinition[]; monitor?: CatalogueMonitorState; loading: boolean }) {
  return (
    <section className="mt-8" aria-labelledby="available-datasets-heading">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h3 id="available-datasets-heading" className="flex items-center gap-2 text-lg font-bold text-slate-900">
            <Database size={19} className="text-emerald-700" /> Available datasets
          </h3>
          <p className="mt-1 text-sm text-slate-600">Ask questions using the measures and geographic coverage below.</p>
        </div>
        {datasets && <span className="shrink-0 rounded-full bg-slate-200 px-2.5 py-1 text-xs font-semibold text-slate-700">{datasets.length} datasets</span>}
      </div>
      {loading && <p className="mt-4 text-sm text-slate-500">Loading dataset catalogue…</p>}
      {datasets && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {datasets.map((dataset) => (
            <article key={dataset.dataset_id} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h4 className="font-semibold leading-snug text-slate-900">{dataset.title}</h4>
                  <p className="mt-1 text-xs capitalize text-slate-500">{dataset.geography_level} · {dataset.frequency}</p>
                </div>
                <a href={dataset.source_url} target="_blank" rel="noreferrer" aria-label={`Open source for ${dataset.title}`} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-emerald-700">
                  <ExternalLink size={16} />
                </a>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-slate-600">{dataset.description}</p>
              <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Available measures">
                {dataset.measures.map((measure) => (
                  <span key={measure.name} className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800">
                    {measure.name.replaceAll('_', ' ')} <span className="font-normal text-emerald-600">({measure.unit})</span>
                  </span>
                ))}
              </div>
              {monitor?.registered[dataset.dataset_id] && (
                <p className={`mt-3 text-xs ${monitor.registered[dataset.dataset_id].status === 'error' ? 'text-red-700' : 'text-slate-500'}`}>
                  Monitor: {monitor.registered[dataset.dataset_id].status}
                  {monitor.registered[dataset.dataset_id].last_checked && ` · checked ${new Date(monitor.registered[dataset.dataset_id].last_checked!).toLocaleString()}`}
                </p>
              )}
            </article>
          ))}
        </div>
      )}
      {monitor?.discovered.length ? (
        <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4">
          <h4 className="font-semibold text-amber-900">New DOSM datasets awaiting review</h4>
          <ul className="mt-2 space-y-1 text-sm text-amber-800">
            {monitor.discovered.map((dataset) => (
              <li key={dataset.dataset_id}>
                {dataset.source_url ? <a className="underline" href={dataset.source_url} target="_blank" rel="noreferrer">{dataset.title || dataset.dataset_id}</a> : dataset.title || dataset.dataset_id}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}

export default function App() {
  const queryClient = useQueryClient()
  const [conversationId, setConversationId] = useState<string | null>(() => localStorage.getItem('tanyadosm-active-conversation'))
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [stream, dispatch] = useReducer(streamReducer, initialStreamState)
  const conversations = useQuery({ queryKey: ['conversations'], queryFn: api.listConversations, refetchInterval: 5000 })
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30000, retry: false })
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: api.datasets, staleTime: 5 * 60 * 1000 })
  const catalogueMonitor = useQuery({ queryKey: ['catalogue-monitor'], queryFn: api.catalogueMonitor, refetchInterval: 60 * 1000 })
  const selected = useQuery({ queryKey: ['run', selectedId], queryFn: () => api.getRun(selectedId!), enabled: !!selectedId, refetchInterval: selectedId ? 1000 : false })
  const conversation = useQuery({ queryKey: ['conversation', conversationId], queryFn: () => api.getConversation(conversationId!), enabled: !!conversationId, refetchInterval: conversationId ? 1000 : false })

  useEffect(() => {
    if (conversationId) localStorage.setItem('tanyadosm-active-conversation', conversationId)
    else localStorage.removeItem('tanyadosm-active-conversation')
  }, [conversationId])

  useEffect(() => {
    const latest = conversation.data?.turns.at(-1)
    if (latest && !selectedId) setSelectedId(latest.id)
  }, [conversation.data, selectedId])

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
    }, () => dispatch({ type: 'connected', value: false }))
  }, [queryClient, selectedId, conversationId])

  const create = useMutation({
    mutationFn: (value: string) => api.createRun({ question: value, conversationId }),
    onSuccess: (run) => {
      setConversationId(run.conversation_id); setSelectedId(run.id); setQuestion(''); setSidebarOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['conversations'] })
      void queryClient.invalidateQueries({ queryKey: ['conversation', run.conversation_id] })
    },
  })
  const remove = useMutation({ mutationFn: api.deleteRun, onSuccess: (_, id) => {
    if (selectedId === id) setSelectedId(null)
    void queryClient.invalidateQueries({ queryKey: ['conversations'] })
    void queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
  } })
  const snapshot = selected.data
  const active = snapshot && ['queued', 'running'].includes(snapshot.status)

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white px-4 py-3 lg:hidden"><button aria-label="Open recent runs" onClick={() => setSidebarOpen(true)}><Menu /></button></header>
      <div className="grid min-h-screen lg:grid-cols-[280px_minmax(0,1fr)_360px]">
        <aside className={`${sidebarOpen ? 'fixed inset-0 z-30 block' : 'hidden'} border-r border-slate-200 bg-slate-950 text-white lg:static lg:block`}>
          <div className="flex h-full flex-col p-5">
            <div className="flex items-center justify-between"><div className="flex items-center gap-3"><BarChart3 className="text-emerald-400" /><div><h1 className="text-xl font-bold">TanyaDOSM</h1><p className="text-xs text-slate-400">Official data, explained</p></div></div><button className="lg:hidden" aria-label="Close recent runs" onClick={() => setSidebarOpen(false)}><X /></button></div>
            <div className="mt-7 space-y-2 text-xs text-slate-400" aria-label="AI provider status">
              <div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${health.data?.llm === 'ready' ? 'bg-emerald-400' : 'bg-amber-400'}`} />Groq {health.data?.llm || 'checking'}</div>
              <div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${health.data?.embeddings === 'ready' ? 'bg-emerald-400' : 'bg-amber-400'}`} />Cloudflare {health.data?.embeddings || 'checking'}</div>
            </div>
            <button onClick={() => { setConversationId(null); setSelectedId(null); setQuestion(''); setSidebarOpen(false) }} className="mt-7 rounded-xl bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950">New chat</button>
            <h2 className="mt-8 flex items-center gap-2 text-sm font-semibold text-slate-300"><Clock3 size={16} /> Recent chats</h2>
            <nav className="mt-3 flex-1 space-y-2 overflow-y-auto" aria-label="Recent chats">
              {conversations.data?.map((chat) => <button key={chat.id} onClick={() => { setConversationId(chat.id); setSelectedId(null); setSidebarOpen(false) }} className={`w-full rounded-xl p-3 text-left text-sm ${conversationId === chat.id ? 'bg-slate-800' : 'hover:bg-slate-900'}`}><div className="line-clamp-2">{chat.title}</div><div className="mt-2 flex items-center justify-between"><StatusPill status={chat.latest_status} /><span className="text-xs text-slate-500">{chat.turn_count} {chat.turn_count === 1 ? 'turn' : 'turns'}</span></div></button>)}
              {!conversations.data?.length && <p className="py-4 text-sm text-slate-500">No chats yet.</p>}
            </nav>
            <p className="mt-4 text-xs leading-relaxed text-slate-500">Chats expire after seven days. Follow-ups use recent verified answers as context.</p>
          </div>
        </aside>

        <main className="min-w-0 p-5 md:p-8">
          <div className="mx-auto max-w-4xl">
            <div className="mb-8"><p className="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-700">Malaysian public statistics</p><h2 className="mt-2 text-3xl font-bold md:text-4xl">Ask the data. See the process.</h2><p className="mt-3 text-slate-600">Ask in English or Bahasa Melayu. Results come from five curated official datasets.</p></div>
            {conversation.data?.turns.map((turn) => <div key={turn.id} className="mb-6 space-y-3"><div className="ml-auto max-w-2xl rounded-2xl bg-slate-900 p-4 text-white">{turn.question}</div><div className={`rounded-2xl border bg-white p-5 ${selectedId === turn.id ? 'border-emerald-400' : 'border-slate-200'}`}><button onClick={() => setSelectedId(turn.id)} className="mb-3 flex w-full items-center justify-between text-left"><StatusPill status={turn.status} /><span className="text-xs text-slate-400">Inspect this turn</span></button>{turn.answer ? <Results answer={turn.answer} /> : <p className="text-sm text-slate-500">{turn.error || 'Processing this turn…'}</p>}{['completed', 'failed', 'interrupted'].includes(turn.status) && <button aria-label="Delete run" onClick={() => remove.mutate(turn.id)} className="mt-3 text-xs text-slate-400 hover:text-red-600"><Trash2 className="inline" size={13} /> Delete turn</button>}</div></div>)}
            <form className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm" onSubmit={(event) => { event.preventDefault(); if (question.trim()) create.mutate(question.trim()) }}>
              <label htmlFor="question" className="sr-only">Question</label><textarea id="question" value={question} maxLength={500} onChange={(event) => setQuestion(event.target.value)} placeholder={conversationId ? 'Ask a follow-up…' : 'What would you like to know?'} className="min-h-24 w-full resize-none p-3 outline-none" />
              <div className="flex items-center justify-between border-t border-slate-100 pt-3"><span className="text-xs text-slate-400">{question.length}/500</span><button disabled={!question.trim() || create.isPending} className="flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 font-semibold text-white disabled:opacity-40"><Send size={16} />{create.isPending ? 'Submitting…' : 'Ask'}</button></div>
            </form>
            {create.error && <p className="mt-3 text-sm text-red-700">{create.error.message}</p>}
            {!conversationId && <div className="mt-8"><h3 className="text-sm font-semibold text-slate-600">Try an example</h3><div className="mt-3 grid gap-3 sm:grid-cols-2">{examples.map((example) => <button key={example} onClick={() => setQuestion(example)} className="rounded-xl border border-slate-200 bg-white p-4 text-left text-sm hover:border-emerald-400">{example}</button>)}</div></div>}
            {active && <div className="mt-5 rounded-2xl border border-blue-200 bg-blue-50 p-5"><p className="font-semibold text-blue-900">{snapshot.status === 'queued' ? 'Waiting for the model…' : `Processing: ${nodeLabels[snapshot.current_node || ''] || snapshot.current_node || 'starting'}`}</p><p className="mt-1 text-sm text-blue-700">Progress is saved and can be recovered after a refresh.</p></div>}
            <DatasetCatalogue datasets={datasets.data} monitor={catalogueMonitor.data} loading={datasets.isLoading} />
          </div>
        </main>
        <Inspector events={stream.events} snapshot={snapshot} />
      </div>
    </div>
  )
}
