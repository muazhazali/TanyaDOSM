import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { AnswerPayload } from './types'

const PALETTE = ['#10b981', '#3b82f6', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#f43f5e', '#6366f1']
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })
const full = new Intl.NumberFormat('en-MY', { maximumFractionDigits: 4 })

const toNum = (value: unknown): number | null => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  const n = Number(String(value ?? '').replace(/,/g, ''))
  return Number.isFinite(n) ? n : null
}
const toLabel = (value: unknown): string => (typeof value === 'string' ? value : String(value ?? ''))
const truncate = (label: string, max = 22): string => (label.length > max ? `${label.slice(0, max - 1)}…` : label)

type TooltipEntry = { name?: string; value?: number | string; color?: string }

function ChartTooltip({
  active,
  payload,
  label,
  unit,
  horizontal,
}: {
  active?: boolean
  payload?: TooltipEntry[]
  label?: unknown
  unit?: string
  horizontal?: boolean
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xl border border-slate-200 bg-white/95 px-3 py-2 shadow-lg backdrop-blur">
      {!horizontal && (
        <p className="mb-1 max-w-[280px] text-[11px] font-medium text-slate-500">{truncate(toLabel(label), 48)}</p>
      )}
      <div className="flex flex-col gap-1">
        {payload.map((entry, index) => (
          <div key={entry.name ?? index} className="flex items-center gap-2">
            {horizontal && (
              <span className="max-w-[220px] truncate text-xs font-medium text-slate-700">{toLabel(label)}</span>
            )}
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: entry.color ?? '#10b981' }} />
            <span className="text-xs font-semibold text-slate-900">
              {typeof entry.value === 'number' ? full.format(entry.value) : String(entry.value)}
            </span>
            {unit && <span className="text-[11px] text-slate-400">{unit}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

export type ChartKindOverride = 'bar' | 'line' | 'ranking_bar' | null

const TICK = { fill: '#64748b', fontSize: 11 }

export function ResultChart({ answer, kindOverride }: { answer: AnswerPayload; kindOverride?: ChartKindOverride }) {
  const { visualization: spec, table_rows: rows } = answer
  if (rows.length <= 1 || ['none', 'table'].includes(spec.kind) || !spec.x || !spec.y) return null

  // Backend convention (src/askdosm/visualization.py): ranking_bar sets x=value,
  // y=category; bar/line set x=category, y=value. Resolve keys from the spec's own
  // convention so overrides only change rendering, never the data mapping.
  const rankedBySpec = spec.kind === 'ranking_bar'
  const effectiveKind = kindOverride ?? spec.kind
  const categoryKey = rankedBySpec ? spec.y! : spec.x!
  const valueKey = rankedBySpec ? spec.x! : spec.y!
  const ranking = effectiveKind === 'ranking_bar'
  const isLine = effectiveKind === 'line'

  const unit = answer.source?.unit ?? ''
  const categoryTitle = categoryKey.replaceAll('_', ' ')
  const metricName = valueKey.replaceAll('_', ' ')
  const metricTitle = `${metricName}${unit ? ` (${unit})` : ''}`

  const valueOf = (row: Record<string, unknown>): number | null => toNum(row[valueKey])

  let seriesNames: string[] = []
  let chart: React.ReactNode

  if (isLine) {
    const useColor = Boolean(spec.color)
    seriesNames = useColor
      ? [...new Set(rows.map((row) => String(row[spec.color!] ?? 'Series')))]
      : [metricName]
    const byX = new Map<string, Record<string, number | null>>()
    rows.forEach((row) => {
      const key = toLabel(row[categoryKey])
      const bucket = { ...(byX.get(key) ?? {}) }
      bucket[useColor ? String(row[spec.color!] ?? 'Series') : metricName] = valueOf(row)
      byX.set(key, bucket)
    })
    const data = [...byX.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([key, values]) => ({ x: key, ...values }))
    chart = (
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
        <XAxis dataKey="x" tickLine={false} axisLine={false} tick={TICK} tickMargin={8} tickFormatter={(value: string) => truncate(String(value), 16)} />
        <YAxis tickLine={false} axisLine={false} tick={TICK} tickFormatter={(value: number) => compact.format(value)} />
        <Tooltip content={<ChartTooltip unit={unit} />} cursor={{ stroke: '#94a3b8', strokeDasharray: '4 4' }} />
        {seriesNames.map((name, index) => (
          <Line
            key={name}
            type="monotone"
            dataKey={name}
            name={name}
            stroke={PALETTE[index % PALETTE.length]}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 0 }}
            connectNulls
          />
        ))}
      </LineChart>
    )
  } else {
    const sorted = ranking ? [...rows].sort((a, b) => (valueOf(a) ?? 0) - (valueOf(b) ?? 0)) : rows
    const data = sorted.map((row) => ({ x: toLabel(row[categoryKey]), value: valueOf(row) }))
    chart = (
      <BarChart data={data} layout={ranking ? 'vertical' : 'horizontal'} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={ranking} stroke="#e2e8f0" />
        {ranking ? (
          <>
            <XAxis type="number" tickLine={false} axisLine={false} tick={TICK} tickFormatter={(value: number) => compact.format(value)} />
            <YAxis type="category" dataKey="x" width={130} tickLine={false} axisLine={false} tick={TICK} tickFormatter={(value: string) => truncate(String(value))} />
          </>
        ) : (
          <>
            <XAxis dataKey="x" tickLine={false} axisLine={false} tick={TICK} tickMargin={8} tickFormatter={(value: string) => truncate(String(value), 12)} />
            <YAxis tickLine={false} axisLine={false} tick={TICK} tickFormatter={(value: number) => compact.format(value)} />
          </>
        )}
        <Tooltip content={<ChartTooltip unit={unit} horizontal={ranking} />} cursor={{ fill: 'rgba(16, 185, 129, 0.06)' }} />
        <Bar dataKey="value" name={metricName} fill="#10b981" fillOpacity={0.9} radius={ranking ? [0, 8, 8, 0] : [8, 8, 0, 0]} />
      </BarChart>
    )
  }

  return (
    <figure aria-label={spec.title || 'Chart of the answer data'}>
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-sm font-semibold text-slate-800">{spec.title || `${metricTitle} by ${categoryTitle}`}</h3>
        {unit && <span className="text-xs text-slate-400">{unit}</span>}
      </header>
      <div className="h-[320px] w-full md:h-[420px]">
        <ResponsiveContainer width="100%" height="100%">
          {chart}
        </ResponsiveContainer>
      </div>
      {isLine && seriesNames.length > 1 && (
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1">
          {seriesNames.map((name, index) => (
            <span key={name} className="flex items-center gap-1.5 text-xs text-slate-600">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: PALETTE[index % PALETTE.length] }} />
              {name}
            </span>
          ))}
        </div>
      )}
      <figcaption className="sr-only">{spec.title || `Chart showing ${metricTitle} by ${categoryTitle}`}. The same values are available in the table below.</figcaption>
    </figure>
  )
}