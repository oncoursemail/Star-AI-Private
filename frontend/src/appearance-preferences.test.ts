import {describe, expect, it} from 'vitest'
import {APPEARANCE_STORAGE_KEY, APPEARANCE_THEMES, DEFAULT_APPEARANCE, appearanceContrast, normalizeAppearance, normalizeHex, readAppearance, resolveAppearance, writeAppearance} from './appearance'
import type {AppearancePreferences} from './appearance'

/** Independent WCAG calculation checks the rendered token pairs, including generated colors. */
function contrast(a: string, b: string) {
  const luminance = (color: string) => {
    const channels = [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16) / 255)
      .map(channel => channel <= 0.04045 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4))
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
  }
  const x = luminance(a), y = luminance(b)
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

describe('local appearance preferences', () => {
  it('normalizes complete hex colors without accepting arbitrary CSS', () => {
    expect(normalizeHex('#aBc')).toBe('#AABBCC')
    expect(normalizeHex('  #7c9db1  ')).toBe('#7C9DB1')
    for (const value of ['red', '#12', '#1234', '#12345678', 'url(https://example.org)', 'var(--secret)', 'rgb(1, 2, 3)', '#123456; color:red', null, 42]) {
      expect(normalizeHex(value)).toBeNull()
    }
  })

  it('ignores unknown fields and falls back for unsupported schema versions', () => {
    expect(normalizeAppearance({version: 1, theme: 'pearl', density: 'compact', accent: '#abc', endpoint: 'private', css: 'body{}'}))
      .toEqual({version: 1, theme: 'pearl', density: 'compact', accent: '#AABBCC'})
    for (const value of [{version: 2, theme: 'dusk'}, [], null, 'pearl']) expect(normalizeAppearance(value)).toEqual(DEFAULT_APPEARANCE)
    expect(normalizeAppearance({version: 1, theme: '__proto__', density: 'tiny', accent: 'url(x)'})).toEqual(DEFAULT_APPEARANCE)
  })

  it('reads one bounded appearance record and tolerates denied or corrupt storage', () => {
    const keys: string[] = []
    expect(readAppearance({getItem(key) {keys.push(key); return '{"version":1,"theme":"grove","accent":null,"density":"compact"}'}}).theme).toBe('grove')
    expect(keys).toEqual([APPEARANCE_STORAGE_KEY])
    for (const saved of ['{', 'null', 'x'.repeat(513), '{"version":99,"theme":"pearl"}']) {
      expect(readAppearance({getItem: () => saved})).toEqual(DEFAULT_APPEARANCE)
    }
    expect(readAppearance({getItem() {throw new Error('denied')}})).toEqual(DEFAULT_APPEARANCE)
  })

  it('writes only normalized view preferences and reports a failed save', () => {
    const records: Array<[string, string]> = []
    expect(writeAppearance({version: 1, theme: 'dusk', accent: '#eee', density: 'compact'}, {setItem: (key, value) => {records.push([key, value])}})).toBe(true)
    expect(records).toEqual([[APPEARANCE_STORAGE_KEY, '{"version":1,"theme":"dusk","accent":"#EEEEEE","density":"compact"}']])
    expect(writeAppearance({...DEFAULT_APPEARANCE}, {setItem() {throw new Error('quota')}})).toBe(false)
  })
})

describe('authored theme contrast', () => {
  it('matches standard black / white and equal-color contrast reference points', () => {
    expect(appearanceContrast('#000', '#fff')).toBe(21)
    expect(appearanceContrast('#727272', '#727272')).toBe(1)
    expect(appearanceContrast('var(--x)', '#fff')).toBe(0)
  })

  for (const theme of APPEARANCE_THEMES) {
    it(`${theme.name} keeps regular text and semantic colors readable on every main surface`, () => {
      const {tokens} = resolveAppearance({...DEFAULT_APPEARANCE, theme: theme.id})
      const backgrounds = ['--star-bg', '--star-sidebar', '--star-surface-1', '--star-surface-2', '--star-surface-3'] as const
      for (const background of backgrounds) {
        for (const foreground of ['--star-text', '--star-body', '--star-muted', '--star-faint', '--star-success', '--star-danger', '--star-info'] as const) {
          expect(contrast(tokens[foreground], tokens[background]), `${foreground} on ${background}`).toBeGreaterThanOrEqual(4.5)
        }
        expect(contrast(tokens['--star-stroke-control'], tokens[background]), `control on ${background}`).toBeGreaterThanOrEqual(3)
      }
    })

    it(`${theme.name} corrects difficult custom accents without changing success or error meaning`, () => {
      const original = resolveAppearance({...DEFAULT_APPEARANCE, theme: theme.id}).tokens
      const candidates = ['#000000', '#FFFFFF', '#777777', '#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#00FFFF', '#FF00FF', '#101113', '#F7F5F0']
      // A deterministic color cube exercises intermediate colors, not only the two extrema.
      for (const red of [0, 128, 255]) for (const green of [0, 128, 255]) for (const blue of [0, 128, 255]) {
        candidates.push('#' + [red, green, blue].map(channel => channel.toString(16).padStart(2, '0')).join(''))
      }
      for (const accent of candidates) {
        const preferences: AppearancePreferences = {...DEFAULT_APPEARANCE, theme: theme.id, accent}
        const {tokens} = resolveAppearance(preferences)
        for (const surface of ['--star-bg', '--star-sidebar', '--star-surface-1', '--star-surface-2', '--star-surface-3', '--star-gold-wash', '--star-gold-wash-strong'] as const) {
          expect(contrast(tokens['--star-gold'], tokens[surface]), `${accent} on ${surface}`).toBeGreaterThanOrEqual(4.5)
          expect(contrast(tokens['--star-stroke-focus'], tokens[surface]), `focus ${accent} on ${surface}`).toBeGreaterThanOrEqual(3)
        }
        expect(contrast(tokens['--star-on-gold'], tokens['--star-gold']), `button text on ${accent}`).toBeGreaterThanOrEqual(4.5)
        expect(contrast(tokens['--star-on-gold'], tokens['--star-gold-hover']), `hover button text on ${accent}`).toBeGreaterThanOrEqual(4.5)
        for (const status of ['--star-success', '--star-success-wash', '--star-danger', '--star-danger-wash', '--star-info'] as const) expect(tokens[status]).toBe(original[status])
        expect(preferences.accent).toBe(accent) // Resolution never rewrites the owner's original preference.
      }
    })
  }

  it('changes density spacing without reducing type size or accepting unknown density names', () => {
    const comfortable = resolveAppearance({...DEFAULT_APPEARANCE}).tokens
    const compact = resolveAppearance({...DEFAULT_APPEARANCE, density: 'compact'}).tokens
    expect(compact['--star-6']).toBe('20px')
    expect(comfortable['--star-6']).toBe('24px')
    expect(Object.keys(compact).filter(key => key.startsWith('--star-fs-'))).toEqual([])
    expect(normalizeAppearance({version: 1, density: 'microscopic'}).density).toBe('comfortable')
  })
})
