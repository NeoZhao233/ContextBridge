import assert from 'node:assert/strict'
import test from 'node:test'
import { createContextBridgeTool } from './tool.js'

test('tool delegates to ContextBridge for the calling DSH workspace', async () => {
  let invocation
  const defineTool = definition => definition
  const run = async input => {
    invocation = input
    return { stdout: '# Context Pack\n\nRelevant memory\n' }
  }
  const tool = createContextBridgeTool(defineTool, run)
  const signal = new AbortController().signal
  const result = await tool.execute(
    { task: 'continue auth work', token_budget: 1200 },
    { agent: { session: { header: { cwd: '/workspace/project' } } }, signal },
  )

  assert.equal(result, '# Context Pack\n\nRelevant memory')
  assert.equal(invocation.cwd, '/workspace/project')
  assert.equal(invocation.command, 'contextbridge')
  assert.deepEqual(invocation.args, [
    'inspect', '--task', 'continue auth work', '--token-budget', '1200',
  ])
  assert.equal(invocation.signal, signal)
})

test('tool refuses calls without a DSH workspace', async () => {
  const tool = createContextBridgeTool(definition => definition, async () => ({ stdout: '' }))
  await assert.rejects(
    tool.execute({ task: 'work' }, { agent: undefined, signal: new AbortController().signal }),
    /workspace cwd/,
  )
})
