import { expect, test } from '@playwright/test'

const now = '2026-08-22T00:00:00Z'
const snapshot = {
  id: 'demo', conversation_id: 'chat-1', question: "What is Malaysia's latest population?", resolved_question: "What is Malaysia's latest population?", status: 'completed',
  created_at: now, updated_at: now, current_node: 'generate_response', error: null, last_sequence: 3,
  answer: { answer: 'The requested population is 34,200 thousand people.', table_rows: [{ date: '2025-01-01', population: 34200 }], visualization: { kind: 'none' }, source: { dataset_id: 'population_malaysia', title: 'Population of Malaysia', agency: 'DOSM', url: 'https://data.gov.my', period: '2025-01-01', unit: 'thousand people', cache_freshness: 'fixture' }, trace: { rows_used: 1 }, error: null },
}
const conversation = {
  id: 'chat-1', title: snapshot.question, created_at: now, updated_at: now,
  turn_count: 1, latest_status: 'completed', turns: [snapshot],
}

test('reopens a completed persisted conversation', async ({ page }) => {
  await page.route('**/api/health', (route) => route.fulfill({ json: { status: 'ready', database: 'ready', catalogue: 'ready', llm: 'ready', embeddings: 'ready' } }))
  await page.route('**/api/conversations?limit=50', (route) => route.fulfill({ json: [conversation] }))
  await page.route('**/api/conversations/chat-1', (route) => route.fulfill({ json: conversation }))
  await page.route('**/api/runs/demo', (route) => route.fulfill({ json: snapshot }))
  await page.route('**/api/runs/demo/events', (route) => route.fulfill({ contentType: 'text/event-stream', body: '' }))
  await page.route('**/api/datasets', (route) => route.fulfill({ json: [] }))
  await page.goto('/')
  await page.getByRole('navigation', { name: 'Recent chats' }).getByRole('button').first().click()
  await expect(page.getByText('The requested population is 34,200 thousand people.')).toBeVisible()
  await page.reload()
  await expect(page.getByText('Population of Malaysia')).toBeVisible()
  await expect(page.getByText('34.2 million')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Download CSV' })).toBeVisible()
})

test('opens a share link without loading the conversation', async ({ page }) => {
  await page.route('**/api/health', (route) => route.fulfill({ json: { status: 'ready', database: 'ready', catalogue: 'ready', llm: 'ready', embeddings: 'unavailable' } }))
  await page.route('**/api/datasets', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/runs/demo', (route) => route.fulfill({ json: snapshot }))
  await page.route('**/api/runs/demo/events', (route) => route.fulfill({ contentType: 'text/event-stream', body: '' }))
  await page.goto('/?run=demo')
  await expect(page.getByRole('heading', { name: 'Shared official-data result' })).toBeVisible()
  await expect(page.getByText(snapshot.question, { exact: true })).toBeVisible()
  await expect(page.getByText('34.2 million')).toBeVisible()
})
