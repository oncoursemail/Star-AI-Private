import {useEffect, useId, useState} from 'react'
import type {CSSProperties, ReactElement, ReactNode} from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import {Check, Palette, RotateCcw, X} from 'lucide-react'
import {APPEARANCE_THEMES, DEFAULT_APPEARANCE, normalizeHex, resolveAppearance} from './appearance'
import type {AppearancePreferences, AppearanceTheme, AppearanceUpdate} from './appearance'
import './appearance.css'

export type AppearanceControlsProps = {
  preferences: AppearancePreferences
  onChange: (patch: AppearanceUpdate) => void
  onReset: () => void
  companionSettings?: ReactNode
  /** False only when the shell has observed that local storage is unavailable. */
  persisted?: boolean
  /** False while no palette is applied (the standard look): no theme shows as picked until the owner picks one. */
  active?: boolean
}

const accents = [
  {name: 'Brass', color: '#E4C48B'}, {name: 'Violet', color: '#BFA9EE'},
  {name: 'Sage', color: '#A8CDA0'}, {name: 'Sky', color: '#90B9DF'},
  {name: 'Coral', color: '#E8A298'}, {name: 'Rose', color: '#D7A5BD'},
]

/** A miniature workspace composition, drawn with native elements rather than a flat swatch. */
function ThemeThumbnail({theme}: {theme: AppearanceTheme}) {
  const p = theme.palette
  const style = {
    '--preview-bg': p.background, '--preview-sidebar': p.sidebar, '--preview-surface': p.surface1,
    '--preview-raised': p.surface3, '--preview-stroke': p.stroke, '--preview-text': p.text,
    '--preview-muted': p.muted, '--preview-accent': p.accent,
  } as CSSProperties
  return <span className="appearance-theme-thumb" style={style} aria-hidden="true">
    <span className="appearance-mini-rail">
      <i className="appearance-mini-star"/>
      <i/><i/><i/>
      <span><i/><i/><i/></span>
    </span>
    <span className="appearance-mini-canvas">
      <span className="appearance-mini-header"><i/><b/><i/></span>
      <span className="appearance-mini-message"><i/><i/></span>
      <span className="appearance-mini-answer"><b/><span><i/><i/><i/></span></span>
      <span className="appearance-mini-composer"><i/><b/></span>
    </span>
  </span>
}

