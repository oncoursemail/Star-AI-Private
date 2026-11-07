// @vitest-environment jsdom
import {StrictMode} from 'react'
import {act, cleanup, render} from '@testing-library/react'
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {MotionPolicy} from './MotionPolicy'
import {StarFace} from './StarFace'

beforeEach(() => {
  vi.useFakeTimers()
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers() })

describe('StarFace expression and visibility lifecycle', () => {
  it('actually removes the outgoing expression after the crossfade', () => {
    const {container, rerender} = render(<StarFace mood="idle"/>)
    rerender(<StarFace mood="thinking"/>)
    expect(container.querySelector('.is-leaving')).toBeTruthy()
    act(() => vi.advanceTimersByTime(241))
    expect(container.querySelector('.is-leaving')).toBeNull()
    expect(container.querySelectorAll('.star-face-img')).toHaveLength(1)
    expect(container.querySelector('.star-face-img')?.getAttribute('src')).toContain('thinking.png')
  })
  it('keeps only the latest outgoing face after rapid phase changes', () => {
    const {container, rerender} = render(<StarFace mood="idle"/>)
    rerender(<StarFace mood="thinking"/>)
    act(() => vi.advanceTimersByTime(80))
    rerender(<StarFace mood="writing"/>)
    expect(container.querySelector('.is-leaving')?.getAttribute('src')).toContain('thinking.png')
    act(() => vi.advanceTimersByTime(170))
    expect(container.querySelector('.is-leaving')).toBeTruthy()
    act(() => vi.advanceTimersByTime(71))
    expect(container.querySelector('.is-leaving')).toBeNull()
    expect(container.querySelector('.star-face-img')?.getAttribute('src')).toContain('focused.png')
  })
  it('clears a transition immediately when reduced motion is enabled', () => {
    const {container, rerender} = render(<MotionPolicy reduced={false}><StarFace mood="idle"/></MotionPolicy>)
    rerender(<MotionPolicy reduced={false}><StarFace mood="thinking"/></MotionPolicy>)
    expect(container.querySelector('.is-leaving')).toBeTruthy()
    rerender(<MotionPolicy reduced><StarFace mood="thinking"/></MotionPolicy>)
    expect(container.querySelector('.is-leaving')).toBeNull()
    expect(container.querySelector('.star-face')?.getAttribute('data-still')).toBe('true')
  })
  it('pauses a hidden face and reveals the current expression without replaying transitions', () => {
    const {container, rerender} = render(<StarFace mood="idle"/>)
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    rerender(<StarFace mood="writing"/>)
    expect(container.querySelector('.star-face')?.getAttribute('data-still')).toBe('true')
    expect(container.querySelector('.is-leaving')).toBeNull()
    expect(container.querySelector('.star-face-blink')).toBeNull()
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(container.querySelector('.star-face-img')?.getAttribute('src')).toContain('focused.png')
    expect(container.querySelector('.is-leaving')).toBeNull()
  })
  it('still completes crossfades under React Strict Mode', () => {
    const {container, rerender} = render(<StrictMode><StarFace mood="idle"/></StrictMode>)
    rerender(<StrictMode><StarFace mood="thinking"/></StrictMode>)
    act(() => vi.advanceTimersByTime(241))
    expect(container.querySelector('.is-leaving')).toBeNull()
  })
  it('cleans up pending crossfade callbacks on unmount', () => {
    const clear = vi.spyOn(window, 'clearTimeout')
    const {rerender, unmount} = render(<StarFace mood="idle"/>)
    rerender(<StarFace mood="thinking"/>)
    const previousCalls = clear.mock.calls.length
    unmount()
    expect(clear.mock.calls.length).toBeGreaterThan(previousCalls)
  })
})
