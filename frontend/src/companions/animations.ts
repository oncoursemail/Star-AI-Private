/**
 * The keyframed animation set. Angles in degrees on screen (y down, positive = clockwise); side views
 * face +x, so a negative thigh or arm angle swings the limb forward. F is the near (side) or screen-left
 * (front) limb, K the far or screen-right one.
 */
import type {BoneTracks, Clip, Track} from './clips'

/** The same cycle half a period later (for the other leg/arm). */
export function shift(track: Track, by = 0.5): number[] {
  const keys: [number, number][] = []
  for (let i = 0; i < track.length; i += 2) keys.push([((track[i] + by) % 1 + 1) % 1, track[i + 1]])
  keys.sort((a, b) => a[0] - b[0])
  return keys.flat()
}

// --- walk: contact, down, passing, up for each foot (F contact at 0, K contact at 0.5) ---
const walkThigh = [0, -28, 0.125, -20, 0.25, -2, 0.375, 14, 0.5, 22, 0.625, 24, 0.75, -10, 0.875, -30]
const walkShin = [0, 4, 0.125, 16, 0.25, 6, 0.375, 6, 0.5, 18, 0.625, 44, 0.75, 58, 0.875, 22]
const walkFoot = [0, -16, 0.125, 0, 0.25, 0, 0.375, 6, 0.5, 22, 0.625, 14, 0.75, 6, 0.875, -10]
const walkArm = [0, 20, 0.25, 2, 0.5, -20, 0.75, 2]
const walkFore = [0, -6, 0.25, -12, 0.5, -24, 0.75, -12]
/** One full cycle (two steps) covers this many model units of ground. */
export const WALK_STRIDE = 36
export const RUN_STRIDE = 74

