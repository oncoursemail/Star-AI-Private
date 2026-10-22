// @vitest-environment jsdom
import {afterEach, describe, expect, it, vi} from 'vitest'
import {cleanup, render} from '@testing-library/react'
import {CompanionStage, measurePlatforms} from './CompanionStage'
import {DEFAULT_COMPANION_PREFERENCES} from '../companion-catalog'

const rect = (left: number, top: number, width: number, height: number) =>
  ({left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({})}) as DOMRect

function thread(withComposer: boolean) {
  const root = document.createElement('div')
  root.getBoundingClientRect = () => rect(200, 0, 1000, 800)
  if (withComposer) {
    const dock = document.createElement('div'); dock.className = 'dock'
    dock.getBoundingClientRect = () => rect(300, 620, 800, 180)
    const cmp = document.createElement('div'); cmp.className = 'cmp'
    cmp.getBoundingClientRect = () => rect(340, 630, 720, 130)
    dock.append(cmp); root.append(dock)
  }
  return root
}

describe('companion stage layout', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('walks the free margins and the top edge of the composer, never across its face', () => {
    const platforms = measurePlatforms(thread(true), false, 92, false, false)
    expect(platforms.map(p => p.id)).toEqual(['floor-l', 'ledge', 'floor-r'])
    const ledge = platforms[1]
    expect(ledge.y).toBe(623)
    expect(ledge.x0).toBeGreaterThan(140)
    expect(ledge.x1).toBeLessThan(860)
    expect(platforms[0].x1).toBeLessThan(140)
    expect(platforms[2].x0).toBeGreaterThan(860)
  })

  it('leaves the composer ledge while you read older messages and keeps it quiet while you type', () => {
    expect(measurePlatforms(thread(true), false, 92, true, false).map(p => p.id)).toEqual(['floor-l', 'floor-r'])
    expect(measurePlatforms(thread(true), false, 92, false, true).find(p => p.id === 'ledge')?.quiet).toBe(true)
  })

  it('uses the whole bottom edge in an empty chat', () => {
    expect(measurePlatforms(thread(false), true, 92, false, false)).toEqual([{id: 'floor', x0: 8, x1: 992, y: 794}])
  })

  it('renders nothing without WebGL2 or with nobody in the cast', () => {
    const props = {app: 'idle' as const, reducedMotion: false, learning: false, empty: false}
    expect(render(<CompanionStage {...props} preferences={DEFAULT_COMPANION_PREFERENCES}/>).container.innerHTML).toBe('')
    vi.stubGlobal('WebGL2RenderingContext', function WebGL2RenderingContext() {})
    expect(render(<CompanionStage {...props} preferences={{...DEFAULT_COMPANION_PREFERENCES, cast: []}}/>).container.innerHTML).toBe('')
  })

  it('is decorative, and marks still mode for reduced motion', () => {
    vi.stubGlobal('WebGL2RenderingContext', function WebGL2RenderingContext() {})
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    const {container} = render(<div className="thread"><CompanionStage app="idle" reducedMotion learning={false} empty={false} preferences={DEFAULT_COMPANION_PREFERENCES}/></div>)
    const stage = container.querySelector('.companion-stage')
    expect(stage?.getAttribute('aria-hidden')).toBe('true')
    expect(stage?.hasAttribute('data-still')).toBe(true)
    expect(container.querySelectorAll('.companion-stage__hit')).toHaveLength(4)
  })
})
