import { useEffect, useMemo, useReducer, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, BarChart3, Clock3, Database, ExternalLink, Menu, Send, Trash2, X } from 'lucide-react'
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
  if (!nodeEvents.length) return <p className="text-sm text-slate-500">Execution details will appear here.</p>
  return <ol className="space-y-3">{nodeEvents.map((event) => (
    <li key={event.sequence} className="flex gap-3 text-sm">
      <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${event.type === 'node.failed' ? 'bg-red-500' : event.type === 'node.completed' ? 'bg-emerald-500' : 'animate-pulse bg-blue-500'}`} />
      <div><p className="font-medium text-slate-800">{nodeLabels[event.node || ''] || event.node}</p><p className="text-xs text-slate-500">{event.type.split('.')[1]}{event.duration_ms != null ? ` · ${Math.round(event.duration_ms)} ms` : ''}</p></div>
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
      <div><h2 className="flex items-center gap-2 font-bold"><Activity size={18} /> Execution</h2><p className="mt-1 text-xs text-slate-500">Sanitized workflow state—no hidden prompts or reasoning.</p></div>
      <Timeline events={events} />
      <div className="space-y-2">
        {artifacts.map(([label, type]) => {
          const artifact = latestArtifact(events, type)
          if (!artifact) return null
          return <details key={type} className="rounded-xl border border-slate-200 p-3"><summary className="cursor-pointer text-sm font-semibold">{label}</summary><pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-slate-600">{JSON.stringify(artifact.payload, null, 2)}</pre></details>
        })}
        {snapshot?.answer?.trace && <details className="rounded-xl border border-slate-200 p-3"><summary className="cursor-pointer text-sm font-semibold">Final execution trace</summary><pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-slate-600">{JSON.stringify(snapshot.answer.trace, null, 2)}</pre></details>}
      </div>
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
  const [selectedId, setSelectedId] = useState<string | null>(() => localStorage.getItem('tanyadosm-active-run'))
  const [question, setQuestion] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [stream, dispatch] = useReducer(streamReducer, initialStreamState)
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.listRuns, refetchInterval: 5000 })
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 30000, retry: false })
  const datasets = useQuery({ queryKey: ['datasets'], queryFn: api.datasets, staleTime: 5 * 60 * 1000 })
  const catalogueMonitor = useQuery({ queryKey: ['catalogue-monitor'], queryFn: api.catalogueMonitor, refetchInterval: 60 * 1000 })
  const selected = useQuery({ queryKey: ['run', selectedId], queryFn: () => api.getRun(selectedId!), enabled: !!selectedId, refetchInterval: selectedId ? 1000 : false })

  useEffect(() => {
    if (selectedId) localStorage.setItem('tanyadosm-active-run', selectedId)
    else localStorage.removeItem('tanyadosm-active-run')
  }, [selectedId])

  useEffect(() => {
    dispatch({ type: 'reset' })
    if (!selectedId) return
    return subscribeToRun(selectedId, (event) => {
      dispatch({ type: 'event', event })
      if (['run.completed', 'run.failed'].includes(event.type)) {
        void queryClient.invalidateQueries({ queryKey: ['run', selectedId] })
        void queryClient.invalidateQueries({ queryKey: ['runs'] })
      }
    }, () => dispatch({ type: 'connected', value: false }))
  }, [queryClient, selectedId])

  const create = useMutation({
    mutationFn: api.createRun,
    onSuccess: (run) => {
      setSelectedId(run.id); setQuestion(''); setSidebarOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
    },
  })
  const remove = useMutation({ mutationFn: api.deleteRun, onSuccess: (_, id) => {
    if (selectedId === id) setSelectedId(null)
    void queryClient.invalidateQueries({ queryKey: ['runs'] })
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
            <div className="mt-7 flex items-center gap-2 text-xs text-slate-400"><span className={`h-2 w-2 rounded-full ${health.data?.ollama === 'ready' ? 'bg-emerald-400' : 'bg-amber-400'}`} />Ollama {health.data?.ollama || 'checking'}</div>
            <h2 className="mt-8 flex items-center gap-2 text-sm font-semibold text-slate-300"><Clock3 size={16} /> Recent runs</h2>
            <nav className="mt-3 flex-1 space-y-2 overflow-y-auto" aria-label="Recent runs">
              {runs.data?.map((run) => <button key={run.id} onClick={() => { setSelectedId(run.id); setSidebarOpen(false) }} className={`group w-full rounded-xl p-3 text-left text-sm ${selectedId === run.id ? 'bg-slate-800' : 'hover:bg-slate-900'}`}><div className="line-clamp-2">{run.question}</div><div className="mt-2 flex items-center justify-between"><StatusPill status={run.status} />{['completed', 'failed', 'interrupted'].includes(run.status) && <span role="button" tabIndex={0} aria-label="Delete run" onClick={(event) => { event.stopPropagation(); remove.mutate(run.id) }} onKeyDown={(event) => { if (event.key === 'Enter') remove.mutate(run.id) }} className="rounded p-1 opacity-0 hover:bg-slate-700 group-hover:opacity-100 focus:opacity-100"><Trash2 size={14} /></span>}</div></button>)}
              {!runs.data?.length && <p className="py-4 text-sm text-slate-500">No runs yet.</p>}
            </nav>
            <p className="mt-4 text-xs leading-relaxed text-slate-500">Runs expire after seven days. Every question is analyzed independently.</p>
          </div>
        </aside>

        <main className="min-w-0 p-5 md:p-8">
          <div className="mx-auto max-w-4xl">
            <div className="mb-8"><p className="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-700">Malaysian public statistics</p><h2 className="mt-2 text-3xl font-bold md:text-4xl">Ask the data. See the process.</h2><p className="mt-3 text-slate-600">Ask in English or Bahasa Melayu. Results come from five curated official datasets.</p></div>
            <form className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm" onSubmit={(event) => { event.preventDefault(); if (question.trim()) create.mutate(question.trim()) }}>
              <label htmlFor="question" className="sr-only">Question</label><textarea id="question" value={question} maxLength={500} onChange={(event) => setQuestion(event.target.value)} placeholder="What would you like to know?" className="min-h-24 w-full resize-none p-3 outline-none" />
              <div className="flex items-center justify-between border-t border-slate-100 pt-3"><span className="text-xs text-slate-400">{question.length}/500</span><button disabled={!question.trim() || create.isPending} className="flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 font-semibold text-white disabled:opacity-40"><Send size={16} />{create.isPending ? 'Submitting…' : 'Ask'}</button></div>
            </form>
            {create.error && <p className="mt-3 text-sm text-red-700">{create.error.message}</p>}
            {!selectedId && <div className="mt-8"><h3 className="text-sm font-semibold text-slate-600">Try an example</h3><div className="mt-3 grid gap-3 sm:grid-cols-2">{examples.map((example) => <button key={example} onClick={() => setQuestion(example)} className="rounded-xl border border-slate-200 bg-white p-4 text-left text-sm hover:border-emerald-400">{example}</button>)}</div></div>}
            {selectedId && <div className="mt-8 space-y-5"><div className="flex flex-wrap items-center gap-3"><StatusPill status={snapshot?.status || 'queued'} /><p className="font-medium">{snapshot?.question}</p></div>{active && <div className="rounded-2xl border border-blue-200 bg-blue-50 p-5"><p className="font-semibold text-blue-900">{snapshot.status === 'queued' ? 'Waiting for the model…' : `Processing: ${nodeLabels[snapshot.current_node || ''] || snapshot.current_node || 'starting'}`}</p><p className="mt-1 text-sm text-blue-700">Progress is saved and can be recovered after a refresh.</p></div>}{snapshot?.error && <div className="rounded-2xl border border-red-200 bg-red-50 p-5 text-red-800">{snapshot.error}</div>}{snapshot?.answer && <Results answer={snapshot.answer} />}</div>}
            <DatasetCatalogue datasets={datasets.data} monitor={catalogueMonitor.data} loading={datasets.isLoading} />
          </div>
        </main>
        <Inspector events={stream.events} snapshot={snapshot} />
      </div>
    </div>
  )
}
