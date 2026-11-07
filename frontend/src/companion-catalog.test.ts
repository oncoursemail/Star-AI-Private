import {describe, expect, it} from 'vitest'
import {COMPANIONS, companionCharacter, companionImage, companionWorkLabel, normalizeCompanionPreferences} from './companion-catalog'

describe('companion appearance contract', () => {
  it.each([null, undefined, [], 'star', {version: 2, character: 'astra', visible: false}])('uses safe, visible defaults for an unsupported preference record', value => {
    expect(normalizeCompanionPreferences(value)).toEqual({version: 1, character: 'star', motion: 'subtle', visible: true})
  })
  it('retains an explicit hidden/still choice and drops unrelated or executable fields', () => {
    expect(normalizeCompanionPreferences({version: 1, character: 'ember', motion: 'still', visible: false, provider: 'other', script: 'alert(1)'}))
      .toEqual({version: 1, character: 'ember', motion: 'still', visible: false})
  })
  it('never treats a stored URL as an image or character ID', () => {
    expect(normalizeCompanionPreferences({version: 1, character: 'https://example.com/avatar.png', visible: 'yes', motion: 'unlimited'}))
      .toEqual({version: 1, character: 'star', motion: 'subtle', visible: true})
  })
  it('limits character choices to the original project pack and packaged relative paths', () => {
    expect(COMPANIONS.map(character => character.id)).toEqual(['star', 'ember', 'astra'])
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
