/**
 * The cast and their looks. Every part of every companion is drawn from these values (see paint.ts),
 * so the parts of one character always match in colour and line.
 */
export type CastId = 'star' | 'ember' | 'astra' | 'gemini'
export const CAST: readonly CastId[] = ['star', 'ember', 'astra', 'gemini']

export type HairStyle = 'twin' | 'long' | 'bob'
export type Style = {
  id: CastId
  name: string
  /** Relative display height: Star is the shortest of the four. */
  height: number
  outline: string
  skin: string
  skinShade: string
  /** Hair gradient from the roots to the tips, and its shadow tone. */
  hair: readonly [string, string]
  hairShade: string
  hairStyle: HairStyle
  /** Where the hair turns from root to tip colour (model y, top to bottom). */
  tipBand: readonly [number, number]
  /** Hair width multiplier (Ember's hair is the fullest). */
  volume: number
  cuff: string
  eye: readonly [string, string]
  top: string
  topShade: string
  skirt: string
  skirtShade: string
  legs: string
  boots: string
  bow: string
  /** Capelet (with a hood behind the head when `hood`). */
  cape: { color: string; shade: string; trim: string; hood: boolean } | null
  glasses: boolean
  /** Hair clip on the head: Star's gold star, Astra's moon. */
  clip: 'star' | 'moon' | null
  /** Astra was drawn as a cat: her normal form keeps the ears and tail. */
  catByNature: boolean
  /** Inner ear colour for animal ears. */
  earInner: string
  cushion: string
  /** Spring feel of the hair: higher is stiffer. */
  hairStiffness: number
}

export const STYLES: Readonly<Record<CastId, Style>> = {
  star: {
    id: 'star', name: 'Star', height: 0.92, outline: '#2a1d22', skin: '#fde3d4', skinShade: '#f3c2b0',
    hair: ['#2b2533', '#f0b63a'], hairShade: '#16121c', hairStyle: 'twin', tipBand: [-52, -32], volume: 1, cuff: '#f7f1e6', eye: ['#7a4a10', '#f6c445'],
    top: '#26222c', topShade: '#17141b', skirt: '#26222c', skirtShade: '#17141b', legs: '#fde3d4', boots: '#1e1b22',
    bow: '#f2c043', cape: null, glasses: false, clip: 'star', catByNature: false, earInner: '#f4b7c0', cushion: '#e7b443',
    hairStiffness: 1.1,
  },
  ember: {
    id: 'ember', name: 'Ember', height: 1, outline: '#4a2116', skin: '#fde3d4', skinShade: '#f0c0aa',
    hair: ['#d4602a', '#f39a3c'], hairShade: '#a8441c', hairStyle: 'long', tipBand: [-80, -22], volume: 1.12, cuff: '#fbf1e2', eye: ['#6b3410', '#d98b2b'],
    top: '#fbf1e2', topShade: '#e6d2b8', skirt: '#5a3424', skirtShade: '#3e2318', legs: '#2c2226', boots: '#5b3a26',
    bow: '#c8323a', cape: {color: '#3a2620', shade: '#26170f', trim: '#c79a4a', hood: false}, glasses: true, clip: null,
    catByNature: false, earInner: '#f6c1b0', cushion: '#8a3b2c', hairStiffness: 0.85,
  },
  astra: {
    id: 'astra', name: 'Astra', height: 0.97, outline: '#140f1c', skin: '#fce4d8', skinShade: '#efc3b4',
    hair: ['#1d1a2c', '#8f55d8'], hairShade: '#0c0a14', hairStyle: 'bob', tipBand: [-64, -46], volume: 1, cuff: '#a978f0', eye: ['#4b1f86', '#b77cf4'],
    top: '#2a2546', topShade: '#1a1630', skirt: '#4a2f78', skirtShade: '#332055', legs: '#1c1824', boots: '#4a3b7a',
    bow: '#e6d7ff', cape: {color: '#232041', shade: '#15132a', trim: '#a978f0', hood: true}, glasses: false, clip: 'moon',
    catByNature: true, earInner: '#c49af0', cushion: '#3b2f6b', hairStiffness: 1,
  },
  gemini: {
    id: 'gemini', name: 'Gemini', height: 0.98, outline: '#3d2a3a', skin: '#fde6da', skinShade: '#f4c6b6',
    hair: ['#8fd3f4', '#f4a3c4'], hairShade: '#6aaed6', hairStyle: 'long', tipBand: [-70, -30], volume: 1, cuff: '#ffffff', eye: ['#1f6fb8', '#7fd0f6'],
    top: '#ffffff', topShade: '#dfe6ee', skirt: '#a9d4ef', skirtShade: '#7fb4da', legs: '#ffffff', boots: '#3fb6a8',
    bow: '#3fb6a8', cape: {color: '#4fc0ae', shade: '#33998a', trim: '#e9fbf6', hood: true}, glasses: false, clip: null,
    catByNature: false, earInner: '#fbd0de', cushion: '#3fb6b0', hairStiffness: 0.8,
  },
}
