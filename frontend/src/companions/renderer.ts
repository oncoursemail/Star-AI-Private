/**
 * WebGL2 renderer for the puppets: one skinned mesh per character (12-bone linear blend skinning in the
 * vertex shader), eye/mouth ellipses blended from the inpainted closed-face sprite, and one batched
 * quad pass per layer for accessories, props and particles from the hand-drawn atlas.
 */
import {BONE, BONE_COUNT, figureHeight} from './rig'
import type {CastId, Ellipse, Rig} from './rig'
import {buildPuppetMesh} from './mesh'
import type {PuppetMesh} from './mesh'
import {apply, computeBones, rootMatrix} from './pose'
import type {Frame} from './animator'
import {buildAtlas, slotKey} from './props'
import type {Atlas, Slot} from './props'

const PUPPET_VS = `#version 300 es
in vec2 aPos; in vec2 aUv; in vec4 aW0; in vec4 aW1; in vec4 aW2;
uniform vec3 uA[${BONE_COUNT}]; uniform vec3 uB[${BONE_COUNT}];
uniform vec4 uView;
out vec2 vUv;
void main() {
  vec3 h = vec3(aPos, 1.0);
  float w[${BONE_COUNT}] = float[${BONE_COUNT}](aW0.x, aW0.y, aW0.z, aW0.w, aW1.x, aW1.y, aW1.z, aW1.w, aW2.x, aW2.y, aW2.z, aW2.w);
  vec2 p = vec2(0.0);
  for (int i = 0; i < ${BONE_COUNT}; i++) { if (w[i] > 0.0) p += w[i] * vec2(dot(uA[i], h), dot(uB[i], h)); }
  vUv = aUv;
  gl_Position = vec4((p.x - uView.z) * uView.x - 1.0, 1.0 - (p.y - uView.w) * uView.y, 0.0, 1.0);
}`
const PUPPET_FS = `#version 300 es
precision mediump float;
in vec2 vUv; out vec4 color;
uniform sampler2D uTex; uniform sampler2D uAlt;
uniform vec4 uEyeL; uniform vec4 uEyeR; uniform vec4 uMouth;
uniform float uEyes; uniform float uMouthClosed; uniform float uAlpha;
float inside(vec4 e) { vec2 d = (vUv - e.xy) * e.zw; return 1.0 - smoothstep(0.78, 0.96, length(d)); }
void main() {
  vec4 c = texture(uTex, vUv);
  float k = max(max(inside(uEyeL), inside(uEyeR)) * uEyes, inside(uMouth) * uMouthClosed);
  if (k > 0.001) c = mix(c, texture(uAlt, vUv), k);
  color = c * uAlpha;
}`
const SPRITE_VS = `#version 300 es
in vec2 aPos; in vec2 aUv; in float aAlpha;
uniform vec4 uView;
out vec2 vUv; out float vAlpha;
void main() { vUv = aUv; vAlpha = aAlpha; gl_Position = vec4((aPos.x - uView.z) * uView.x - 1.0, 1.0 - (aPos.y - uView.w) * uView.y, 0.0, 1.0); }`
const SPRITE_FS = `#version 300 es
precision mediump float;
in vec2 vUv; in float vAlpha; out vec4 color;
uniform sampler2D uTex;
void main() { color = texture(uTex, vUv) * vAlpha; }`

type Puppet = {
  rig: Rig
  mesh: PuppetMesh
  vao: WebGLVertexArrayObject
  count: number
  base: WebGLTexture
  closed: WebGLTexture
  plain: WebGLTexture | null
}

export type Particle = { item: string; x: number; y: number; vx: number; vy: number; age: number; life: number; size: number; spin: number; kind: 'float' | 'pop' | 'fall' | 'burst' | 'drift' }

export type DrawCharacter = { id: CastId; frame: Frame; z: number }

function compile(gl: WebGL2RenderingContext, vs: string, fs: string): WebGLProgram {
  const program = gl.createProgram() as WebGLProgram
  for (const [type, source] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]] as const) {
    const shader = gl.createShader(type) as WebGLShader
    gl.shaderSource(shader, source)
    gl.compileShader(shader)
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error('Companion shader: ' + gl.getShaderInfoLog(shader))
    gl.attachShader(program, shader)
  }
  gl.linkProgram(program)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Companion program: ' + gl.getProgramInfoLog(program))
  return program
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.decoding = 'async'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('Companion art missing: ' + src))
    image.src = src
  })
}

