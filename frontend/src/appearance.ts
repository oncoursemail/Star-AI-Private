/** Appearance is a local view preference. It never changes a model, a provider or a permission. */
export type ThemeId = 'obsidian' | 'pearl' | 'dusk' | 'grove'
export type AppearanceDensity = 'comfortable' | 'compact'
export type AppearancePreferences = {
  version: 1
  theme: ThemeId
  /** The owner's requested color. Null uses the authored theme color. */
  accent: string | null
  density: AppearanceDensity
}
export type AppearanceUpdate = Partial<Omit<AppearancePreferences, 'version'>>
export type AppearanceTokens = Readonly<Record<`--star-${string}`, string>>
type RGB = readonly [number, number, number]
type Palette = {
  background: string; sidebar: string; surface1: string; surface2: string; surface3: string
  text: string; textHover: string; body: string; muted: string; faint: string
  stroke: string; strokeSoft: string; strokeStrong: string; strokeControl: string
  accent: string; success: string; danger: string; info: string
}
export type AppearanceTheme = {
  id: ThemeId
  name: string
  description: string
  scheme: 'dark' | 'light'
  palette: Readonly<Palette>
}

export const APPEARANCE_STORAGE_KEY = 'star.appearance.v1'
export const DEFAULT_APPEARANCE: Readonly<AppearancePreferences> = Object.freeze({
  version: 1, theme: 'obsidian', accent: null, density: 'comfortable',
})

/** Complete palettes, including readable secondary text and control boundaries. */
export const APPEARANCE_THEMES: ReadonlyArray<AppearanceTheme> = [
  {
    id: 'obsidian', name: 'Obsidian', description: 'Soft black. Warm brass.', scheme: 'dark',
    palette: {
      background: '#101113', sidebar: '#151618', surface1: '#1B1C1F', surface2: '#232429', surface3: '#2C2D32',
      text: '#F3F1EC', textHover: '#FFFFFF', body: '#DDDAD3', muted: '#B6B3AC', faint: '#AAA69F',
      stroke: '#323337', strokeSoft: '#26272B', strokeStrong: '#48494F', strokeControl: '#85858C',
      accent: '#E4C48B', success: '#A9D3B7', danger: '#F0ADAD', info: '#B1C9EA',
    },
  },
  {
    id: 'pearl', name: 'Pearl', description: 'Warm paper. Clear space.', scheme: 'light',
    palette: {
      background: '#F7F5F0', sidebar: '#EEEBE4', surface1: '#FFFEFA', surface2: '#EEEAE2', surface3: '#E4DED3',
      text: '#232524', textHover: '#101513', body: '#343831', muted: '#535950', faint: '#585E55',
      stroke: '#D6D2C8', strokeSoft: '#E5E0D7', strokeStrong: '#B8B5AA', strokeControl: '#777B71',
      accent: '#785C2D', success: '#2C6142', danger: '#9B373B', info: '#315E89',
    },
  },
  {
    id: 'dusk', name: 'Dusk', description: 'Deep plum. Quiet violet.', scheme: 'dark',
    palette: {
      background: '#16131C', sidebar: '#1D1825', surface1: '#241F2D', surface2: '#2D2638', surface3: '#362D43',
      text: '#F2EDF8', textHover: '#FFFFFF', body: '#DED6E8', muted: '#BFB2CC', faint: '#AEA1BC',
      stroke: '#3F354B', strokeSoft: '#30273B', strokeStrong: '#594E66', strokeControl: '#8F829D',
      accent: '#CDB2EF', success: '#A8D4BD', danger: '#F1ACBD', info: '#B4C9F1',
    },
  },
  {
    id: 'grove', name: 'Grove', description: 'Forest shade. Fresh sage.', scheme: 'dark',
    palette: {
      background: '#101714', sidebar: '#17201B', surface1: '#1D2822', surface2: '#25322A', surface3: '#2D3C32',
      text: '#ECF3EC', textHover: '#FFFFFF', body: '#D4E0D6', muted: '#AFBFB2', faint: '#9DAFA1',
      stroke: '#3A4A3E', strokeSoft: '#2B392F', strokeStrong: '#556A59', strokeControl: '#829989',
      accent: '#B4D5AA', success: '#B4D5AA', danger: '#F4B6B0', info: '#AFCBEA',
    },
  },
]

/** Only complete hex colors cross into CSS. Shorthand expands to a canonical six-digit value. */
export function normalizeHex(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 16) return null
  const text = value.trim()
  if (/^#[\da-f]{6}$/i.test(text)) return text.toUpperCase()
  if (/^#[\da-f]{3}$/i.test(text)) return '#' + [...text.slice(1)].map(c => c + c).join('').toUpperCase()
  return null
}

export function normalizeAppearance(value: unknown): AppearancePreferences {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {...DEFAULT_APPEARANCE}
  const input = value as Record<string, unknown>
  if (input.version !== 1) return {...DEFAULT_APPEARANCE}
  return {
    version: 1,
    theme: APPEARANCE_THEMES.some(theme => theme.id === input.theme) ? input.theme as ThemeId : 'obsidian',
    accent: normalizeHex(input.accent),
    density: input.density === 'compact' ? 'compact' : 'comfortable',
  }
}

export function readAppearance(storage?: Pick<Storage, 'getItem'>): AppearancePreferences {
  try {
    const saved = (storage ?? window.localStorage).getItem(APPEARANCE_STORAGE_KEY)
    if (!saved || saved.length > 512) return {...DEFAULT_APPEARANCE}
    return normalizeAppearance(JSON.parse(saved))
  } catch {
    // file:// storage and privacy settings can deny access. The current session still works.
    return {...DEFAULT_APPEARANCE}
  }
}

export function writeAppearance(preferences: AppearancePreferences, storage?: Pick<Storage, 'setItem'>): boolean {
  try {
    (storage ?? window.localStorage).setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(normalizeAppearance(preferences)))
    return true
  } catch {
    return false
  }
}

