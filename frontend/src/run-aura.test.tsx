// @vitest-environment jsdom
import {afterEach, describe, expect, it} from 'vitest'
import {cleanup, render, screen} from '@testing-library/react'
import {applyProgress, settleRun, startRun} from './activity'
import {RunAura, runAuraPhase} from './RunAura'

afterEach(cleanup)

describe('Litha run aura: truth and lifecycle', () => {
  it('never implies progress without a running backend turn', () => {
    expect(runAuraPhase(null)).toBe('idle')
    const run = startRun('request-1', 'chat', 1000)
    expect(runAuraPhase(run)).toBe('working')
    expect(runAuraPhase(settleRun(run, 'done', 1200))).toBe('idle')
    expect(runAuraPhase(settleRun(run, 'failed', 1200))).toBe('idle')
    expect(runAuraPhase(settleRun(run, 'cancelled', 1200))).toBe('idle')
  })

  it('uses real backend-reported search and verification events', () => {
    const start = startRun('request-2', 'chat', 1000)
    const searching = applyProgress(start, {activity: {type: 'search', state: 'running'}}, 1050)
    expect(runAuraPhase(searching)).toBe('researching')
    const searched = applyProgress(searching, {activity: {type: 'search', state: 'done'}}, 1150)
    expect(runAuraPhase(searched)).toBe('working')
    const checking = applyProgress(searched, {activity: {type: 'tool', tool: 'star_luau_check', state: 'running'}}, 1200)
    expect(runAuraPhase(checking)).toBe('verifying')
    expect(runAuraPhase(checking, true)).toBe('stopping')
    const checked = applyProgress(checking, {activity: {type: 'tool', tool: 'star_luau_check', state: 'done'}}, 1250)
    expect(runAuraPhase(checked)).toBe('working')
  })

  it('recognizes the dedicated Luau-check progress type, not only generic tool events', () => {
    const start = startRun('request-dedicated-check', 'chat', 1000)
    const checking = applyProgress(start, {activity: {type: 'luau_check', state: 'running'}}, 1010)
    expect(runAuraPhase(checking)).toBe('verifying')
    const checked = applyProgress(checking, {activity: {type: 'luau_check', state: 'done', result: 'passed'}}, 1030)
    expect(runAuraPhase(checked)).toBe('working')
  })

  it('does not call normal tools verification', () => {
    const start = startRun('request-3', 'chat', 1000)
    const tool = applyProgress(start, {activity: {type: 'tool', tool: 'workspace_search', state: 'running'}}, 1020)
    expect(runAuraPhase(tool)).toBe('working')
  })

  it('keeps the wrapped composer interactive and its effect assistive-technology silent', () => {
    render(<RunAura phase="verifying"><button type="button">Stop response</button></RunAura>)
    expect(screen.getByRole('button', {name: 'Stop response'})).toBeTruthy()
    const aura = screen.getByTestId('litha-run-aura')
    expect(aura.getAttribute('data-phase')).toBe('verifying')
    expect(aura.querySelector('.litha-run-aura-fx')?.getAttribute('aria-hidden')).toBe('true')
    expect(aura.querySelectorAll('svg rect')).toHaveLength(2)
  })

  it('preserves a visually quiet idle state', () => {
    render(<RunAura phase="idle"><span>Composer</span></RunAura>)
    expect(screen.getByTestId('litha-run-aura').getAttribute('data-phase')).toBe('idle')
    expect(screen.getByText('Composer')).toBeTruthy()
  })
})