/** Summed-area table of alpha so the mesh builder can drop fully transparent cells cheaply. */
function opacityTest(image: HTMLImageElement): (x0: number, y0: number, x1: number, y1: number) => boolean {
  const w = image.naturalWidth, h = image.naturalHeight
  const canvas = document.createElement('canvas')
  canvas.width = w; canvas.height = h
  const ctx = canvas.getContext('2d', {willReadFrequently: true})
  if (!ctx) return () => true
  ctx.drawImage(image, 0, 0)
  const data = ctx.getImageData(0, 0, w, h).data
  const sat = new Uint32Array((w + 1) * (h + 1))
  for (let y = 0; y < h; y++) {
    let row = 0
    for (let x = 0; x < w; x++) {
      row += data[(y * w + x) * 4 + 3] > 6 ? 1 : 0
      sat[(y + 1) * (w + 1) + x + 1] = sat[y * (w + 1) + x + 1] + row
    }
  }
  return (x0, y0, x1, y1) => {
    const a = Math.max(0, Math.floor(x0)), b = Math.max(0, Math.floor(y0)), c = Math.min(w, Math.ceil(x1)), d = Math.min(h, Math.ceil(y1))
    if (c <= a || d <= b) return false
    return sat[d * (w + 1) + c] - sat[b * (w + 1) + c] - sat[d * (w + 1) + a] + sat[b * (w + 1) + a] > 0
  }
}

const FLOATS = 5   // x, y, u, v, alpha per sprite vertex

export class CompanionRenderer {
  readonly gl: WebGL2RenderingContext
  private puppetProgram: WebGLProgram
  private spriteProgram: WebGLProgram
  private puppets = new Map<CastId, Puppet>()
  private atlas: Atlas | null = null
  private atlasTexture: WebGLTexture | null = null
  private spriteVao: WebGLVertexArrayObject
  private spriteBuffer: WebGLBuffer
  private spriteData = new Float32Array(6 * FLOATS * 1200)
  private spriteCount = 0
  private width = 1
  private height = 1
  private originX = 0
  private originY = 0
  private loc: Record<string, WebGLUniformLocation | null> = {}
  private bones = new Float32Array(BONE_COUNT * 6)
  private boneA = new Float32Array(BONE_COUNT * 3)
  private boneB = new Float32Array(BONE_COUNT * 3)
  particles: Particle[] = []
  private buffers: WebGLBuffer[] = []

  static create(canvas: HTMLCanvasElement): CompanionRenderer | null {
    const gl = canvas.getContext('webgl2', {alpha: true, premultipliedAlpha: true, antialias: true, powerPreference: 'low-power', preserveDrawingBuffer: false})
    if (!gl) return null
    try { return new CompanionRenderer(gl) } catch { return null }
  }

