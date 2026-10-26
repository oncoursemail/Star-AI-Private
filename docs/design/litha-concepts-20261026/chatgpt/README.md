# Litha concepts

Created with the built-in ChatGPT image-generation tool for [Claude's issue #682 brief](https://github.com/oncoursemail/Star-AI-Private/issues/682). These are review concepts, not an approved character, a layered drawing or a rigged model. STAR's installed avatar is unchanged.

| Direction | File | Design distinction |
| --- | --- | --- |
| A: Sun Engineer | [Character sheet](litha-a-sun-engineer-sheet.png) | Braid, brass goggles, practical work jacket, toolbelt and holographic wrench |
| B: Solstice Architect | [Character sheet](litha-b-solstice-architect-sheet.png) | Long emerald hair, round glasses and long cream coat |
| C: Light Weaver | [Character sheet](litha-c-light-weaver-sheet.png) | Light mint bob, sun clip and cream/green hoodie |
| D: Chibi Sun Engineer | [Wave pose](../../metallic-art-20261026/litha/litha-wave.png) | The engineer's identifiers reduced into a large-head mascot |

Each sheet is 1536×1024 RGB on a plain ivory background, with front, side and back body views plus focused, smiling, surprised and proud expressions. The maker clothing, sun clip and game-level blueprint carry the identity; decoration is limited to those readable objects. A is the working reference for the pose set, not an owner-approved winner.

The [launcher pose set](../../metallic-art-20261026/litha/README.md) contains six transparent chibis and a full-body illustration. The [manifest](ASSET-MANIFEST.json) records actual dimensions, alpha ranges and SHA-256 checksums for all ten files. Files were copied from the tool's original outputs without raster post-processing.

## Review

Root and an independent agent inspected all ten outputs for the requested identity, modest presentation, view/pose differences, obvious anatomy problems and hard clipping. The Light Weaver's first output had overly dark hair; a targeted edit made the bob visibly mint across all seven views/portraits. That earlier candidate is not in this set.

The six chibi masters are **1254×1254**, despite the requested 1024px canvas in the generation prompts. Exact 1024px exports remain outstanding. Fine coloured edge fringes and faint alpha noise are visible around some hair and glow contours; check them on both light and dark launcher backgrounds before production use. No animation, app integration, PSD layers or rigging was produced. The separate crow, wallpaper-layer and game-tile requests in #682 remain open.

## Prompt set

All requests used the built-in tool in `stylized-concept` mode. Transparent output was requested for the pose set and full-body illustration; the sheets requested a plain background. Reference images were explicitly supplied to preserve Litha's identity between requests.

**A, initial sheet:** Original, clearly adult, all-ages anime game-development maker mascot; spring-green/emerald hair with restrained sunlit gold highlights in a side braid; teal-green eyes; gold sun clip and brass goggles; green/cream practical jacket over opaque cream shirt, dark-green trousers, toolbelt and sturdy boots. Include a glowing wrench and small cyan holographic game-level blueprint. Landscape ivory sheet: complete front/true-side/back views above four focused/smiling/surprised/proud head portraits. Crisp line art, soft cel shading, coherent seams, clear silhouette, no text/logos, no stars, no fantasy armour or sexualized outfit.

**B, reference A:** Preserve the recognizable face, eyes, palette and style. Replace hair/outfit with long emerald hair, round fine gold glasses, cream high-neck shirt, dark-green trousers, practical boots and a long white architect coat with restrained green/gold geometric trim. Keep the same sheet layout and floating game-level blueprint. No goggles, braid, fantasy clutter or text.

**C, reference A:** Preserve face, eyes, palette and style. Replace hair/outfit with a mint-green chin-length bob, gold sun-ray clip, cream/green hoodie with restrained circuit/sun seams, forest-green trousers and sturdy light boots. Include a floating light keyboard and game-level blueprint. Keep the same sheet layout. Targeted final edit, reference C: change only all hair regions to distinctly light mint with cool emerald shadows and small gold highlights; preserve the existing composition and identity.

**D / wave, reference A:** One isolated full-body chibi on a transparent square 1024px canvas; large head/small body; keep engineer braid, goggles, sun clip, teal eyes, jacket, trousers, toolbelt and boots. Wave hello with a correctly drawn open hand and inviting smile; hold a tiny blueprint in the other hand. Crisp cel shading, clear silhouette and generous transparent margin. No text, logos, background, duplicate character or ground panel.

**Five further poses, reference D:** Preserve exact chibi identity, proportions, outfit, palette and line weight. Request one isolated full-body character per transparent 1024px square, with hair, hands and boots fully inside the canvas. Replace the waving pose with:

- Thinking: open eyes looking upward, fingertip at chin, other arm folded beneath that elbow; small floating blueprint.
- Typing: focused pleased expression, both hands typing on a floating cyan keyboard at waist height; unobscured hands.
- Cheering: closed happy eye arcs, broad smile, both fists raised and one boot lifting in a little hop; separate tiny blueprint.
- Sleepy: half-closed eyes, yawn with one hand covering the mouth, other hand loosely holding a rolled blueprint; both boots visible, no letters or sleep symbols.
- Surprised: wide teal eyes, O-shaped mouth and both open hands near the shoulders; friendly surprise and separate tiny blueprint.

**Full-body, reference A:** One adult-proportioned cute illustration of the same Sun Engineer, standing in a welcoming three-quarter pose with a warm confident smile, holding a cyan game-level blueprint in one hand and gesturing toward it with the other. Preserve the exact engineer identity and modest outfit; full boots, hands and hair visible. Transparent background, crisp line art, soft cel shading, no scenery, text, logo, extra character or fantasy jewellery.
