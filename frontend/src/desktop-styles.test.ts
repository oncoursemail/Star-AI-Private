/**
 * Style rules that only show up in the real desktop shell.
 *
 * jsdom does not apply stylesheets, so these read the CSS sources. Each case
 * pins a defect that was seen in the Qt WebEngine window and fixed.
 */
import {readFileSync} from 'node:fs'
import {describe, expect, it} from 'vitest'

const source = (name: string) => readFileSync(new URL(name, import.meta.url), 'utf8').replace(/\r\n/g, '\n')
/** Specificity of a simple selector list as [ids, classes, elements]; `:is()` counts as its most specific argument. */
function specificity(selector: string): [number, number, number] {
  let rest = selector
  let best: [number, number, number] = [0, 0, 0]
  rest = rest.replace(/:is\(([^)]*)\)/g, (_, list: string) => {
    for (const item of list.split(',')) {
      const value = specificity(item.trim())
      if (value[0] * 10000 + value[1] * 100 + value[2] > best[0] * 10000 + best[1] * 100 + best[2]) best = value
    }
    return ' '
  })
  const ids = (rest.match(/#[\w-]+/g) || []).length
  const classes = (rest.match(/\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+/g) || []).length
  const elements = (rest.replace(/#[\w-]+|\.[\w-]+|\[[^\]]+\]|::?[\w-]+/g, ' ').match(/[a-zA-Z][\w-]*/g) || []).length
  return [ids + best[0], classes + best[1], elements + best[2]]
}
const weight = (value: [number, number, number]) => value[0] * 10000 + value[1] * 100 + value[2]

describe('composer focus', () => {
  const shell = source('./stellar-ui.css')
  const chat = source('./chat.css')

  it('is shown on the composer edge, not as a second ring around the text field', () => {
    const ring = shell.match(/(\.shell :is\([^)]*textarea[^)]*\):focus-visible)/)
    expect(ring, 'the shared focus ring').not.toBeNull()
    const off = chat.match(/([^{}\n]*\.cmp-input:focus-visible)\s*\{\s*outline:\s*0;?\s*\}/)
    expect(off, 'a rule that switches the ring off for the composer field').not.toBeNull()
    // Desktop.tsx imports stellar-ui.css before chat.css, so equal specificity would also win; more is safer.
    expect(weight(specificity(off![1].trim()))).toBeGreaterThan(weight(specificity(ring![1])))
    expect(chat).toMatch(/\.cmp:focus-within\s*\{\s*border-color:\s*var\(--star-stroke-focus\)/)
  })

  it('measures specificity the way browsers do', () => {
    expect(specificity('.shell .cmp-input')).toEqual([0, 2, 0])
    expect(specificity('.shell :is(button, input, textarea, [tabindex]):focus-visible')).toEqual([0, 3, 0])
    expect(specificity('.shell .cmp .cmp-input:focus-visible')).toEqual([0, 4, 0])
  })
})

describe('every class the desktop pages use has a style', () => {
  const sheets = ['./styles.css', './tokens.css', './stellar-ui.css', './chat.css', './integrated-tools.css', './learning.css', './media.css', './settings-ui.css', './redesign.css', './resilience.css', './voice-call.css', './polish.css', './commerce.css', './commerce-mission.css', './commerce-seasonality.css'].map(source).join('\n')
  const styled = new Set(Array.from(sheets.matchAll(/\.([A-Za-z_][\w-]*)/g), match => match[1]))
  /** Class names written as plain string literals in a component (dynamic `is-*` suffixes are skipped). */
  const used = (file: string) => {
    const names = new Set<string>()
    for (const match of source(file).matchAll(/className=(?:"([^"]+)"|\{'([^']+)')/g)) {
      for (const name of (match[1] || match[2]).split(/\s+/)) {
        if (/^[A-Za-z_][\w-]*$/.test(name) && !name.endsWith('-')) names.add(name)
      }
    }
    return names
  }
  // Names that are only hooks for scripts and tests, or are styled through another selector.
  const hooks = new Set(['rail-chat', 'composer-image-chip', 'composer-menu', 'dashboard', 'starlight'])

  it('leaves no page element unstyled (the Tools cards lost their layout this way)', () => {
    const missing: string[] = []
    for (const file of ['./Desktop.tsx', './CommercePanel.tsx', './CommerceApprovals.tsx', './CommerceMissionControl.tsx', './CommerceSeasonality.tsx', './components.tsx', './Composer.tsx', './ActivityTimeline.tsx', './IntegrationPanels.tsx', './ModelFleetPanel.tsx', './ReviewToolsPanel.tsx', './Charts.tsx', './LearningPanel.tsx', './MediaPanel.tsx', './VoiceSettings.tsx', './StudioTargetSettings.tsx', './ChatRow.tsx', './StarFace.tsx', './ScreenConsent.tsx', './VoiceCall.tsx', './ReadAloud.tsx']) {
      for (const name of used(file)) if (!styled.has(name) && !hooks.has(name)) missing.push(`${file}: .${name}`)
    }
    expect(missing).toEqual([])
  })

  it('lays the Tools knowledge cards out as a grid with the status tag beside the icon', () => {
    const shell = source('./stellar-ui.css')
    expect(shell).toMatch(/\.shell \.intelligence-grid\s*\{[^}]*display:\s*grid/)
    expect(shell).toMatch(/\.shell \.integration-head\s*\{[^}]*justify-content:\s*space-between/)
  })
})
