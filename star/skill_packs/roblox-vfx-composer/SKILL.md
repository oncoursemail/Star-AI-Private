---
name: roblox-vfx-composer
description: Style-agnostic Roblox ability VFX - style profiles (anime energy, soft cartoon, realistic fire, sci-fi neon, pixel retro), a timeline composer (charge, impact, shockwave, linger, dissipate), effect primitives, budgets and a validated RemoteEvent path, with typed Luau modules in luau/.
---
# Ability VFX composer (any art style)

Separate the LOOK from the CONTENT. A style profile is the art direction: palette (core, glow, dark, accent, flash), shape language (jagged, round, wispy, crisp, blocky), texture set, timing per stage and easing, intensity, and how much screen effect it may use. An ability is a list of cues `{stage, at (0..1 of that stage), fx, params}` and names no colours. The same ability under another profile is a different effect. Ready modules: luau/VfxStyles, VfxPrimitives, VfxComposer, VfxClient (ReplicatedStorage) and VfxService (ServerScriptService).

## Timeline (stage lengths come from the style)
1. Charge (anticipation): aura Highlight on the caster, inward motes (Sphere shape, ShapeInOut Inward), a small ground ring, a light rumble. Keep it quieter than the hit.
2. Impact (0.1-0.25 s): flash, one inverted frame only for styles that allow it (ColorCorrection Saturation -1, Contrast -2), PointLight kick, ground crack + debris, sparks, slashes, a shell, the strongest shake and FOV punch. Reserve the most contrast for this frame.
3. Shockwave: flat ring particle (Orientation VelocityPerpendicular, Size grows over life), a ring of segments flying out, dust.
4. Linger: vortex shell with spinning trail arms, a pillar of two scrolling beams plus a solid core.
5. Dissipate: embers rise, smoke drifts, every layer fades; nothing may pop off. Restore tint, bloom and FOV.

## Shape language decides the primitive's form
- jagged: stretched streak sparks (VelocityParallel + Squash), tilted shard rings, rock spikes, inverted frame, hard shake.
- round: circle puffs, Back easing, ball debris in palette colours, no spikes, soft splat instead of a dark crack.
- wispy: lit smoke (LightInfluence 1), long dissipate, little screen effect.
- crisp: thin geometry, ForceField shells, two-tone palette, linear snappy timing.
- blocky: square particles, no rotation, cube debris, stepped motion (tweens split into hard steps), no bloom.

## Techniques
- Bursts: Rate 0 and Emit(n). Continuous only while charging (Enabled on, then off).
- Flipbooks: FlipbookLayout Grid4x4 with FlipbookMode OneShot plays 16 frames once per particle life.
- Flat decals on the ground: one particle with VelocityPerpendicular and a tiny upward Speed.
- Shells: Ball part, ForceField material reads as an energy rim; an opaque Neon ball hides every other layer.
- Beams: Attachment0/1, FaceCamera, TextureMode Wrap and TextureSpeed for scrolling energy; tween Width0/Width1.
- Trails need moving attachments: spin an anchored part each Heartbeat.
- Debris: raycast the floor to copy its colour and material, move chunks yourself (ballistic step, short raycasts for bounces, BulkMoveTo); no physics ownership and no pushing players.
- Camera shake: BindToRenderStep at Camera + 2, decaying math.noise offsets, unbind at the end. A Scriptable camera must be re-set every frame by its owner or offsets accumulate. FOV punch from a remembered resting FOV.
- Screen: ColorCorrection works only under Lighting or the current camera; it is client-local when a LocalScript makes it.
- Slow motion for review: one speed value scales every wait and tween and sets ParticleEmitter.TimeScale.
- Cleanup: Debris:AddItem on every piece plus one Folder per effect destroyed at the end; disconnect Heartbeat connections and unbind render steps.

## Budgets
At most 4 effects per client, a particle budget per effect (700 at quality 1) scaled by device quality (touch-only devices 0.5, low graphics level lower), fewer segments and chunks on low quality, cull beyond 350 studs, screen effects only within 120 studs. Overdraw of big transparent particles costs more than part count.

## Security (server authoritative)
The client sends only an ability name and a style name (strings, length-checked, allow lists). The server takes the origin from the caster's own character (a target point is clamped to range), applies a per-ability cooldown and a token bucket, refuses dead characters, and tells only nearby players. Clients check every received value before rendering. Damage never depends on VFX.

## Reviewing an effect
Capture frames across the whole timeline in slow motion from a fixed camera; check impact readability (the hit changes the picture far more than the charge), layering (several layers visible at once, not one blob), timing (anticipation, a short hit, a longer tail), palette, flash and shake strength, and that the scene returns to normal at the end.

## 2026 creator-reference compositions (original assets)
STAR VFX Studio now includes two **original** authored cue lists inspired by externally supplied footage (no borrowed textures or source code):
- `frost_cyclone`: an inward anticipation, cool-coloured crystal spikes at hit, ring segments, restrained flash, multi-arm vortex and slow falling/smoke dissipation. Prompt: "blue ice vortex crystal storm".
- `cinematic_sword_arc`: brief anticipation, fast narrow slash strokes, localized orange-gold impact, sparks, modest shake, short ring segments, and a lingering motion trail. Prompt: "anime sword slash orange". For real combat, anchor hits to animation markers and validate server-owned damage separately.
Evaluate the effect from **multiple camera angles**, not a hero still. Use slow-motion capture to inspect silhouette and timing; compare p50/p95 frame time and cleanup on mobile and desktop. Visual effects may never grant gameplay authority. The short-video claim that a professional effect took "five minutes" is unverified. A plugin license does not grant rights to copy its source or textures; favor native editable Studio assets.
