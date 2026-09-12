import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

export async function runContextBridge({ command, args, cwd, signal }) {
  return execFileAsync(command, args, {
    cwd,
    signal,
    encoding: 'utf8',
    maxBuffer: 256 * 1024,
  })
}

export function createContextBridgeTool(defineTool, run = runContextBridge) {
  return defineTool({
    name: 'contextbridge_handoff',
    description: 'Load concise, attributed project memory relevant to the current task.',
    parameters: {
      task: {
        type: 'string',
        required: true,
        description: 'The concrete task the agent is about to continue.',
      },
      token_budget: {
        type: 'number',
        description: 'Approximate maximum Context Pack tokens. Defaults to 4000.',
      },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    timeoutMs: 30_000,
    async execute(args, exec) {
      const cwd = exec.agent?.session.header.cwd
      if (!cwd) throw new Error('ContextBridge requires a DSH session workspace cwd.')

      const command = process.env.CONTEXTBRIDGE_COMMAND || 'contextbridge'
      const tokenBudget = Math.max(100, Math.floor(args.token_budget ?? 4000))
      const commandArgs = ['inspect', '--task', args.task, '--token-budget', String(tokenBudget)]
      const { stdout } = await run({ command, args: commandArgs, cwd, signal: exec.signal })
      return stdout.trim()
    },
  })
}
