import {describe, expect, it} from 'vitest'
import {applyProgress, isRich, settleRun, startRun} from './activity'

describe('incremental repair activity records evidence without upgrading its scope', () => {
  it('keeps the original finding unverified after an otherwise successful task', () => {
    const detected = applyProgress(startRun('repair', 'chat', 0), {activity: {
      type: 'repair', result: 'detected', checker: 'python.compile', kind: 'syntax', count: 1, attempt: 0,
    }}, 10)
    expect(detected.steps).toHaveLength(1)
    expect(detected.steps[0].state).toBe('failed')
    expect(detected.steps[0].detail).toContain('has not yet passed')
    expect(detected.steps[0].startedAt).toBeUndefined()
    expect(isRich(detected)).toBe(true)
    const finished = settleRun(detected, 'done', 20)
    expect(finished.steps[0]).toEqual(detected.steps[0])
  })

  it('adds a separate narrow success after the actual checker reports it', () => {
    const detected = applyProgress(startRun('repair', 'chat', 0), {activity: {
      type: 'repair', result: 'detected', checker: 'python.compile', kind: 'syntax', count: 1,
    }}, 10)
    const checked = applyProgress(detected, {activity: {
      type: 'repair', result: 'check_passed', checker: 'python.compile', kind: 'syntax', attempt: 1,
    }}, 20)
    expect(checked.steps.map(step => step.state)).toEqual(['failed', 'done'])
    expect(checked.steps[1].title).toBe('Python syntax check passed')
    expect(checked.steps[1].detail).toContain('without running')
    expect(checked.steps[1].detail).toContain('Repair attempt 1')
    expect(JSON.stringify(checked.steps)).not.toContain('fixed')
  })

  it('makes a repeated-failure limit and unknown action outcome explicit', () => {
    const queued = applyProgress(startRun('queued', 'chat', 0), {activity: {
      type: 'repair', result: 'blocked', checker: 'none', kind: 'budget', attempt: 0,
    }}, 1)
    expect(queued.steps[0].title).toBe('Work paused for a repair')
    expect(queued.steps[0].state).toBe('blocked')
    expect(queued.steps[0].detail).not.toContain('limit')
    const stopped = applyProgress(startRun('repair', 'chat', 0), {activity: {
      type: 'repair', result: 'blocked', checker: 'json.loads', kind: 'budget', attempt: 2,
    }}, 10)
    expect(stopped.steps[0].state).toBe('blocked')
    expect(stopped.steps[0].title).toBe('Focused repair limit reached')
    expect(stopped.steps[0].detail).toContain('remains unverified')
    const uncertain = applyProgress(stopped, {activity: {
      type: 'repair', result: 'blocked', checker: 'tool.result', kind: 'unknown_outcome',
    }}, 20)
    expect(uncertain.steps[1].detail).toContain('may have taken effect')
    expect(uncertain.steps[1].detail).toContain('before another mutation')
  })

  it('records Luau advisory findings as an observation rather than a proven defect', () => {
    const advisory = applyProgress(startRun('advisory', 'chat', 0), {activity: {
      type: 'repair', result: 'detected', checker: 'luau.lint', kind: 'advisory', count: 2,
    }}, 1)
    expect(advisory.steps[0].state).toBe('done')
    expect(advisory.steps[0].title).toBe('Luau advisory check reported possible issues')
    expect(advisory.steps[0].detail).toContain('do not prove a defect')
    expect(advisory.steps[0].detail).not.toContain('repair has not yet passed')
    expect(settleRun(advisory, 'done', 2).steps).toEqual(advisory.steps)
  })

  it('does not present advisory lint or tool success as runtime verification', () => {
    const lint = applyProgress(startRun('repair', 'chat', 0), {activity: {
      type: 'repair', result: 'check_passed', checker: 'luau.lint', kind: 'advisory',
    }}, 10)
    expect(lint.steps[0].title).toBe('Luau advisory check passed')
    expect(lint.steps[0].detail).toContain('does not compile or run')
    const tool = applyProgress(lint, {activity: {
      type: 'repair', result: 'check_passed', checker: 'tool.result', kind: 'tool_error',
    }}, 20)
    expect(tool.steps[1].title).toBe('Tool call returned successfully')
    expect(tool.steps[1].detail).toContain('does not verify the whole task')
  })

  it('ignores unknown result codes and never converts an unknown checker into success', () => {
    const start = startRun('repair', 'chat', 0)
    expect(applyProgress(start, {activity: {type: 'repair', result: 'perfect'}}, 1).steps).toEqual([])
    const bad = applyProgress(start, {activity: {
      type: 'repair', result: 'check_passed', state: 'done', checker: 'private-file-path',
      kind: 'private-output', count: 101, attempt: 3,
    }}, 10)
    expect(bad.steps[0].state).toBe('blocked')
    expect(bad.phase).not.toContain('passed')
    expect(JSON.stringify(bad)).not.toContain('private-')
    expect(JSON.stringify(bad)).not.toContain('Repair attempt 3')
  })

  it('does not close or alter an independent tool row', () => {
    const running = applyProgress(startRun('repair', 'chat', 0), {activity: {
      type: 'tool', state: 'running', tool: 'workspace_write',
    }}, 1)
    const finding = applyProgress(running, {activity: {
      type: 'repair', result: 'detected', checker: 'json.loads', kind: 'syntax', count: 1,
    }}, 2)
    expect(finding.steps[0]).toEqual(running.steps[0])
    const ended = applyProgress(finding, {activity: {
      type: 'tool', state: 'done', tool: 'workspace_write',
    }}, 3)
    expect(ended.steps.map(step => step.state)).toEqual(['done', 'failed'])
  })
})
