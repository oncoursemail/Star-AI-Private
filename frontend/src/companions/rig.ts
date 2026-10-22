/**
 * Puppet rigs for the living companions. All coordinates are in the sprite's own pixels
 * (Ember, Astra, Gemini: 416x520; Star: the shipped 512x640 stand pose), measured on the art.
 * A rig names the pivots of a small bone hierarchy and the soft regions that each bone moves.
 */
export type CastId = 'star' | 'ember' | 'astra' | 'gemini'
export const CAST: readonly CastId[] = ['star', 'ember', 'astra', 'gemini']

export const BONE = {
  hips: 0, torso: 1, head: 2, hairL: 3, hairR: 4, armL: 5, armR: 6, legL: 7, legR: 8, tail: 9, earL: 10, earR: 11,
} as const
export const BONE_COUNT = 12
export type BoneIndex = typeof BONE[keyof typeof BONE]

export type Pt = readonly [number, number]
/** Centre x, centre y, radius x, radius y. */
export type Ellipse = readonly [number, number, number, number]
export type Region = { bone: BoneIndex; pivot: Pt; poly: readonly Pt[]; feather: number }
export type Anchor = { at: Pt; angle: number; size: number }

export type Rig = {
  id: CastId
  name: string
  image: string
  /** Same sprite with the eyes and mouth closed (inpainted); used only inside the eye/mouth ellipses. */
  closed: string
  /** Sprite without the character's own animal ears/tail, for the other animal form. */
  plain?: string
  size: Pt
  topY: number
  footY: number
  centerX: number
  neck: Pt
  waistY: number
  hemY: number
  hipL: Pt
  hipR: Pt
  shoulderL: Pt
  shoulderR: Pt
  head: Pt
  regions: readonly Region[]
  eyes: readonly [Ellipse, Ellipse]
  mouth: Ellipse
  cheeks: readonly [Pt, Pt]
  /** Where animal ears sit on the head (angle in radians, size in sprite px). */
  ears: readonly [Anchor, Anchor]
  /** Where an animal tail leaves the back of the skirt. */
  tailRoot: Pt
  /** Centre of the eyes line for study glasses; null when the art already wears glasses. */
  glasses: { at: Pt; width: number; angle: number } | null
  hands: readonly [Pt, Pt]
  ownEars: boolean
  ownTail: boolean
  /** Hair root and tip colours for ears and tails, outline colour, cushion colour, accent. */
  palette: { hair: string; tip: string; inner: string; outline: string; cushion: string; accent: string }
  /** Relative display height (Star is drawn a touch smaller: she is the shortest of the four). */
  height: number
}

const P = (x: number, y: number): Pt => [x, y]

