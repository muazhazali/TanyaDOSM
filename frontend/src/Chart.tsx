import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from 'plotly.js-basic-dist-min'
import type { Data, Datum } from 'plotly.js'
import type { AnswerPayload } from './types'

const Plot = createPlotlyComponent(Plotly)

export function ResultChart({ answer }: { answer: AnswerPayload }) {
  const { visualization: spec, table_rows: rows } = answer
  if (rows.length <= 1 || ['none', 'table'].includes(spec.kind) || !spec.x || !spec.y) return null

  const datum = (value: unknown): Datum => typeof value === 'number' || typeof value === 'string' ? value : String(value ?? '')
  let data: Data[]
  if (spec.kind === 'line' && spec.color) {
    const groups = new Map<string, Record<string, unknown>[]>()
    rows.forEach((row) => {
      const label = String(row[spec.color!] ?? 'Series')
      groups.set(label, [...(groups.get(label) ?? []), row])
    })
    data = [...groups.entries()].map(([name, values]) => {
      const sorted = [...values].sort((a, b) => String(a[spec.x!]).localeCompare(String(b[spec.x!])))
      return { type: 'scatter', mode: 'lines+markers', name, x: sorted.map((row) => datum(row[spec.x!])), y: sorted.map((row) => datum(row[spec.y!])) }
    })
  } else {
    const ranking = spec.kind === 'ranking_bar'
    const values = ranking
      ? [...rows].sort((a, b) => Number(a[spec.y!]) - Number(b[spec.y!]))
      : rows
    data = [{
      type: 'bar',
      orientation: ranking ? 'h' : 'v',
      x: values.map((row) => datum(row[ranking ? spec.y! : spec.x!])),
      y: values.map((row) => datum(row[ranking ? spec.x! : spec.y!])),
      hovertemplate: ranking ? `%{y}<br>%{x} ${answer.source?.unit ?? ''}<extra></extra>` : `%{x}<br>%{y} ${answer.source?.unit ?? ''}<extra></extra>`,
    }]
  }
  const ranking = spec.kind === 'ranking_bar'
  const categoryTitle = spec.x?.replaceAll('_', ' ') ?? ''
  const metricTitle = `${spec.y?.replaceAll('_', ' ') ?? ''}${answer.source?.unit ? ` (${answer.source.unit})` : ''}`
  const xTitle = ranking ? metricTitle : categoryTitle
  const yTitle = ranking ? categoryTitle : metricTitle
  return (
    <figure aria-label={spec.title || 'Chart of the answer data'}>
      <Plot
        data={data}
        layout={{ title: { text: spec.title ?? '' }, xaxis: { title: { text: xTitle }, automargin: true }, yaxis: { title: { text: yTitle }, automargin: true }, autosize: true, margin: { l: 70, r: 20, t: 55, b: 60 }, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', font: { family: 'Inter, sans-serif' } }}
        config={{ responsive: true, displaylogo: false, modeBarButtonsToRemove: ['lasso2d', 'select2d'] }}
        useResizeHandler
        className="h-[320px] w-full md:h-[420px]"
      />
      <figcaption className="sr-only">{spec.title || `Chart showing ${yTitle} by ${xTitle}`}. The same values are available in the table below.</figcaption>
    </figure>
  )
}
