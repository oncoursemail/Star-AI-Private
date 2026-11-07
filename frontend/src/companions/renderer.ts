/**
 * WebGL2 renderer for the skeletal companions: CPU-skinned weighted meshes (a few hundred vertices per
 * character) streamed into one buffer and drawn in slot order, one draw per atlas page change, then the
 * particles. Premultiplied alpha throughout so soft edges and mipmaps stay clean.
 */
import type {Skeleton} from './skeleton'
import type {Character} from './armature'
import {fxSheet, paintSheet} from './armature'
import type {FxName} from './art'
import type {Rect} from './armature'

export type Particle = {
  item: FxName; x: number; y: number; vx: number; vy: number; age: number; life: number; size: number; spin: number
  kind: 'float' | 'pop' | 'fall' | 'burst' | 'drift' | 'puff'
  rot?: number
}
export type DrawItem = { sk: Skeleton; alpha: number; z: number }

const VS = `#version 300 es
layout(location=0) in vec2 a_pos;
layout(location=1) in vec2 a_uv;
layout(location=2) in vec4 a_color;
uniform vec2 u_view;
uniform vec2 u_offset;
out vec2 v_uv;
out vec4 v_color;
void main() {
  vec2 p = (a_pos - u_offset) / u_view * 2.0 - 1.0;
  gl_Position = vec4(p.x, -p.y, 0.0, 1.0);
  v_uv = a_uv;
  v_color = a_color;
}`
const FS = `#version 300 es
precision mediump float;
in vec2 v_uv;
in vec4 v_color;
uniform sampler2D u_tex;
out vec4 outColor;
void main() { outColor = texture(u_tex, v_uv) * v_color; }`

const FLOATS = 8
const MAX_VERTS = 24000

export class CompanionRenderer {
  particles: Particle[] = []
  private textures: WebGLTexture[] = []
  private fxCells: Record<FxName, Rect> | null = null
  private fxSize = {w: 1, h: 1}
  private data = new Float32Array(MAX_VERTS * FLOATS)
  private index = new Uint16Array(MAX_VERTS * 3)
  private skinned = new Float32Array(4096)
  private width = 1
  private height = 1
  private ox = 0
  private oy = 0
  private program: WebGLProgram
  private vao: WebGLVertexArrayObject
  private vbo: WebGLBuffer
  private ibo: WebGLBuffer
  private uView: WebGLUniformLocation | null
  private uOffset: WebGLUniformLocation | null

  static create(canvas: HTMLCanvasElement): CompanionRenderer | null {
    const gl = canvas.getContext('webgl2', {alpha: true, premultipliedAlpha: true, antialias: true})
    if (!gl) return null
    try { return new CompanionRenderer(gl) } catch { return null }
  }