export const RIGS: Readonly<Record<CastId, Rig>> = {
  star: {
    id: 'star', name: 'Star',
    image: './assets/mascot/poses/stand.png', closed: './assets/companions/star-closed.png',
    size: P(512, 640), topY: 140, footY: 608, centerX: 268,
    neck: P(266, 398), waistY: 455, hemY: 538, hipL: P(232, 540), hipR: P(308, 540),
    shoulderL: P(222, 438), shoulderR: P(318, 438), head: P(265, 300),
    regions: [
      { bone: BONE.hairL, pivot: P(150, 362), feather: 10, poly: [P(70, 352), P(130, 340), P(178, 372), P(178, 420), P(160, 470), P(130, 500), P(95, 505), P(70, 470), P(62, 410)] },
      { bone: BONE.hairR, pivot: P(382, 362), feather: 10, poly: [P(392, 340), P(450, 350), P(470, 410), P(462, 470), P(440, 500), P(405, 500), P(380, 450), P(372, 380)] },
      { bone: BONE.armL, pivot: P(222, 440), feather: 8, poly: [P(160, 470), P(205, 452), P(222, 480), P(212, 515), P(185, 522), P(162, 505)] },
      { bone: BONE.armR, pivot: P(318, 440), feather: 8, poly: [P(318, 452), P(368, 465), P(378, 505), P(352, 522), P(326, 512), P(316, 480)] },
    ],
    eyes: [[201, 346, 34, 31], [312, 343, 34, 31]], mouth: [257, 381, 16, 12],
    cheeks: [P(196, 382), P(322, 378)],
    ears: [{ at: P(168, 196), angle: -0.42, size: 92 }, { at: P(362, 192), angle: 0.42, size: 92 }],
    tailRoot: P(318, 526),
    glasses: { at: P(257, 346), width: 190, angle: -0.02 },
    hands: [P(190, 505), P(348, 505)],
    ownEars: false, ownTail: false,
    palette: { hair: '#2b2533', tip: '#e9b23c', inner: '#f4b7c0', outline: '#1b1418', cushion: '#e7b443', accent: '#f1c24a' },
    height: 0.94,
  },
  ember: {
    id: 'ember', name: 'Ember',
    image: './assets/companions/ember.png', closed: './assets/companions/ember-closed.png',
    size: P(416, 520), topY: 22, footY: 498, centerX: 212,
    neck: P(214, 250), waistY: 326, hemY: 393, hipL: P(188, 395), hipR: P(238, 395),
    shoulderL: P(160, 292), shoulderR: P(272, 296), head: P(208, 165),
    regions: [
      { bone: BONE.hairL, pivot: P(118, 168), feather: 12, poly: [P(78, 150), P(148, 168), P(146, 250), P(140, 305), P(112, 345), P(70, 368), P(44, 330), P(50, 260), P(62, 200)] },
      { bone: BONE.hairR, pivot: P(304, 168), feather: 12, poly: [P(296, 150), P(345, 178), P(378, 262), P(392, 340), P(380, 392), P(322, 392), P(300, 340), P(312, 260), P(292, 210)] },
      { bone: BONE.armL, pivot: P(158, 296), feather: 8, poly: [P(112, 330), P(150, 306), P(172, 318), P(165, 352), P(132, 376), P(104, 372)] },
      { bone: BONE.armR, pivot: P(274, 298), feather: 8, poly: [P(226, 296), P(286, 292), P(316, 330), P(304, 360), P(262, 372), P(230, 362)] },
    ],
    eyes: [[157, 205, 27, 25], [240, 186, 26, 27]], mouth: [201, 225, 13, 10],
    cheeks: [P(150, 230), P(258, 216)],
    ears: [{ at: P(118, 70), angle: -0.5, size: 92 }, { at: P(300, 60), angle: 0.45, size: 92 }],
    tailRoot: P(262, 388),
    glasses: null,
    hands: [P(118, 362), P(250, 346)],
    ownEars: false, ownTail: false,
    palette: { hair: '#d4602a', tip: '#f39a3c', inner: '#f6c1b0', outline: '#4a2116', cushion: '#8a3b2c', accent: '#c8463a' },
    height: 1,
  },
  astra: {
    id: 'astra', name: 'Astra',
    image: './assets/companions/astra.png', closed: './assets/companions/astra-closed.png',
    plain: './assets/companions/astra-plain.png',
    size: P(416, 520), topY: 40, footY: 490, centerX: 219,
    neck: P(214, 272), waistY: 345, hemY: 400, hipL: P(190, 400), hipR: P(246, 400),
    shoulderL: P(162, 304), shoulderR: P(266, 304), head: P(200, 170),
    regions: [
      { bone: BONE.hairL, pivot: P(128, 205), feather: 10, poly: [P(92, 180), P(150, 196), P(152, 290), P(128, 330), P(100, 325), P(84, 255)] },
      { bone: BONE.hairR, pivot: P(292, 192), feather: 10, poly: [P(266, 186), P(322, 178), P(334, 240), P(304, 268), P(270, 258)] },
      { bone: BONE.earL, pivot: P(112, 142), feather: 6, poly: [P(64, 84), P(128, 82), P(126, 134), P(100, 172), P(78, 160)] },
      { bone: BONE.earR, pivot: P(256, 118), feather: 6, poly: [P(204, 92), P(250, 34), P(268, 38), P(308, 112), P(290, 130), P(240, 122)] },
      { bone: BONE.tail, pivot: P(302, 404), feather: 6, poly: [P(294, 388), P(318, 330), P(332, 298), P(362, 290), P(388, 314), P(388, 346), P(368, 358), P(350, 342), P(342, 328), P(334, 362), P(332, 410), P(306, 420), P(290, 406)] },
      { bone: BONE.armL, pivot: P(162, 306), feather: 8, poly: [P(112, 332), P(156, 306), P(176, 320), P(162, 356), P(126, 368), P(108, 356)] },
      { bone: BONE.armR, pivot: P(266, 306), feather: 8, poly: [P(254, 310), P(292, 308), P(312, 348), P(298, 372), P(262, 362)] },
    ],
    eyes: [[166, 236, 27, 27], [241, 215, 31, 30]], mouth: [208, 252, 13, 10],
    cheeks: [P(152, 258), P(256, 240)],
    ears: [{ at: P(104, 108), angle: -0.55, size: 88 }, { at: P(262, 74), angle: 0.4, size: 88 }],
    tailRoot: P(262, 392),
    glasses: { at: P(204, 228), width: 150, angle: -0.26 },
    hands: [P(124, 356), P(300, 362)],
    ownEars: true, ownTail: true,
    palette: { hair: '#1d1a2c', tip: '#8f55d8', inner: '#c49af0', outline: '#140f1c', cushion: '#3b2f6b', accent: '#a978f0' },
    height: 1,
  },
  gemini: {
    id: 'gemini', name: 'Gemini',
    image: './assets/companions/gemini.png', closed: './assets/companions/gemini-closed.png',
    size: P(416, 520), topY: 18, footY: 501, centerX: 201,
    neck: P(204, 242), waistY: 322, hemY: 397, hipL: P(176, 398), hipR: P(226, 398),
    shoulderL: P(150, 292), shoulderR: P(256, 292), head: P(205, 150),
    regions: [
      { bone: BONE.hairL, pivot: P(104, 172), feather: 12, poly: [P(62, 160), P(126, 168), P(118, 260), P(112, 330), P(96, 372), P(46, 362), P(30, 300), P(44, 226)] },
      { bone: BONE.hairR, pivot: P(292, 178), feather: 14, poly: [P(284, 176), P(340, 198), P(386, 280), P(384, 370), P(330, 402), P(306, 372), P(302, 300), P(294, 262)] },
      { bone: BONE.armL, pivot: P(150, 294), feather: 8, poly: [P(102, 322), P(140, 300), P(158, 330), P(138, 368), P(108, 362)] },
      { bone: BONE.armR, pivot: P(256, 294), feather: 8, poly: [P(256, 318), P(292, 318), P(298, 366), P(270, 372), P(252, 352)] },
    ],
    eyes: [[140, 189, 27, 26], [223, 177, 32, 29]], mouth: [183, 218, 14, 10],
    cheeks: [P(132, 214), P(238, 202)],
    ears: [{ at: P(96, 66), angle: -0.5, size: 90 }, { at: P(296, 62), angle: 0.45, size: 90 }],
    tailRoot: P(252, 392),
    glasses: { at: P(183, 184), width: 156, angle: -0.12 },
    hands: [P(120, 352), P(276, 356)],
    ownEars: false, ownTail: false,
    palette: { hair: '#8fd3f4', tip: '#f4a3c4', inner: '#fbd0de', outline: '#4b2a33', cushion: '#3fb6b0', accent: '#5fd0c4' },
    height: 1,
  },
}

/** Figure height in sprite px (top of hair to the soles). */
export const figureHeight = (rig: Rig): number => rig.footY - rig.topY
