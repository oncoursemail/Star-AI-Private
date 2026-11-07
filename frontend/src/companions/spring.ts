/** A damped spring (semi-implicit Euler, fixed substeps so it is stable at any frame rate). */
export class Spring {
  value: number
  velocity = 0
  constructor(value = 0, public stiffness = 120, public damping = 14) { this.value = value }
  step(target: number, dt: number): number {
    let left = Math.min(dt, 0.1)
    while (left > 1e-6) {
      const h = Math.min(left, 1 / 120)
      this.velocity += (this.stiffness * (target - this.value) - this.damping * this.velocity) * h
      this.value += this.velocity * h
      left -= h
    }
    return this.value
  }
  kick(velocity: number) { this.velocity += velocity }
  set(value: number) { this.value = value; this.velocity = 0 }
}