function rgb(hex: string): RGB {
  return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)]
}
function hex(channels: RGB): string {
  return '#' + channels.map(channel => Math.round(channel).toString(16).padStart(2, '0')).join('').toUpperCase()
}
function mix(first: string, second: string, amount: number): string {
  const from = rgb(first), to = rgb(second)
  return hex(from.map((channel, index) => channel + (to[index] - channel) * amount) as unknown as RGB)
}
function luminance(color: string): number {
  const linear = rgb(color).map(channel => {
    const value = channel / 255
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722
}
/** WCAG relative-luminance contrast, for already validated opaque colors. */
export function appearanceContrast(first: string, second: string): number {
  const a = normalizeHex(first), b = normalizeHex(second)
  if (!a || !b) return 0
  const values = [luminance(a), luminance(b)].sort((x, y) => x - y)
  return (values[1] + 0.05) / (values[0] + 0.05)
}

function readableAccent(requested: string, theme: AppearanceTheme): string {
  const p = theme.palette
  const surfaces = [p.background, p.sidebar, p.surface1, p.surface2, p.surface3]
  const passes = (color: string) => [...surfaces, mix(p.surface1, color, 0.1), mix(p.surface1, color, 0.16)]
    .every(surface => appearanceContrast(color, surface) >= 4.6)
  if (passes(requested)) return requested
  const target = theme.scheme === 'dark' ? '#FFFFFF' : '#000000'
  // A bounded search changes brightness only as much as required; it never accepts CSS or remote assets.
  let low = 0, high = 1
  for (let step = 0; step < 16; step++) {
    const middle = (low + high) / 2
    if (passes(mix(requested, target, middle))) high = middle
    else low = middle
  }
  return mix(requested, target, high)
}

export function resolveAppearance(preferences: AppearancePreferences): {
  theme: AppearanceTheme; accent: string; requestedAccent: string; adjusted: boolean; tokens: AppearanceTokens
} {
  const safe = normalizeAppearance(preferences)
  const theme = APPEARANCE_THEMES.find(candidate => candidate.id === safe.theme) ?? APPEARANCE_THEMES[0]
  const p = theme.palette
  const requestedAccent = safe.accent ?? p.accent
  const accent = readableAccent(requestedAccent, theme)
  const dark = theme.scheme === 'dark'
  const hover = mix(accent, dark ? '#FFFFFF' : '#000000', 0.09)
  const onAccent = appearanceContrast(accent, '#101113') >= appearanceContrast(accent, '#FFFFFF') ? '#101113' : '#FFFFFF'
  const tokens: AppearanceTokens = {
    '--star-bg': p.background, '--star-sidebar': p.sidebar,
    '--star-surface-1': p.surface1, '--star-surface-2': p.surface2, '--star-surface-3': p.surface3,
    '--star-text': p.text, '--star-text-hover': p.textHover, '--star-body': p.body,
    '--star-muted': p.muted, '--star-faint': p.faint,
    '--star-stroke': p.stroke, '--star-stroke-soft': p.strokeSoft, '--star-stroke-strong': p.strokeStrong,
    '--star-stroke-control': p.strokeControl, '--star-stroke-focus': accent,
    '--star-veil': dark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(20, 25, 20, 0.045)',
    '--star-scrim': dark ? 'rgba(5, 7, 10, 0.62)' : 'rgba(26, 29, 24, 0.35)',
    '--star-gold': accent, '--star-gold-soft': readableAccent(mix(accent, p.surface1, 0.12), theme),
    '--star-gold-hover': hover, '--star-on-gold': onAccent,
    '--star-gold-wash': mix(p.surface1, accent, 0.1), '--star-gold-wash-strong': mix(p.surface1, accent, 0.16),
    '--star-gold-line': mix(p.surface1, accent, 0.48),
    // Status colors do not follow a custom accent. Success remains green and errors remain red.
    '--star-success': p.success, '--star-success-wash': mix(p.surface1, p.success, 0.12),
    '--star-danger': p.danger, '--star-danger-wash': mix(p.surface1, p.danger, 0.1), '--star-info': p.info,
    '--star-shadow-float': dark ? '0 16px 48px rgba(0, 0, 0, 0.45)' : '0 16px 48px rgba(35, 32, 25, 0.18)',
    '--star-3': safe.density === 'compact' ? '10px' : '12px',
    '--star-4': safe.density === 'compact' ? '14px' : '16px',
    '--star-5': safe.density === 'compact' ? '18px' : '20px',
    '--star-6': safe.density === 'compact' ? '20px' : '24px',
    '--star-8': safe.density === 'compact' ? '28px' : '32px',
  }
  return {theme, accent, requestedAccent, adjusted: accent !== requestedAccent, tokens}
}

/** Only prefixed variables are attached to html. Scoped CSS maps these onto desktop surfaces. */
export const appearanceRootVariable = (token: string) => token.replace(/^--star-/, '--star-appearance-')
