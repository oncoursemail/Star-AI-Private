/* Home hero: the launcher's Revival wall (wall/logos.js, copied from launcher/web/wallpaper): the logo of every revival
   floating at different depths, the most online ones largest and up front. WebGL2 only; without it the hero's
   dark gradient stays. Reduced motion: one still frame. Nothing is drawn while the hero is off screen or the tab is hidden. */
"use strict";
(() => {
  const box = document.querySelector(".hero-bg");
  if (!box) return;
  const cv = document.createElement("canvas");
  const gl = cv.getContext("webgl2", { alpha: true, premultipliedAlpha: true, antialias: false });
  if (!gl) return;
  const v = (document.currentScript && new URL(document.currentScript.src).search) || "";
  // the launcher's scene (scenes/revivals/scene.json "logos"), stepping back a little more behind the headline
  const CFG = {
    seed: 11, dir: [-0.94, 0.34], domain: [5, 2.2],
    groups: [
      { count: 150, z: [0, 0.34], size: [0.04, 0.075] },
      { count: 70, z: [0.42, 0.74], size: [0.085, 0.14] },
      { count: 22, z: [0.86, 1], size: [0.18, 0.28], hero: true },
    ],
    speed: [0.003, 0.024], blur: [24, 0], bright: [0.46, 0.95], fog: [0.55, 0], parallax: [0.004, 0.05], glow: [0.85, 0.9],
    float: 0.012, rotate: 4, radius: 0.46, fogColor: [0.075, 0.065, 0.13], rim: [0.75, 0.66, 1.0],
    calm: 0.85, column: [600, 1200], sheen: 0.1, grain: 0.03, vignette: 0.42,
  };
  import("/assets/wall/logos.js" + v).then(({ LogoWall }) => {
    let dirty = true, W = 0, H = 0, seen = true;
    const wall = new LogoWall(gl, { redraw: () => { dirty = true; } });
    wall.configure(CFG);
    const list = (rs) => wall.setList(rs.map((r) => ({ id: r.id, name: r.name, icon: r.discord && r.discord.icon })));
    if (window.Metallic.revivals) list(window.Metallic.revivals);
    addEventListener("metallic:revivals", (e) => list(e.detail));
    box.prepend(cv);
    const size = () => {
      const r = box.getBoundingClientRect(), d = Math.min(devicePixelRatio || 1, 2);
      W = cv.width = Math.max(1, Math.round(r.width * d));
      H = cv.height = Math.max(1, Math.round(r.height * d));
      dirty = true;
    };
    new ResizeObserver(size).observe(box);
    new IntersectionObserver(([e]) => { seen = e.isIntersecting; }).observe(box);
    // pointer parallax, eased; the wall shifts each logo by its depth
    let tx = 0, ty = 0, cx = 0, cy = 0;
    addEventListener("pointermove", (e) => { tx = (e.clientX / innerWidth) * 2 - 1; ty = (e.clientY / innerHeight) * 2 - 1; }, { passive: true });
    const still = matchMedia("(prefers-reduced-motion: reduce)");
    const t0 = performance.now();
    const frame = (now) => {
      requestAnimationFrame(frame);
      if (!seen || document.hidden || (still.matches && !dirty)) return;
      dirty = false;
      cx += (tx - cx) * 0.04; cy += (ty - cy) * 0.04;
      gl.viewport(0, 0, W, H);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      wall.draw({ t: still.matches ? 0 : (now - t0) / 1000, W, H, cam: still.matches ? [0, 0] : [cx, cy], fade: 1, tint: [1, 1, 1, 0], still: still.matches });
      if (wall.active) box.classList.add("wall");
    };
    requestAnimationFrame(frame);
  }).catch((e) => console.warn("revival wall off: " + (e && e.message)));
})();
