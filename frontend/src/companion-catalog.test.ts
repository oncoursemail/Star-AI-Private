import {describe, expect, it} from 'vitest'
import {COMPANIONS, DEFAULT_COMPANION_PREFERENCES, companionCharacter, companionImage, companionWorkLabel, normalizeCompanionPreferences} from './companion-catalog'

describe('companion appearance contract', () => {
  it.each([null, undefined, [], 'star', {version: 3, character: 'astra', visible: false}])('uses safe, visible defaults for an unsupported preference record', value => {
    expect(normalizeCompanionPreferences(value)).toEqual(DEFAULT_COMPANION_PREFERENCES)
  })
  it('defaults: walking companions on, all four out, normal forms, affection on, study looks automatic', () => {
    expect(DEFAULT_COMPANION_PREFERENCES).toEqual({
      version: 2, character: 'star', motion: 'subtle', visible: true, stage: true, cast: ['star', 'ember', 'astra', 'gemini'],
      forms: {star: 'normal', ember: 'normal', astra: 'normal', gemini: 'normal'}, affection: true, study: 'auto',
    })
  })
  it('keeps a version 1 choice and fills in the new settings', () => {
    expect(normalizeCompanionPreferences({version: 1, character: 'ember', motion: 'still', visible: false, provider: 'other', script: 'alert(1)'}))
      .toEqual({...DEFAULT_COMPANION_PREFERENCES, character: 'ember', motion: 'still', visible: false})
  })
  it('keeps valid version 2 choices and drops unknown cast members, forms and fields', () => {
    expect(normalizeCompanionPreferences({
      version: 2, character: 'gemini', motion: 'subtle', visible: true, stage: false, cast: ['astra', 'gemini', 'mallory'],
      forms: {astra: 'dog', gemini: 'cat', star: 'dragon'}, affection: false, study: 'on', script: 'x',
    })).toEqual({
      ...DEFAULT_COMPANION_PREFERENCES, character: 'gemini', stage: false, cast: ['astra', 'gemini'],
      forms: {star: 'normal', ember: 'normal', astra: 'dog', gemini: 'cat'}, affection: false, study: 'on',
    })
  })
  it('never treats a stored URL as an image or character ID', () => {
    expect(normalizeCompanionPreferences({version: 1, character: 'https://example.com/avatar.png', visible: 'yes', motion: 'unlimited'}))
      .toEqual(DEFAULT_COMPANION_PREFERENCES)
  })
  it('limits character choices to the original project pack and packaged relative paths', () => {
    expect(COMPANIONS.map(character => character.id)).toEqual(['star', 'ember', 'astra', 'gemini'])
    for (const character of COMPANIONS) {
      expect(character.image).toMatch(/^\.\/assets\/(mascot\/poses|companions)\/[a-z-]+\.png$/)
      expect(new URL(character.image, 'file:///app/frontend/dist/index.html').protocol).toBe('file:')
    }
  })
  it('uses already shipped Star poses for actual work states', () => {
    const star = companionCharacter('star')
    expect(companionImage(star, 'thinking')).toBe('./assets/mascot/poses/think.png')
    expect(companionImage(star, 'streaming')).toBe('./assets/mascot/poses/type-1.png')
    expect(companionImage(star, 'finished')).toBe('./assets/mascot/poses/wave-a.png')
    expect(companionImage(star, 'cancelled')).toBe('./assets/mascot/poses/stand.png')
    expect(companionImage(companionCharacter('astra'), 'thinking')).toBe('./assets/companions/astra.png')
  })
  it('keeps failures and stops distinct from successful completion', () => {
    expect(companionWorkLabel('error')).toBe('The request could not finish')
    expect(companionWorkLabel('cancelled')).toBe('Request stopped')
    expect(companionWorkLabel('finished')).toBe('Answer complete')
  })
})