export function AppearanceControls({preferences, onChange, onReset, companionSettings, persisted, active = true}: AppearanceControlsProps) {
  const name = useId()
  const resolved = resolveAppearance(preferences)
  const [hexDraft, setHexDraft] = useState(resolved.requestedAccent)
  const [invalid, setInvalid] = useState(false)
  useEffect(() => {setHexDraft(resolved.requestedAccent); setInvalid(false)}, [resolved.requestedAccent, preferences.theme])
  const commitHex = () => {
    const next = normalizeHex(hexDraft)
    setInvalid(!next)
    if (next) {setHexDraft(next); if (next !== resolved.requestedAccent) onChange({accent: next})}
  }
  const resetAccent = () => {setHexDraft(resolved.theme.palette.accent); setInvalid(false); onChange({accent: null})}
  const resetAll = () => {setHexDraft(APPEARANCE_THEMES[0].palette.accent); setInvalid(false); onReset()}
  const isDefault = !active || (preferences.theme === DEFAULT_APPEARANCE.theme && preferences.accent === null && preferences.density === 'comfortable')
  return <div className="appearance-controls">
    <fieldset className="appearance-section">
      <legend>Theme</legend>
      <p className="appearance-description">{active ? 'Pick one and the whole app changes right away.' : 'You are on the standard look. Pick a theme to change the whole app right away.'}</p>
      <div className="appearance-themes">
        {APPEARANCE_THEMES.map(theme => <label className="appearance-theme-option" key={theme.id}>
          <input type="radio" name={name + '-theme'} value={theme.id} checked={active && preferences.theme === theme.id}
            aria-label={theme.name} onChange={() => onChange({theme: theme.id, accent: null})}/>
          <ThemeThumbnail theme={theme}/>
          <span className="appearance-theme-caption"><strong>{theme.name}</strong><span className="appearance-theme-check" aria-hidden="true">{active && preferences.theme === theme.id && <Check size={12} strokeWidth={2.7}/>}</span></span>
          <span className="appearance-theme-detail">{theme.description}</span>
        </label>)}
      </div>
    </fieldset>

    <fieldset className="appearance-section">
      <legend>Accent color</legend>
      <p className="appearance-description">Used for the selected item, the main button and focus rings.</p>
      <div className="appearance-accents" role="group" aria-label="Accent suggestions">
        {accents.map(accent => <button type="button" className="appearance-accent" key={accent.name}
          style={{'--accent-choice': accent.color} as CSSProperties} aria-label={accent.name + ' accent'}
          title={accent.name} aria-pressed={preferences.accent === accent.color} onClick={() => onChange({accent: accent.color})}>
          <span>{preferences.accent === accent.color && <Check size={13} strokeWidth={2.6}/>}</span>
        </button>)}
      </div>
      <div className="appearance-color-field">
        <label className="appearance-color-picker" title="Choose a custom color">
          <input type="color" aria-label="Choose custom accent" value={resolved.requestedAccent}
            onChange={event => onChange({accent: event.target.value})}/>
        </label>
        <label className="appearance-hex-label"><span>Custom accent</span>
          <input className="appearance-hex" type="text" value={hexDraft} maxLength={16} spellCheck={false}
            autoComplete="off" aria-label="Accent hex color" aria-invalid={invalid || undefined}
            aria-describedby={invalid ? name + '-color-error' : name + '-color-help'}
            onChange={event => {
              const value = event.target.value
              setHexDraft(value); setInvalid(false)
              // Six digits update live. Three-digit shorthand commits on blur, so typing six stays possible.
              if (/^#[\da-f]{6}$/i.test(value)) onChange({accent: value})
            }} onBlur={commitHex} onKeyDown={event => {if (event.key === 'Enter') {event.preventDefault(); commitHex()}}}/>
        </label>
        <button type="button" className="appearance-color-reset" disabled={preferences.accent === null && hexDraft === resolved.requestedAccent && !invalid}
          aria-label="Use theme accent" title="Use theme accent" onClick={resetAccent}><RotateCcw size={15}/></button>
      </div>
      {invalid ? <p className="appearance-field-error" id={name + '-color-error'} role="alert">Use a hex color such as #90B9DF.</p>
        : <p className="appearance-color-help" id={name + '-color-help'}>
          {resolved.adjusted ? <><span className="appearance-applied-dot" style={{background: resolved.accent}} aria-hidden="true"/> Uses {resolved.accent} to keep text readable.</> : 'Text and focus colors stay readable automatically.'}
        </p>}
    </fieldset>

    <fieldset className="appearance-section">
      <legend>Spacing</legend>
      <div className="appearance-density-options">
        {(['comfortable', 'compact'] as const).map(density => <label className="appearance-density-option" key={density}>
          <input type="radio" name={name + '-density'} value={density} checked={preferences.density === density}
            aria-label={density === 'comfortable' ? 'Comfortable spacing' : 'Compact spacing'} onChange={() => onChange({density})}/>
          <span className={'appearance-density-icon is-' + density} aria-hidden="true"><i/><i/><i/></span>
          <span>{density === 'comfortable' ? 'Comfortable' : 'Compact'}</span>
          <Check size={13} aria-hidden="true"/>
        </label>)}
      </div>
      <p className="appearance-color-help">The same readable type, with room to breathe or room for more.</p>
    </fieldset>

    {companionSettings && <section className="appearance-companions" aria-label="Companion settings">{companionSettings}</section>}
    <div className="appearance-footer">
      <span>{persisted === false ? 'Applies now. This browser cannot save preferences.' : 'Changes apply immediately.'}</span>
      <button type="button" className="appearance-reset" disabled={isDefault && hexDraft === resolved.requestedAccent && !invalid} onClick={resetAll}><RotateCcw size={13} aria-hidden="true"/> Reset appearance</button>
    </div>
  </div>
}

export type AppearancePanelProps = AppearanceControlsProps & {
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** A custom trigger can be provided by the shell; null leaves a controlled drawer without one. */
  trigger?: ReactElement | null
}

export function AppearancePanel({open: controlled, onOpenChange, trigger, ...controls}: AppearancePanelProps) {
  const [localOpen, setLocalOpen] = useState(false)
  const setOpen = (open: boolean) => {if (controlled === undefined) setLocalOpen(open); onOpenChange?.(open)}
  return <Dialog.Root open={controlled ?? localOpen} onOpenChange={setOpen}>
    {trigger !== null && <Dialog.Trigger asChild>{trigger ?? <button type="button" className="appearance-trigger" aria-label="Appearance" title="Appearance"><Palette size={16} aria-hidden="true"/><span>Appearance</span></button>}</Dialog.Trigger>}
    <Dialog.Portal>
      <Dialog.Overlay className="star-layer appearance-overlay"/>
      <Dialog.Content className="star-layer appearance-drawer">
        <div className="appearance-heading">
          <div><span className="appearance-eyebrow">Your workspace</span><Dialog.Title>Make Star yours.</Dialog.Title></div>
          <Dialog.Close asChild><button type="button" className="appearance-close" aria-label="Close appearance"><X size={18}/></button></Dialog.Close>
        </div>
        <Dialog.Description className="appearance-intro">Choose a palette, tune the details, and make yourself at home.</Dialog.Description>
        <div className="appearance-scroll"><AppearanceControls {...controls}/></div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}