export const CLIPS = {
  walk: {
    dur: 1, loop: true,
    bones: {
      thighF: {r: walkThigh}, shinF: {r: walkShin}, footF: {r: walkFoot},
      thighK: {r: shift(walkThigh)}, shinK: {r: shift(walkShin)}, footK: {r: shift(walkFoot)},
      armUF: {r: walkArm}, armLF: {r: walkFore}, armUK: {r: shift(walkArm)}, armLK: {r: shift(walkFore)},
      chest: {r: [0, 3, 0.25, 4.5, 0.5, 3, 0.75, 4.5]},
      hips: {r: [0, 1.5, 0.25, 0, 0.5, 1.5, 0.75, 0]},
      // The head counters the body's bob a beat late.
      head: {r: [0, -2, 0.125, 1.2, 0.25, 0.5, 0.375, -1.5, 0.5, -2, 0.625, 1.2, 0.75, 0.5, 0.875, -1.5]},
    },
  },
  run: {
    dur: 1, loop: true,
    bones: {
      thighF: {r: [0, -48, 0.15, -22, 0.3, 18, 0.45, 38, 0.6, 12, 0.75, -32, 0.9, -55]},
      shinF: {r: [0, 22, 0.15, 22, 0.3, 14, 0.45, 32, 0.6, 92, 0.75, 98, 0.9, 50]},
      footF: {r: [0, -12, 0.15, 0, 0.3, 10, 0.45, 32, 0.6, 22, 0.75, 8, 0.9, -6]},
      thighK: {r: shift([0, -48, 0.15, -22, 0.3, 18, 0.45, 38, 0.6, 12, 0.75, -32, 0.9, -55])},
      shinK: {r: shift([0, 22, 0.15, 22, 0.3, 14, 0.45, 32, 0.6, 92, 0.75, 98, 0.9, 50])},
      footK: {r: shift([0, -12, 0.15, 0, 0.3, 10, 0.45, 32, 0.6, 22, 0.75, 8, 0.9, -6])},
      armUF: {r: [0, 48, 0.5, -58]}, armLF: {r: [0, -72, 0.5, -98]},
      armUK: {r: [0, -58, 0.5, 48]}, armLK: {r: [0, -98, 0.5, -72]},
      chest: {r: [0, 12, 0.25, 14, 0.5, 12, 0.75, 14]},
      head: {r: [0, -6, 0.25, -4, 0.5, -6, 0.75, -4]},
      hips: {y: [0, 0, 0.15, 1.6, 0.3, 0, 0.45, -3.4, 0.5, 0, 0.65, 1.6, 0.8, 0, 0.95, -3.4]},
    },
  },
  hop: {
    dur: 1, loop: false,
    bones: {
      hips: {y: [0, 4.5, 0.12, -2, 0.5, -1, 0.85, 0, 1, 0]},
      chest: {r: [0, 16, 0.12, -6, 0.5, 6, 0.85, 2, 1, 8]},
      head: {r: [0, -6, 0.12, 4, 0.5, -2, 1, -4]},
      thighF: {r: [0, -52, 0.12, -8, 0.5, -64, 0.85, -22, 1, -14]},
      shinF: {r: [0, 88, 0.12, 6, 0.5, 104, 0.85, 20, 1, 12]},
      footF: {r: [0, -30, 0.12, 32, 0.5, 18, 0.85, -8, 1, -4]},
      thighK: {r: [0, -40, 0.12, 12, 0.5, -42, 0.85, 0, 1, 4]},
      shinK: {r: [0, 76, 0.12, 14, 0.5, 112, 0.85, 26, 1, 10]},
      footK: {r: [0, -20, 0.12, 34, 0.5, 26, 0.85, 2, 1, 0]},
      armUF: {r: [0, 42, 0.12, -150, 0.5, -118, 0.85, -60, 1, -24]}, armLF: {r: [0, 6, 0.12, -6, 0.5, -30, 1, -10]},
      armUK: {r: [0, 44, 0.12, -140, 0.5, -108, 0.85, -50, 1, -20]}, armLK: {r: [0, 6, 0.12, -6, 0.5, -30, 1, -10]},
      root: {sx: [0, 1.14, 0.12, 0.9, 0.3, 0.96, 0.5, 1, 1, 1], sy: [0, 0.86, 0.12, 1.12, 0.3, 1.04, 0.5, 1, 1, 1]},
    },
    slots: {lashF: [[0, 'squeeze' + 'F'], [0.12, 'openF'], [0.9, 'openF']], mouth: [[0, 'flat'], [0.12, 'wide'], [0.8, 'open']]},
  },
  reach: {
    dur: 0.45, loop: false,
    bones: {
      armUF: {r: [0, -20, 0.35, -92, 1, -80]}, armLF: {r: [0, -10, 0.35, 2, 1, -6]},
      armUK: {r: [0, 10, 0.35, 30, 1, 20]},
      chest: {r: [0, 4, 0.35, 14, 1, 10]},
      thighF: {r: [0, -10, 0.35, -26, 1, -20]}, shinF: {r: [0, 6, 0.35, 10, 1, 8]},
      thighK: {r: [0, 6, 0.35, 22, 1, 18]}, shinK: {r: [0, 8, 0.35, 16, 1, 12]}, footK: {r: [0, 0, 0.35, 12, 1, 8]},
    },
    slots: {mouth: [[0, 'wide']], lashF: [[0, 'happyF']]},
  },
  kissGive: {
    dur: 1.6, loop: false,
    bones: {
      chest: {r: [0, 0, 0.22, 16, 0.75, 16, 1, 2]},
      neck: {r: [0, 0, 0.22, 8, 0.75, 8, 1, 0]},
      head: {r: [0, 0, 0.22, 6, 0.75, 6, 1, 0]},
      thighK: {r: [0, 0, 0.22, 28, 0.75, 28, 1, 0]}, shinK: {r: [0, 0, 0.22, 62, 0.75, 62, 1, 0]}, footK: {r: [0, 0, 0.22, 20, 0.75, 20, 1, 0]},
      thighF: {r: [0, 0, 0.22, -6, 0.75, -6, 1, 0]},
      armUF: {r: [0, 0, 0.22, 34, 0.75, 34, 1, 0]}, armLF: {r: [0, 0, 0.22, 34, 0.75, 34, 1, 0]},
      armUK: {r: [0, 0, 0.22, 30, 0.75, 30, 1, 0]}, armLK: {r: [0, 0, 0.22, 30, 0.75, 30, 1, 0]},
    },
    slots: {lashF: [[0, 'openF'], [0.18, 'closedF'], [0.85, 'happyF']], mouth: [[0, 'smile'], [0.18, 'kiss'], [0.85, 'smile']]},
  },
  // Two-character moments in the front view are written with the partner on the right (+x);
  // the "M" versions (mirrored below) are for a partner on the left.
  hugGive: {
    dur: 2.2, loop: false,
    bones: {
      armUK: {r: [0, 0, 0.15, -122, 0.3, -112, 0.85, -112, 1, -6]}, armLK: {r: [0, 0, 0.15, 28, 0.3, 62, 0.85, 62, 1, 0]},
      armUF: {r: [0, 0, 0.3, -32, 0.85, -32, 1, 0]}, armLF: {r: [0, 0, 0.3, -86, 0.85, -86, 1, 0]},
      chest: {r: [0, 0, 0.3, 6, 0.5, 8, 0.7, 6, 0.85, 6, 1, 0]},
      head: {r: [0, 0, 0.3, 11, 0.85, 11, 1, 0]},
      hips: {x: [0, 0, 0.3, 1.2, 0.85, 1.2, 1, 0]},
      root: {sy: [0, 1, 0.45, 0.97, 0.55, 1, 1, 1], sx: [0, 1, 0.45, 1.03, 0.55, 1, 1, 1]},
    },
    slots: {lashF: [[0, 'openF'], [0.25, 'happyF'], [0.95, 'openF']], lashK: [[0, 'openK'], [0.25, 'happyK'], [0.95, 'openK']], mouth: [[0, 'wide'], [0.25, 'cat'], [0.95, 'smile']]},
  },
  hugGet: {
    dur: 2.2, loop: false,
    bones: {
      armUK: {r: [0, 0, 0.2, -55, 0.85, -55, 1, 0]}, armLK: {r: [0, 0, 0.2, -30, 0.85, -30, 1, 0]},
      armUF: {r: [0, 0, 0.2, -20, 0.85, -20, 1, 0]}, armLF: {r: [0, 0, 0.2, -72, 0.85, -72, 1, 0]},
      head: {r: [0, 0, 0.3, 8, 0.85, 8, 1, 0]}, chest: {r: [0, 0, 0.3, 4, 0.85, 4, 1, 0]},
    },
    slots: {lashF: [[0, 'openF'], [0.22, 'happyF']], lashK: [[0, 'openK'], [0.22, 'happyK']], mouth: [[0, 'o'], [0.22, 'cat']]},
  },
  highfive: {
    dur: 1.1, loop: false,
    bones: {
      armUK: {r: [0, 0, 0.3, -116, 0.42, -102, 0.7, -102, 1, 0]}, armLK: {r: [0, 0, 0.3, -22, 0.42, 0, 0.7, 0, 1, 0]},
      armUF: {r: [0, 0, 0.42, 20, 0.7, 14, 1, 0]},
      chest: {r: [0, 0, 0.3, -4, 0.42, 5, 0.7, 3, 1, 0]},
      hips: {y: [0, 0, 0.3, 1.5, 0.45, -3, 0.6, 0, 1, 0]},
      root: {sy: [0, 1, 0.3, 0.94, 0.45, 1.06, 0.6, 1, 1, 1]},
    },
    slots: {lashF: [[0, 'openF'], [0.42, 'squeezeF'], [0.6, 'happyF']], lashK: [[0, 'openK'], [0.42, 'squeezeK'], [0.6, 'happyK']], mouth: [[0, 'smile'], [0.3, 'wide']]},
  },
  kissGet: {
    dur: 1.6, loop: false,
    bones: {
      head: {r: [0, 0, 0.3, 6, 0.75, 6, 1, 0]},
      armUF: {r: [0, 0, 0.3, -22, 0.75, -22, 1, -6]}, armLF: {r: [0, 0, 0.3, -112, 0.75, -112, 1, -20]},
      armUK: {r: [0, 0, 0.3, 22, 0.75, 22, 1, 6]}, armLK: {r: [0, 0, 0.3, 112, 0.75, 112, 1, 20]},
      root: {sy: [0, 1, 0.3, 1.04, 0.45, 1, 1, 1]},
    },
    slots: {lashF: [[0, 'openF'], [0.3, 'squeezeF'], [0.6, 'happyF']], lashK: [[0, 'openK'], [0.3, 'squeezeK'], [0.6, 'happyK']], mouth: [[0, 'smile'], [0.3, 'o'], [0.6, 'cat']]},
  },
  // --- front view ---
  idle: {
    dur: 3.6, loop: true,
    bones: {
      armUF: {r: [0, 4, 0.5, 6.5]}, armUK: {r: [0, -4, 0.5, -6.5]},
      armLF: {r: [0, 3, 0.5, 5]}, armLK: {r: [0, -3, 0.5, -5]},
      head: {r: [0, 0, 0.3, 2.2, 0.7, -1.4]},
      hips: {x: [0, 0, 0.5, 0.35]},
    },
  },
  lookAround: {
    dur: 2.6, loop: false,
    bones: {
      head: {r: [0, 0, 0.15, 7, 0.45, 7, 0.6, -7, 0.88, -7, 1, 0]},
      pupilF: {x: [0, 0, 0.15, 0.9, 0.45, 0.9, 0.6, -0.9, 0.88, -0.9, 1, 0]},
      pupilK: {x: [0, 0, 0.15, 0.9, 0.45, 0.9, 0.6, -0.9, 0.88, -0.9, 1, 0]},
      chest: {r: [0, 0, 0.15, 2, 0.6, -2, 1, 0]},
    },
  },
  stretch: {
    dur: 2.2, loop: false, armsUp: true,
    bones: {
      armUF: {r: [0, 0, 0.25, 124, 0.7, 130, 1, 0]}, armLF: {r: [0, 0, 0.25, 12, 0.7, 16, 1, 0]},
      armUK: {r: [0, 0, 0.25, -124, 0.7, -130, 1, 0]}, armLK: {r: [0, 0, 0.25, -12, 0.7, -16, 1, 0]},
      chest: {sy: [0, 1, 0.3, 1.05, 0.7, 1.06, 1, 1]},
      root: {sy: [0, 1, 0.3, 1.03, 0.7, 1.03, 1, 1]},
      head: {r: [0, 0, 0.4, -3, 0.7, 3, 1, 0]},
    },
    slots: {lashF: [[0, 'openF'], [0.22, 'happyF'], [0.85, 'openF']], lashK: [[0, 'openK'], [0.22, 'happyK'], [0.85, 'openK']], mouth: [[0, 'smile'], [0.22, 'o'], [0.85, 'smile']]},
  },
  sway: {
    dur: 2.4, loop: false,
    bones: {
      hips: {x: [0, 0, 0.25, -1.3, 0.75, 1.3, 1, 0], r: [0, 0, 0.25, 3, 0.75, -3, 1, 0]},
      head: {r: [0, 0, 0.25, -5, 0.75, 5, 1, 0]},
      armUF: {r: [0, 0, 0.25, 8, 0.75, -2, 1, 0]}, armUK: {r: [0, 0, 0.25, 2, 0.75, -8, 1, 0]},
    },
    slots: {mouth: [[0, 'cat'], [0.95, 'smile']]},
  },
  talk: {
    dur: 2.4, loop: true,
    bones: {
      head: {r: [0, 0, 0.25, 3, 0.5, -1.5, 0.75, 2.5], y: [0, 0, 0.25, -0.5, 0.5, 0, 0.75, -0.4]},
      armUK: {r: [0, -6, 0.3, -38, 0.6, -24, 0.85, -10]}, armLK: {r: [0, -10, 0.3, -48, 0.6, -36, 0.85, -14]},
      browF: {y: [0, 0, 0.3, -0.7, 0.6, 0]}, browK: {y: [0, 0, 0.3, -0.7, 0.6, 0]},
      chest: {r: [0, 0, 0.3, 1.5, 0.7, -1]},
    },
  },
  listen: {
    dur: 3, loop: true,
    bones: {head: {r: [0, 6, 0.4, 8, 0.55, 5.5, 0.7, 8]}, pupilF: {x: [0, 0.5]}, pupilK: {x: [0, 0.5]}, armUF: {r: [0, 4]}, armUK: {r: [0, -4]}},
  },
  shy: {
    dur: 1.6, loop: false,
    bones: {
      armUF: {r: [0, 0, 0.3, -24, 1, -24]}, armLF: {r: [0, 0, 0.3, -64, 1, -64]},
      armUK: {r: [0, 0, 0.3, 24, 1, 24]}, armLK: {r: [0, 0, 0.3, 64, 1, 64]},
      head: {r: [0, 0, 0.3, 7, 0.6, 4, 1, 7]},
      footF: {r: [0, 0, 0.4, 14, 0.6, 0, 0.8, 14, 1, 0]},
    },
    slots: {lashF: [[0, 'happyF'], [0.45, 'halfF']], lashK: [[0, 'happyK'], [0.45, 'halfK']], mouth: [[0, 'cat']]},
  },
  cheer: {
    dur: 0.5, loop: true, interp: 'ease', armsUp: true,
    bones: {
      hips: {y: [0, 0, 0.5, -8, 1, 0]},
      root: {sy: [0, 0.88, 0.15, 1.06, 0.5, 1, 0.85, 1.04, 1, 0.88], sx: [0, 1.1, 0.15, 0.95, 0.5, 1, 1, 1.1]},
      armUF: {r: [0, 112, 0.5, 128, 1, 112]}, armUK: {r: [0, -112, 0.5, -128, 1, -112]},
      armLF: {r: [0, 20, 0.5, 8, 1, 20]}, armLK: {r: [0, -20, 0.5, -8, 1, -20]},
      thighF: {r: [0, 0, 0.5, 10, 1, 0]}, shinF: {r: [0, 0, 0.5, -18, 1, 0]},
      thighK: {r: [0, 0, 0.5, -10, 1, 0]}, shinK: {r: [0, 0, 0.5, 18, 1, 0]},
    },
    slots: {lashF: [[0, 'happyF']], lashK: [[0, 'happyK']], mouth: [[0, 'wide']]},
  },
  worried: {
    dur: 1.8, loop: true,
    bones: {
      armUF: {r: [0, -18]}, armLF: {r: [0, -112, 0.5, -118]}, armUK: {r: [0, 18]}, armLK: {r: [0, 112, 0.5, 118]},
      head: {r: [0, -3, 0.5, -5]}, browF: {r: [0, -14], y: [0, -0.5]}, browK: {r: [0, 14], y: [0, -0.5]},
      root: {sy: [0, 0.98]},
    },
    slots: {mouth: [[0, 'frown']]},
  },
  startle: {
    dur: 0.7, loop: false,
    bones: {
      hips: {y: [0, 0, 0.18, -6, 0.4, 0, 1, 0]},
      root: {sy: [0, 0.8, 0.18, 1.1, 0.4, 0.92, 0.6, 1, 1, 1], sx: [0, 1.15, 0.18, 0.94, 0.4, 1.05, 0.6, 1, 1, 1]},
      armUF: {r: [0, 0, 0.18, 70, 0.6, 30, 1, 0]}, armUK: {r: [0, 0, 0.18, -70, 0.6, -30, 1, 0]},
      armLF: {r: [0, 0, 0.18, 30, 1, 0]}, armLK: {r: [0, 0, 0.18, -30, 1, 0]},
    },
    slots: {lashF: [[0, 'squeezeF'], [0.45, 'openF']], lashK: [[0, 'squeezeK'], [0.45, 'openK']], mouth: [[0, 'o'], [0.6, 'smile']]},
  },
  poked: {
    dur: 0.8, loop: false,
    bones: {
      chest: {r: [0, 0, 0.12, -9, 0.5, -3, 1, 0]},
      head: {r: [0, 0, 0.12, -12, 0.5, -4, 1, 0]},
      root: {sx: [0, 1, 0.08, 0.88, 0.25, 1.06, 0.45, 1, 1, 1], sy: [0, 1, 0.08, 1.1, 0.25, 0.95, 0.45, 1, 1, 1]},
      armUF: {r: [0, 0, 0.12, 40, 0.6, 10, 1, 0]}, armLF: {r: [0, 0, 0.12, -40, 0.6, -10, 1, 0]},
      armUK: {r: [0, 0, 0.12, -40, 0.6, -10, 1, 0]}, armLK: {r: [0, 0, 0.12, 40, 0.6, 10, 1, 0]},
      browF: {y: [0, 0, 0.12, -1, 1, 0]}, browK: {y: [0, 0, 0.12, -1, 1, 0]},
    },
    slots: {lashF: [[0, 'squeezeF'], [0.55, 'openF']], lashK: [[0, 'squeezeK'], [0.55, 'openK']], mouth: [[0, 'o'], [0.6, 'cat']]},
  },
  dangle: {
    dur: 0.56, loop: true,
    bones: {
      thighF: {r: [0, -16, 0.5, 14]}, shinF: {r: [0, 36, 0.5, 4]}, footF: {r: [0, 10, 0.5, -10]},
      thighK: {r: [0, 14, 0.5, -16]}, shinK: {r: [0, -4, 0.5, -36]}, footK: {r: [0, 10, 0.5, -10]},
      armUF: {r: [0, 34, 0.5, 46]}, armLF: {r: [0, 20, 0.5, 34]},
      armUK: {r: [0, -46, 0.5, -34]}, armLK: {r: [0, -34, 0.5, -20]},
      head: {r: [0, -3, 0.5, 3]},
    },
    slots: {mouth: [[0, 'wide']]},
  },
  fall: {
    dur: 0.4, loop: true, armsUp: true,
    bones: {
      armUF: {r: [0, 115, 0.5, 130]}, armUK: {r: [0, -130, 0.5, -115]}, armLF: {r: [0, 20, 0.5, -10]}, armLK: {r: [0, 10, 0.5, -20]},
      thighF: {r: [0, -12, 0.5, 10]}, shinF: {r: [0, 20, 0.5, 0]}, thighK: {r: [0, 10, 0.5, -12]}, shinK: {r: [0, 0, 0.5, -20]},
    },
    slots: {lashF: [[0, 'squeezeF']], lashK: [[0, 'squeezeK']], mouth: [[0, 'o']]},
  },
  groom: {
    dur: 0.7, loop: true,
    bones: {
      armUF: {r: [0, -36, 0.5, -42]}, armLF: {r: [0, -118, 0.5, -132]},
      head: {r: [0, -8, 0.5, -10]},
      handF: {r: [0, -10, 0.5, 10]},
    },
    slots: {handF: [[0, 'fistF']], lashF: [[0, 'happyF']], lashK: [[0, 'happyK']], mouth: [[0, 'cat']]},
  },
  wag: {
    dur: 0.42, loop: true, interp: 'ease',
    bones: {
      hips: {y: [0, 0, 0.5, -2.4, 1, 0]},
      root: {sy: [0, 0.95, 0.25, 1.03, 0.5, 1, 1, 0.95]},
      armUF: {r: [0, -30]}, armLF: {r: [0, -104]}, armUK: {r: [0, 30]}, armLK: {r: [0, 104]},
      head: {r: [0, -4, 0.5, 4, 1, -4]},
    },
    slots: {handF: [[0, 'fistF']], handK: [[0, 'fistK']], lashF: [[0, 'happyF']], lashK: [[0, 'happyK']], mouth: [[0, 'wide']]},
  },
  sit: {
    dur: 4, loop: true,
    bones: {
      hips: {y: [0, 12.5]},
      thighF: {r: [0, 28], sy: [0, 0.42]}, shinF: {r: [0, -46], sy: [0, 0.9]}, footF: {r: [0, 18]},
      thighK: {r: [0, -28], sy: [0, 0.42]}, shinK: {r: [0, 46], sy: [0, 0.9]}, footK: {r: [0, -18]},
      armUF: {r: [0, -10, 0.5, -12]}, armLF: {r: [0, -34, 0.5, -36]}, armUK: {r: [0, 10, 0.5, 12]}, armLK: {r: [0, 34, 0.5, 36]},
      head: {r: [0, 2, 0.5, -2]},
      skirt0: {sx: [0, 1.12]},
    },
  },
  flop: {
    dur: 1.2, loop: true,
    bones: {
      hips: {y: [0, 12.5]},
      thighF: {r: [0, 44], sy: [0, 0.4]}, shinF: {r: [0, -30], sy: [0, 0.92]}, footF: {r: [0, 24]},
      thighK: {r: [0, -44], sy: [0, 0.4]}, shinK: {r: [0, 30], sy: [0, 0.92]}, footK: {r: [0, -24]},
      armUF: {r: [0, 42]}, armLF: {r: [0, -20]}, armUK: {r: [0, -42]}, armLK: {r: [0, 20]},
      chest: {sy: [0, 0.98, 0.5, 1.04]}, head: {r: [0, -5, 0.5, -3], y: [0, 0, 0.5, -0.5]},
      skirt0: {sx: [0, 1.15]},
    },
    slots: {lashF: [[0, 'halfF']], lashK: [[0, 'halfK']], mouth: [[0, 'open']]},
  },
  sleep: {
    dur: 4.6, loop: true,
    bones: {
      hips: {y: [0, 12.5]},
      thighF: {r: [0, 28], sy: [0, 0.42]}, shinF: {r: [0, -46], sy: [0, 0.9]}, footF: {r: [0, 18]},
      thighK: {r: [0, -28], sy: [0, 0.42]}, shinK: {r: [0, 46], sy: [0, 0.9]}, footK: {r: [0, -18]},
      armUF: {r: [0, -14]}, armLF: {r: [0, -40]}, armUK: {r: [0, 14]}, armLK: {r: [0, 40]},
      chest: {r: [0, 3], sy: [0, 1, 0.45, 1.03]},
      head: {r: [0, 13, 0.45, 15], y: [0, 1, 0.45, 1.6]},
      skirt0: {sx: [0, 1.12]},
    },
    slots: {lashF: [[0, 'closedF']], lashK: [[0, 'closedK']], mouth: [[0, 'o']]},
  },
  study: {
    dur: 3, loop: true,
    bones: {
      hips: {y: [0, 12.5]},
      thighF: {r: [0, 28], sy: [0, 0.42]}, shinF: {r: [0, -46], sy: [0, 0.9]}, footF: {r: [0, 18]},
      thighK: {r: [0, -28], sy: [0, 0.42]}, shinK: {r: [0, 46], sy: [0, 0.9]}, footK: {r: [0, -18]},
      armUF: {r: [0, -26], sy: [0, 0.86]}, armLF: {r: [0, -64]}, armUK: {r: [0, 26], sy: [0, 0.86]}, armLK: {r: [0, 64]},
      head: {r: [0, 3, 0.5, 5], y: [0, 0.6]},
      skirt0: {sx: [0, 1.12]},
    },
  },
  nap: {
    dur: 4.8, loop: true,
    bones: {
      hips: {y: [0, 12.5]},
      thighF: {r: [0, 28], sy: [0, 0.42]}, shinF: {r: [0, -46], sy: [0, 0.9]}, footF: {r: [0, 18]},
      thighK: {r: [0, -28], sy: [0, 0.42]}, shinK: {r: [0, 46], sy: [0, 0.9]}, footK: {r: [0, -18]},
      armUF: {r: [0, -40], sy: [0, 0.8]}, armLF: {r: [0, -86]}, armUK: {r: [0, 40], sy: [0, 0.8]}, armLK: {r: [0, 86]},
      chest: {r: [0, 2], y: [0, 1.5], sy: [0, 1, 0.45, 1.03]},
      head: {r: [0, 10, 0.45, 11], y: [0, 4.5, 0.45, 5]},
      skirt0: {sx: [0, 1.12]},
    },
    slots: {lashF: [[0, 'closedF']], lashK: [[0, 'closedK']], mouth: [[0, 'o']]},
  },
} satisfies Record<string, Clip>

const swapSide = (name: string) => name.replace(/([FK])(\d*)$/, (_, side: string, n: string) => (side === 'F' ? 'K' : 'F') + n)
/** The same clip for the other side: F and K swap, turns and sideways moves flip. */
export function mirrorClip(clip: Clip): Clip {
  const bones: Record<string, BoneTracks> = {}
  for (const [name, t] of Object.entries(clip.bones)) {
    const neg = (tr?: Track) => tr && tr.map((v, i) => (i % 2 ? -v : v))
    bones[swapSide(name)] = {...t, r: neg(t.r), x: neg(t.x)}
  }
  const slots: Record<string, (readonly [number, string | null])[]> = {}
  for (const [name, keys] of Object.entries(clip.slots ?? {})) slots[swapSide(name)] = keys.map(([t, v]) => [t, v && swapSide(v)] as const)
  return {...clip, bones, slots}
}

export const MIRRORED = {
  hugGive: mirrorClip(CLIPS.hugGive),
  hugGet: mirrorClip(CLIPS.hugGet),
  highfive: mirrorClip(CLIPS.highfive),
  kissGet: mirrorClip(CLIPS.kissGet),
}

export type ClipName = keyof typeof CLIPS