  private constructor(gl: WebGL2RenderingContext) {
    this.gl = gl
    this.puppetProgram = compile(gl, PUPPET_VS, PUPPET_FS)
    this.spriteProgram = compile(gl, SPRITE_VS, SPRITE_FS)
    for (const name of ['uA', 'uB', 'uView', 'uTex', 'uAlt', 'uEyeL', 'uEyeR', 'uMouth', 'uEyes', 'uMouthClosed', 'uAlpha'])
      this.loc[name] = gl.getUniformLocation(this.puppetProgram, name)
    this.loc.sView = gl.getUniformLocation(this.spriteProgram, 'uView')
    this.loc.sTex = gl.getUniformLocation(this.spriteProgram, 'uTex')
    this.spriteVao = gl.createVertexArray() as WebGLVertexArrayObject
    this.spriteBuffer = gl.createBuffer() as WebGLBuffer
    gl.bindVertexArray(this.spriteVao)
    gl.bindBuffer(gl.ARRAY_BUFFER, this.spriteBuffer)
    gl.bufferData(gl.ARRAY_BUFFER, this.spriteData.byteLength, gl.DYNAMIC_DRAW)
    const stride = FLOATS * 4
    const attrib = (name: string, size: number, offset: number) => {
      const at = gl.getAttribLocation(this.spriteProgram, name)
      gl.enableVertexAttribArray(at)
      gl.vertexAttribPointer(at, size, gl.FLOAT, false, stride, offset)
    }
    attrib('aPos', 2, 0); attrib('aUv', 2, 8); attrib('aAlpha', 1, 16)
    gl.bindVertexArray(null)
    gl.enable(gl.BLEND)
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA)
    gl.disable(gl.DEPTH_TEST)
  }

  private texture(source: TexImageSource): WebGLTexture {
    const gl = this.gl
    const texture = gl.createTexture() as WebGLTexture
    gl.bindTexture(gl.TEXTURE_2D, texture)
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source)
    gl.generateMipmap(gl.TEXTURE_2D)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    return texture
  }

  async load(rigs: readonly Rig[]): Promise<void> {
    const gl = this.gl
    this.atlas = buildAtlas(rigs)
    this.atlasTexture = this.texture(this.atlas.canvas)
    await Promise.all(rigs.map(async rig => {
      const [base, closed, plain] = await Promise.all([loadImage(rig.image), loadImage(rig.closed), rig.plain ? loadImage(rig.plain) : Promise.resolve(null)])
      const mesh = buildPuppetMesh(rig, 9, opacityTest(base))
      const vao = gl.createVertexArray() as WebGLVertexArrayObject
      gl.bindVertexArray(vao)
      const buffer = (data: Float32Array, name: string, size: number) => {
        const b = gl.createBuffer() as WebGLBuffer; this.buffers.push(b)
        gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW)
        const at = gl.getAttribLocation(this.puppetProgram, name)
        gl.enableVertexAttribArray(at); gl.vertexAttribPointer(at, size, gl.FLOAT, false, 0, 0)
      }
      buffer(mesh.positions, 'aPos', 2)
      buffer(mesh.uvs, 'aUv', 2)
      const wb = gl.createBuffer() as WebGLBuffer; this.buffers.push(wb); gl.bindBuffer(gl.ARRAY_BUFFER, wb); gl.bufferData(gl.ARRAY_BUFFER, mesh.weights, gl.STATIC_DRAW)
      for (let i = 0; i < 3; i++) {
        const at = gl.getAttribLocation(this.puppetProgram, 'aW' + i)
        gl.enableVertexAttribArray(at); gl.vertexAttribPointer(at, 4, gl.FLOAT, false, BONE_COUNT * 4, i * 16)
      }
      const ib = gl.createBuffer() as WebGLBuffer; this.buffers.push(ib); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, mesh.indices, gl.STATIC_DRAW)
      gl.bindVertexArray(null)
      this.puppets.set(rig.id, {
        rig, mesh, vao, count: mesh.indices.length,
        base: this.texture(base), closed: this.texture(closed), plain: plain ? this.texture(plain) : null,
      })
    }))
  }

  get ready() { return this.puppets.size > 0 && !!this.atlas }

  /** The canvas shows the stage rectangle (originX, originY, cssWidth, cssHeight). */
  resize(cssWidth: number, cssHeight: number, dpr: number, originX = 0, originY = 0) {
    const canvas = this.gl.canvas as HTMLCanvasElement
    const w = Math.max(1, Math.round(cssWidth * dpr)), h = Math.max(1, Math.round(cssHeight * dpr))
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h }
    this.width = cssWidth; this.height = cssHeight; this.originX = originX; this.originY = originY
  }

  /** Stage point of a sprite point on a bone (for bubbles, particles and hit boxes). */
  point(id: CastId, frame: Frame, bone: number, x: number, y: number): [number, number] {
    const puppet = this.puppets.get(id)
    if (!puppet) return [frame.pose.x, frame.pose.y]
    computeBones(puppet.rig, frame.pose, this.bones)
    return apply(this.bones.subarray(bone * 6, bone * 6 + 6), x, y)
  }

  render(characters: readonly DrawCharacter[], dt: number) {
    const gl = this.gl
    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)
    if (!this.ready) return
    const order = [...characters].sort((a, b) => a.z - b.z)
    for (const c of order) {
      const puppet = this.puppets.get(c.id)
      if (!puppet || c.frame.alpha <= 0.01) continue
      computeBones(puppet.rig, c.frame.pose, this.bones)
      this.beginSprites(); this.backLayer(puppet, c.frame); this.flushSprites()
      this.drawPuppet(puppet, c.frame)
      this.beginSprites(); this.frontLayer(puppet, c.frame); this.flushSprites()
    }
    this.beginSprites(); this.stepParticles(dt); this.flushSprites()
  }

  // ------------------------------------------------------------ puppet

  private drawPuppet(puppet: Puppet, frame: Frame) {
    const gl = this.gl
    const loc = this.loc
    gl.useProgram(this.puppetProgram)
    for (let i = 0; i < BONE_COUNT; i++) {
      const m = this.bones.subarray(i * 6, i * 6 + 6)
      this.boneA[i * 3] = m[0]; this.boneA[i * 3 + 1] = m[2]; this.boneA[i * 3 + 2] = m[4]
      this.boneB[i * 3] = m[1]; this.boneB[i * 3 + 1] = m[3]; this.boneB[i * 3 + 2] = m[5]
    }
    gl.uniform3fv(loc.uA, this.boneA)
    gl.uniform3fv(loc.uB, this.boneB)
    gl.uniform4f(loc.uView, 2 / this.width, 2 / this.height, this.originX, this.originY)
    const [w, h] = puppet.rig.size
    const ellipse = (name: string, e: Ellipse) => gl.uniform4f(loc[name], e[0] / w, e[1] / h, w / e[2], h / e[3])
    ellipse('uEyeL', puppet.rig.eyes[0]); ellipse('uEyeR', puppet.rig.eyes[1]); ellipse('uMouth', puppet.rig.mouth)
    gl.uniform1f(loc.uEyes, frame.eyes)
    gl.uniform1f(loc.uMouthClosed, frame.mouth)
    gl.uniform1f(loc.uAlpha, frame.alpha)
    const base = frame.form === 'dog' && puppet.plain ? puppet.plain : puppet.base
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, base); gl.uniform1i(loc.uTex, 0)
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, puppet.closed); gl.uniform1i(loc.uAlt, 1)
    gl.bindVertexArray(puppet.vao)
    gl.drawElements(gl.TRIANGLES, puppet.count, gl.UNSIGNED_SHORT, 0)
    gl.bindVertexArray(null)
  }

  // ------------------------------------------------------------ sprites

  private beginSprites() { this.spriteCount = 0 }

  private flushSprites() {
    if (!this.spriteCount || !this.atlasTexture) return
    const gl = this.gl
    gl.useProgram(this.spriteProgram)
    gl.uniform4f(this.loc.sView, 2 / this.width, 2 / this.height, this.originX, this.originY)
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.atlasTexture); gl.uniform1i(this.loc.sTex, 0)
    gl.bindVertexArray(this.spriteVao)
    gl.bindBuffer(gl.ARRAY_BUFFER, this.spriteBuffer)
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, this.spriteData, 0, this.spriteCount * FLOATS)
    gl.drawArrays(gl.TRIANGLES, 0, this.spriteCount)
    gl.bindVertexArray(null)
  }

  private vertex(x: number, y: number, u: number, v: number, alpha: number) {
    if (this.spriteCount * FLOATS + FLOATS > this.spriteData.length) return
    const o = this.spriteCount * FLOATS
    const d = this.spriteData
    d[o] = x; d[o + 1] = y; d[o + 2] = u; d[o + 3] = v; d[o + 4] = alpha
    this.spriteCount++
  }

  /** A textured quad from four stage corners (top-left, top-right, bottom-right, bottom-left). */
  private quad(corners: [number, number][], slot: Slot, alpha: number, mirror = false) {
    const s = this.atlas?.size ?? 1024
    let u0 = slot.x / s, u1 = (slot.x + slot.w) / s
    if (mirror) [u0, u1] = [u1, u0]
    const v0 = slot.y / s, v1 = (slot.y + slot.h) / s
    const [a, b, c, d] = corners
    this.vertex(a[0], a[1], u0, v0, alpha); this.vertex(b[0], b[1], u1, v0, alpha); this.vertex(c[0], c[1], u1, v1, alpha)
    this.vertex(a[0], a[1], u0, v0, alpha); this.vertex(c[0], c[1], u1, v1, alpha); this.vertex(d[0], d[1], u0, v1, alpha)
  }

  /** Place an atlas item on a bone: sprite-space anchor, rotation, height; anchor fraction inside the item. */
  private attach(matrix: ArrayLike<number>, key: string, at: readonly [number, number], angle: number, height: number, ax: number, ay: number, alpha: number, mirror = false) {
    const slot = this.atlas?.slots[key]
    if (!slot) return
    const width = height * slot.w / slot.h
    const cos = Math.cos(angle), sin = Math.sin(angle)
    const corner = (fx: number, fy: number): [number, number] => {
      const lx = (fx - ax) * width, ly = (fy - ay) * height
      return apply(matrix, at[0] + lx * cos - ly * sin, at[1] + lx * sin + ly * cos)
    }
    this.quad([corner(0, 0), corner(1, 0), corner(1, 1), corner(0, 1)], slot, alpha, mirror)
  }

  private boneOf(bone: number): Float32Array { return this.bones.subarray(bone * 6, bone * 6 + 6) }

  private backLayer(puppet: Puppet, frame: Frame) {
    const rig = puppet.rig
    const k = figureHeight(rig) / 470
    const root = rootMatrix(frame.pose)
    if (frame.cushion) this.attach(root, slotKey('cushion', rig.id), [rig.centerX, rig.footY + 10 * k], 0, 104 * k, 0.5, 0.78, frame.alpha)
    if (frame.tail) this.tailStrip(rig, frame)
    const head = this.boneOf(BONE.head)
    if (frame.form === 'cat' && !rig.ownEars) {
      const [l, r] = rig.ears
      this.attach(head, slotKey('catEar', rig.id), l.at, l.angle + frame.earAngles[0], l.size * 0.92, 0.5, 0.9, frame.alpha)
      this.attach(head, slotKey('catEar', rig.id), r.at, r.angle + frame.earAngles[1], r.size * 0.92, 0.5, 0.9, frame.alpha, true)
    }
  }

  private frontLayer(puppet: Puppet, frame: Frame) {
    const rig = puppet.rig
    const k = figureHeight(rig) / 470
    const head = this.boneOf(BONE.head)
    const root = rootMatrix(frame.pose)
    if (frame.form === 'dog') {
      const [l, r] = rig.ears
      // Floppy ears hang from the upper sides of the head and bounce with the body.
      const bounce = 0.1 * Math.sin(frame.pose.bodyY * 0.5)
      this.attach(head, slotKey('dogEar', rig.id), [l.at[0] + 16 * k, l.at[1] + 66 * k], 0.14 - frame.earAngles[0] * 0.6 + bounce, l.size * 1.55, 0.5, 0.06, frame.alpha)
      this.attach(head, slotKey('dogEar', rig.id), [r.at[0] - 16 * k, r.at[1] + 66 * k], -0.14 - frame.earAngles[1] * 0.6 - bounce, r.size * 1.55, 0.5, 0.06, frame.alpha, true)
    }
    if (frame.blush > 0.01) for (const cheek of rig.cheeks) this.attach(head, 'blush', cheek, 0, 26 * k, 0.5, 0.5, frame.blush * frame.alpha)
    if (frame.glasses && rig.glasses) {
      const g = rig.glasses
      this.attach(head, 'glasses', g.at, g.angle, g.width * 92 / 260, 0.5, 0.5, frame.alpha)
    }
    if (frame.desk) {
      const deskTop = rig.footY - 92 * k
      this.attach(root, 'desk', [rig.centerX, rig.footY + 8 * k], 0, 112 * k, 0.5, 1, frame.alpha)
      if (frame.prop === 'laptop') {
        const tap = Math.sin(frame.propPhase * 21) * 0.6
        this.attach(root, 'laptop', [rig.centerX + tap * 0.2, deskTop + 8 * k], 0, 112 * k, 0.5, 1, frame.alpha)
      } else if (frame.prop === 'notebook') {
        this.attach(root, 'notebook', [rig.centerX - 6 * k, deskTop + 10 * k], 0, 62 * k, 0.5, 1, frame.alpha)
        const hand = rig.hands[1]
        this.attach(this.boneOf(BONE.armR), 'pencil', [hand[0], hand[1] - 4 * k], -1.05 + 0.18 * Math.sin(frame.propPhase * 9), 13 * k, 0.88, 0.5, frame.alpha)
      }
    }
    if (frame.prop === 'book') {
      const [hl, hr] = rig.hands
      const flip = Math.max(0, Math.sin(frame.propPhase * 0.6) - 0.96) * 18
      this.attach(this.boneOf(BONE.torso), 'book', [(hl[0] + hr[0]) / 2, Math.min(hl[1], hr[1]) - 6 * k], 0.04 * Math.sin(flip), 92 * k, 0.5, 0.62, frame.alpha)
    }
  }

  private tailStrip(rig: Rig, frame: Frame) {
    const points = frame.tail
    const slot = this.atlas?.slots[slotKey(frame.form === 'dog' ? 'dogTail' : 'catTail', rig.id)]
    if (!points || points.length < 2 || !slot) return
    const hips = this.boneOf(BONE.hips)
    const k = figureHeight(rig) / 470
    const s = this.atlas?.size ?? 1024
    const lengths = [0]
    for (let i = 1; i < points.length; i++) lengths.push(lengths[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]))
    const total = lengths[lengths.length - 1] || 1
    const half = (frame.form === 'dog' ? 22 : 15) * k
    const edge = (i: number): [[number, number], [number, number], number] => {
      const a = points[Math.max(0, i - 1)], b = points[Math.min(points.length - 1, i + 1)]
      const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1
      const nx = -dy / len * half, ny = dx / len * half
      const p = points[i]
      return [apply(hips, p[0] + nx, p[1] + ny), apply(hips, p[0] - nx, p[1] - ny), slot.x / s + lengths[i] / total * slot.w / s]
    }
    const v0 = slot.y / s, v1 = (slot.y + slot.h) / s
    let prev = edge(0)
    for (let i = 1; i < points.length; i++) {
      const next = edge(i)
      const [a, b, ua] = prev, [c, d, uc] = next
      this.vertex(a[0], a[1], ua, v0, frame.alpha); this.vertex(c[0], c[1], uc, v0, frame.alpha); this.vertex(d[0], d[1], uc, v1, frame.alpha)
      this.vertex(a[0], a[1], ua, v0, frame.alpha); this.vertex(d[0], d[1], uc, v1, frame.alpha); this.vertex(b[0], b[1], ua, v1, frame.alpha)
      prev = next
    }
  }

  // ------------------------------------------------------------ particles

  emit(particle: Omit<Particle, 'age'>) {
    if (this.particles.length < 80) this.particles.push({...particle, age: 0})
  }

  private stepParticles(dt: number) {
    const keep: Particle[] = []
    for (const p of this.particles) {
      p.age += dt
      if (p.age >= p.life) continue
      keep.push(p)
      const t = p.age / p.life
      let scale = 1, alpha = 1, angle = 0
      if (p.kind === 'float') { p.x += p.vx * dt + Math.sin(p.age * 5 + p.spin) * 8 * dt; p.y += p.vy * dt; scale = Math.min(1, t * 6) * (1 - t * 0.2); alpha = 1 - Math.max(0, t - 0.6) / 0.4 }
      else if (p.kind === 'drift') { p.x += p.vx * dt; p.y += p.vy * dt; scale = 0.6 + t * 0.7; alpha = Math.min(1, t * 5) * (1 - Math.max(0, t - 0.6) / 0.4); angle = -0.2 }
      else if (p.kind === 'pop') { scale = t < 0.18 ? t / 0.18 * 1.25 : t < 0.3 ? 1.25 - (t - 0.18) / 0.12 * 0.25 : 1; alpha = 1 - Math.max(0, t - 0.75) / 0.25; p.y += p.vy * dt }
      else if (p.kind === 'fall') { p.vy += 260 * dt; p.x += p.vx * dt; p.y += p.vy * dt; alpha = 1 - Math.max(0, t - 0.5) / 0.5; scale = Math.min(1, t * 8) }
      else { p.x += p.vx * dt; p.y += p.vy * dt; p.vx *= Math.pow(0.05, dt); p.vy *= Math.pow(0.05, dt); scale = (t < 0.2 ? t / 0.2 : 1) * (1 - t * 0.5); alpha = 1 - t; angle = p.spin * p.age }
      const slot = this.atlas?.slots[p.item]
      if (!slot) continue
      const h = p.size * scale, w = h * slot.w / slot.h
      const cos = Math.cos(angle), sin = Math.sin(angle)
      const corner = (fx: number, fy: number): [number, number] => {
        const lx = (fx - 0.5) * w, ly = (fy - 0.5) * h
        return [p.x + lx * cos - ly * sin, p.y + lx * sin + ly * cos]
      }
      this.quad([corner(0, 0), corner(1, 0), corner(1, 1), corner(0, 1)], slot, Math.max(0, alpha))
    }
    this.particles = keep
  }

  dispose() {
    const gl = this.gl
    for (const p of this.puppets.values()) {
      gl.deleteVertexArray(p.vao)
      for (const t of [p.base, p.closed, p.plain]) if (t) gl.deleteTexture(t)
    }
    if (this.atlasTexture) gl.deleteTexture(this.atlasTexture)
    gl.deleteBuffer(this.spriteBuffer)
    for (const b of this.buffers) gl.deleteBuffer(b)
    gl.deleteVertexArray(this.spriteVao)
    gl.deleteProgram(this.puppetProgram)
    gl.deleteProgram(this.spriteProgram)
    this.puppets.clear()
  }
}
