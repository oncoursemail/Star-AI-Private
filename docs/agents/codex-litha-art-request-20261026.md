# Litha art request, 2026-10-26

Read-only review at 23:25 UTC. The canonical GitHub request is
[issue #682: Art for ChatGPT: Litha (green, cute) + Metallic launcher logo, wallpapers, tiles](https://github.com/oncoursemail/Star-AI-Private/issues/682),
opened by `oncoursemail` at **2026-10-26 23:18:13 UTC**. Its body identifies the request as Claude's and mirrors local collaboration messages **#497** (23:10:31 UTC) and **#498** (23:17:30 UTC). The earlier local Litha brief remains consistent; the newer message adds a distinct Metallic launcher art request.

## Litha deliverables

The requested original destination is `docs/design/litha-concepts-20261026/chatgpt/`. Deliver PNGs with a transparent or plain background. Work for this checkout belongs at that relative path here; this review did not write into the separate collaboration workspace.

Litha is the green, midsummer-themed mascot of a game-development tool for Roblox/Unity, distinct from STAR's Star, Ember, Astra and Gemini characters. The brief calls for an original anime design, an all-ages modest outfit and no suggestive presentation or existing franchise identity.

- Spring-green to emerald flowing hair with a few sunlit golden highlights; bright teal-green eyes; a warm, confident smile.
- Practical maker outfit: soft green jacket with cream/gold trim, fitted dark-green pants, sturdy boots, tool belt with small holographic tools, and a small golden sun hair clip.
- A glowing holographic blueprint of a game level. Personality direction: calm, precise, encouraging, slightly perfectionist and warm.
- Polished anime illustration, soft cel shading, crisp line art and a midsummer/green-fields/bright-sunlight theme.
- Main character sheet: full-body front, side and back views, plus head close-ups showing **focused, smiling, surprised and proud** expressions. Plain light background; **no text or logos**.

The requested variants retain a consistent character identity:

| Variant | Required details |
| --- | --- |
| A, sun engineer | Green braid, small brass goggles on her head, green-and-cream work jacket, tool belt, glowing holographic wrench. |
| B, solstice architect | Long emerald hair, round gold glasses, long white coat with green/gold geometric trim, floating blueprint panels. |
| C, light weaver | Short mint-green bob, sun-ray hair clip, white-and-green hoodie with subtle gold circuit/sun patterns, floating light keyboard. |
| D, chibi | The best selected variant with a big head, small body, cheerful pose and tiny glowing blueprint; app-icon style. |

Issue #682 also requests a cute Litha set under the separate Metallic art destination: **six transparent 1024px PNGs**, showing **wave hello, thinking, typing, cheering, sleepy and surprised**, in the same style, plus **one full-body cute illustration**. The specified identifiers are green hair, teal eyes, green jacket and gold sun clip. These are Litha deliverables within the broader launcher brief; they should be indexed separately from the main character concepts if created in this checkout's Litha directory.

Claude says a separate GPU-generated comparison set will be saved beside the `chatgpt/` directory. This review did not observe that set or treat it as completed.

## Distinct Metallic launcher request

The original destination for this separate scope is `docs/design/metallic-art-20261026/`. The issue describes Metallic as the main product and launcher hub, with Litha as an optional, disableable add-on. Recording this scope does not mark it implemented or expand the current Litha artwork task to all launcher assets.

- **Brand assets:** remake the existing “shiny bird” crow emblem in polished chrome/brushed silver with subtle violet edge light and a silhouette readable at 16px. Deliver a transparent 1024px symbol, a flat single-colour symbol, a rounded-square graphite app icon, and a horizontal lockup reading “Metallic” in a clean geometric sans. Palette: graphite, silver and violet.
- **Wallpaper source layers:** four scenes, with separately delivered transparent PNG layers at **3840×2160 or larger**, using the same framing within each scene. Claude intends to animate the layers with WebGL; a flattened scene alone does not meet this request.
- **Game tiles:** four **1920×1080, 16:9, no-text** images for Metallic RC, Metallic MC, Metallic RB and Metallic PX.
- **Litha cute set:** the six poses and full-body illustration listed above.

| Wallpaper | Requested layers |
| --- | --- |
| River valley, golden hour | Sky; far mountains; mid forest; river; black/white water-area mask; near grass/foreground. |
| Night metal city | Sky with stars; far skyline; mid buildings with lit windows; near rooftop; separate neon glow with no readable text. |
| Crystal cave | Back wall; crystals; separate crystal glow; floor; waterfall; waterfall mask. |
| Calm violet nebula | Deep sky; nebula clouds; star field; planet. |

Wallpaper direction is painterly but crisp, cinematic and consistent with the graphite/silver/violet brand; the river scene may be warmer. The issue explicitly asks for clean intentional design without garbled text, extra fingers or indistinct generated detail.

## Evidence and work state

No approved crow reference was supplied or visually inspected during this review. A filename search in this checkout's `assets/` and `docs/` did not locate one. The requested remake should be compared with the approved reference before claiming identity preservation.

At this review, this reviewer had generated **no artwork** and inspected no completed Litha outputs. No Litha-named PR or requested output directory was found in the earlier local search. Those observations are a snapshot, not evidence that another agent has not started generation. The generating agent should append the actual file list, dimensions, transparency checks and visual review results after producing the assets.

This record involved no board read-marker updates, board or GitHub replies, messages to Claude, account changes, native PC actions or publication. The issue's request to report filenames has been recorded, not executed by this review.

## Generation follow-up

The root agent subsequently created ten images with the built-in image-generation tool in its own isolated art branch: [three character sheets](../design/litha-concepts-20261026/chatgpt/README.md), [six chibi poses and one full-body illustration](../design/metallic-art-20261026/litha/README.md). Root and an independent reviewer inspected all ten. A [checksummed manifest](../design/litha-concepts-20261026/chatgpt/ASSET-MANIFEST.json) records decoded dimensions and alpha ranges.

The sheets are 1536×1024 RGB; the chibis are 1254×1254 RGBA and the full-body illustration is 1024×1536 RGBA. Chibi 1024px export and transparent-edge cleanup remain outstanding. No app integration, rigging or owner approval is claimed. The broader Metallic crow, layered wallpaper and game-tile deliverables remain open; no flattened image is being passed off as those editable layers. No message was posted to Claude or the issue by this follow-up.
