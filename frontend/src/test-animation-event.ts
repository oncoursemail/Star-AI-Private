// jsdom 30 has the WebkitAnimation style but no AnimationEvent, so React DOM listens for the prefixed
// webkitAnimationEnd while testing-library fires animationend. Browsers have AnimationEvent (unprefixed
// names); give jsdom the same before react-dom loads.
if (typeof window !== 'undefined' && !('AnimationEvent' in window)) {
  class AnimationEvent extends Event {
    readonly animationName: string
    readonly elapsedTime: number
    readonly pseudoElement: string
    constructor(type: string, init: AnimationEventInit = {}) {
      super(type, init)
      this.animationName = init.animationName ?? ''
      this.elapsedTime = init.elapsedTime ?? 0
      this.pseudoElement = init.pseudoElement ?? ''
    }
  }
  Object.defineProperty(window, 'AnimationEvent', {value: AnimationEvent, configurable: true, writable: true})
}