  private constructor(private gl: WebGL2RenderingContext) {
    const compile = (type: number, src: string) => {
      const s = gl.createShader(type) as WebGLShader
      gl.shaderSource(s, src); gl.compileShader(s)
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || 'shader')
      return s
    }
    const p = gl.createProgram() as WebGLProgram
    gl.attachShader(p, compile(gl.VERTEX_SHADER, VS)); gl.attachShader(p, compile(gl.FRAGMENT_SHADER, FS))
    gl.linkProgram(p)
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error('link')
    this.program = p
    this.uView = gl.getUniformLocation(p, 'u_view')
    this.uOffset = gl.getUniformLocation(p, 'u_offset')
    this.vao = gl.createVertexArray() as WebGLVertexArrayObject
    gl.bindVertexArray(this.vao)
    this.vbo = gl.createBuffer() as WebGLBuffer
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo)
    gl.bufferData(gl.ARRAY_BUFFER, this.data.byteLength, gl.DYNAMIC_DRAW)
    const stride = FLOATS * 4
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, stride, 0)
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 2, gl.FLOAT, false, stride, 8)
    gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 4, gl.FLOAT, false, stride, 16)
    this.ibo = gl.createBuffer() as WebGLBuffer
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.ibo)
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, this.index.byteLength, gl.DYNAMIC_DRAW)
    gl.bindVertexArray(null)
  }

  /** Paints and uploads one atlas page per character (page = position in the list) plus the particles. */
  async load(characters: readonly Character[]) {
    const gl = this.gl
    const upload = (canvas: HTMLCanvasElement) => {
      const tex = gl.createTexture() as WebGLTexture
      gl.bindTexture(gl.TEXTURE_2D, tex)
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true)
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas)
      gl.generateMipmap(gl.TEXTURE_2D)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
      return tex
    }
    for (const c of characters) {
      this.textures.push(upload(paintSheet(c.sheet)))
      // Let the page breathe between the big uploads.
      await new Promise(r => setTimeout(r, 0))
    }
    const fx = fxSheet()
    this.fxCells = fx.cells
    this.fxSize = {w: fx.canvas.width, h: fx.canvas.height}
    this.textures.push(upload(fx.canvas))
  }

  resize(width: number, height: number, dpr: number, ox: number, oy: number) {
    const canvas = this.gl.canvas as HTMLCanvasElement
    const w = Math.max(1, Math.round(width * dpr)), h = Math.max(1, Math.round(height * dpr))
    if (canvas.width !== w) canvas.width = w
    if (canvas.height !== h) canvas.height = h
    this.width = width; this.height = height; this.ox = ox; this.oy = oy
  }

  emit(p: Omit<Particle, 'age'>) { if (this.particles.length < 120) this.particles.push({...p, age: 0, rot: p.spin * 0.2}) }

  render(items: readonly DrawItem[], dt: number) {
    const gl = this.gl
    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)
    if (!this.textures.length) return
    gl.useProgram(this.program)
    gl.uniform2f(this.uView, this.width, this.height)
    gl.uniform2f(this.uOffset, this.ox, this.oy)
    gl.enable(gl.BLEND)
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA)
    gl.bindVertexArray(this.vao)
    let verts = 0, tris = 0, page = -1
    const flush = () => {
      if (!tris) return
      gl.bindTexture(gl.TEXTURE_2D, this.textures[page])
      gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo)
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, this.data, 0, verts * FLOATS)
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.ibo)
      gl.bufferSubData(gl.ELEMENT_ARRAY_BUFFER, 0, this.index, 0, tris)
      gl.drawElements(gl.TRIANGLES, tris, gl.UNSIGNED_SHORT, 0)
      verts = 0; tris = 0
    }
    for (const item of [...items].sort((a, b) => a.z - b.z)) {
      if (item.alpha <= 0.01) continue
      const sk = item.sk, slots = sk.data.slots
      for (let s = 0; s < slots.length; s++) {
        const slot = slots[s]
        const name = sk.attachment[s]
        if (!name) continue
        const mesh = sk.data.attachments[slot.name]?.[name]
        if (!mesh) continue
        const a = sk.alpha[s] * item.alpha
        if (a <= 0.01) continue
        const n = mesh.influences.length
        if (verts + n > MAX_VERTS || tris + mesh.triangles.length > this.index.length) flush()
        if (mesh.page !== page) { flush(); page = mesh.page }
        if (this.skinned.length < n * 2) this.skinned = new Float32Array(n * 2)
        sk.skin(mesh, this.skinned)
        const c = slot.shade * a
        for (let v = 0; v < n; v++) {
          const o = (verts + v) * FLOATS
          this.data[o] = this.skinned[v * 2]; this.data[o + 1] = this.skinned[v * 2 + 1]
          this.data[o + 2] = mesh.uvs[v * 2]; this.data[o + 3] = mesh.uvs[v * 2 + 1]
          this.data[o + 4] = c; this.data[o + 5] = c; this.data[o + 6] = c; this.data[o + 7] = a
        }
        for (let i = 0; i < mesh.triangles.length; i++) this.index[tris + i] = mesh.triangles[i] + verts
        verts += n; tris += mesh.triangles.length
      }
    }
    flush()
    this.drawParticles(dt, flush, (p: number) => { if (p !== page) { flush(); page = p } }, () => ({verts, tris}), (v, t) => { verts = v; tris = t })
    flush()
    gl.bindVertexArray(null)
  }

  private drawParticles(dt: number, flush: () => void, use: (page: number) => void, counts: () => {verts: number; tris: number}, set: (v: number, t: number) => void) {
    if (!this.fxCells || !this.particles.length) return
    use(this.textures.length - 1)
    const keep: Particle[] = []
    for (const p of this.particles) {
      p.age += dt
      if (p.age >= p.life) continue
      keep.push(p)
      const u = p.age / p.life
      let scale = 1, alpha = 1
      switch (p.kind) {
        case 'float': p.x += (p.vx + Math.sin(p.age * 5 + p.spin) * 8) * dt; p.y += p.vy * dt; alpha = u > 0.65 ? (1 - u) / 0.35 : 1; scale = Math.min(1, p.age * 8); break
        case 'pop': scale = u < 0.15 ? 1.35 * u / 0.15 : u < 0.3 ? 1.35 - (u - 0.15) / 0.15 * 0.35 : 1; alpha = u > 0.75 ? (1 - u) / 0.25 : 1; p.y += p.vy * dt; break
        case 'fall': p.vy += 220 * dt; p.x += p.vx * dt; p.y += p.vy * dt; alpha = 1 - u * u; break
        case 'burst': p.vx *= Math.pow(0.05, dt); p.vy *= Math.pow(0.05, dt); p.x += p.vx * dt; p.y += p.vy * dt; scale = 1 - u * 0.5; alpha = 1 - u; break
        case 'drift': p.x += (p.vx + Math.sin(p.age * 2.4) * 6) * dt; p.y += p.vy * dt; scale = 0.6 + u * 0.7; alpha = u > 0.6 ? (1 - u) / 0.4 : Math.min(1, u * 6); break
        case 'puff': p.vx *= Math.pow(0.02, dt); p.vy *= Math.pow(0.02, dt); p.x += p.vx * dt; p.y += p.vy * dt; scale = 0.45 + 0.9 * Math.sqrt(u); alpha = u > 0.45 ? (1 - u) / 0.55 : 1; break
      }
      p.rot = (p.rot ?? 0) + p.spin * dt
      const cell = this.fxCells[p.item]
      if (!cell) continue
      let {verts, tris} = counts()
      if (verts + 4 > MAX_VERTS) { flush(); ({verts, tris} = counts()) }
      const half = p.size * scale / 2, cos = Math.cos(p.rot) * half, sin = Math.sin(p.rot) * half
      const u0 = cell.x / this.fxSize.w, v0 = cell.y / this.fxSize.h, u1 = (cell.x + cell.w) / this.fxSize.w, v1 = (cell.y + cell.h) / this.fxSize.h
      const corners = [[-1, -1, u0, v0], [1, -1, u1, v0], [1, 1, u1, v1], [-1, 1, u0, v1]]
      corners.forEach(([cx, cy, uu, vv], k) => {
        const o = (verts + k) * FLOATS
        this.data[o] = p.x + cx * cos - cy * sin; this.data[o + 1] = p.y + cx * sin + cy * cos
        this.data[o + 2] = uu; this.data[o + 3] = vv
        this.data[o + 4] = alpha; this.data[o + 5] = alpha; this.data[o + 6] = alpha; this.data[o + 7] = alpha
      })
      this.index.set([verts, verts + 1, verts + 2, verts, verts + 2, verts + 3], tris)
      set(verts + 4, tris + 6)
    }
    this.particles = keep
  }

  dispose() {
    const gl = this.gl
    for (const t of this.textures) gl.deleteTexture(t)
    gl.deleteBuffer(this.vbo); gl.deleteBuffer(this.ibo); gl.deleteVertexArray(this.vao); gl.deleteProgram(this.program)
    this.textures = []
  }
}
