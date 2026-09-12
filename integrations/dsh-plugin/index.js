import { defineTool } from '@deepseek-ai/dsh-tools'
import { createContextBridgeTool } from './tool.js'

export const name = 'contextbridge-dsh'
export const inject = ['tools']

export function apply(ctx) {
  ctx.tools.register(createContextBridgeTool(defineTool))
}
