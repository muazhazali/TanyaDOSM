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
    data = [...groups.entries()].map(([name, values]) => ({
      type: 'scatter', mode: 'lines+markers', name,
      x: values.map((row) => datum(row[spec.x!])), y: values.map((row) => datum(row[spec.y!])),
    }))
  } else {
    data = [{
      type: 'bar',
      orientation: spec.kind === 'ranking_bar' ? 'h' : 'v',
      x: rows.map((row) => datum(row[spec.x!])),
      y: rows.map((row) => datum(row[spec.y!])),
    }]
  }
  return (
    <Plot
      data={data}
      layout={{ title: { text: spec.title ?? '' }, autosize: true, margin: { l: 70, r: 20, t: 55, b: 60 }, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent' }}
      config={{ responsive: true, displaylogo: false }}
      useResizeHandler
      className="h-[420px] w-full"
    />
  )
}
