# STAR Minecraft Engineering: resource packs, models, plugins, mods, infrastructure

Research checkpoint 2026-10-18. This is a technical architecture/reference, NOT proof of installation or live server changes.

## Verified baselines and compatibility

Java Edition 26.3 released 2026-09-15 with resource-pack format **97.1**, data-pack format **121.0** and a Java 25 runtime. Projects may target earlier releases; always inspect the exact server version, Paper/Folia build, Java runtime, installed plugins, and client protocol support before generating code.

Java resource packs from 1.21.9 require min_format/max_format. An example for **26.3 only** is JSON with a top-level pack object containing description "Metallic" and min_format [97,1] and max_format [97,1]. For 1.21.4 the integer pack_format was 46. Use version-specific metadata templates. Do not copy outdated CustomModelData/item rendering examples into modern item definitions without checking the exact version.

A resource pack contains client-side assets, not authoritative game logic. Java and Bedrock pack formats differ; Geyser does not automatically translate every Java model/entity/GUI into working Bedrock content.

Core sources:
- https://www.minecraft.net/en-us/article/minecraft-java-edition-26-3
- https://docs.papermc.io/paper/dev/
- https://docs.papermc.io/paper/dev/plugin-yml/
- https://docs.papermc.io/paper/dev/folia-support/
- https://docs.papermc.io/velocity/player-information-forwarding/
- https://geysermc.org/wiki/geyser/custom-items/
- https://learn.microsoft.com/en-us/minecraft/creator/documents/addcustomitems
- https://docs.fabricmc.net/
- https://docs.neoforged.net/
- https://blockbench.net/

## Unified Minecraft content compilation

Model every feature (e.g. metallic:azure_sword, metallic:wings, metallic:cloud_pet) with an immutable asset ID, creator brief, style reference, owner/licensing, target MC versions, animations, collision and gameplay behavior, dependencies and target profiles.

The source content graph contains:
1. Editable art: Blockbench project, Blender source where necessary, textures, source font, sound and spritesheets.
2. Semantic definitions: item, block, furniture, cosmetic, mount, entity, equipment slot, crafting recipe, loot, UI, particles, physics, permissions and gameplay state.
3. Export adapters: Java vanilla resource pack; plugin-managed Nexo/Oraxen/ItemsAdder pack; Paper plugin; Fabric/NeoForge mod or datapack; Bedrock visual/behavior packs and Geyser compatibility mappings.
4. Verification: schema and reference graph, deterministic archive/hash, licensing check, disposable server startup, actual client render/animation tests, production roll-back artifact.
5. Release manifest: exact software versions, pack checksum, model sources, provider version, compatible devices, test evidence and performance budget.

One creative request should lead to a coherent set of version-pinned outputs, NOT a collection of unrelated generated files. Do not overwrite user-edited files. Stage previews and diffs first.

## Java resource packs: complete learning scope

- pack.mcmeta, pack.png, format ranges, ZIP root rules, server pack delivery, HTTPS hosting, SHA-1 for traditional server resource pack protocol and SHA-256 for build reproducibility, downloads and client cache behavior.
- assets/namespace directory structure: modern item definitions, item/block models, blockstates, custom model data transitions, parent models, texture aliases, inventories and world rendering.
- Animated textures with PNG metadata, UV space, cube coordinates, alternate predicates/components, font providers/glyphs, private-use glyph ranges, Unicode conflicts.
- Sounds: sounds.json, Ogg, spatial cues, subtitles, volume/pitch, language files and translations.
- GUIs: vanilla inventory menus versus client mods, sprites, resource-pack font GUIs, scoreboards, bossbars, actionbars, text displays, HUD overlays.
- Custom armor/trim and equipment layers, glint overlays, culling, emissive/glow techniques when supported and modded-client shader features. Never assume a shader works on every client.
- Resource conflicts when packs merge: duplicate paths, namespace case, collisions between pack manager assigned item IDs, glyph codepoints, model predicates, override ordering.
- JSON syntax/semantic checks, texture dimensions, model/textures dependency graphs, failed asset fallbacks, sound refs and missing translations, oversized atlases and texture memory.
- Version-aware testing with a Minecraft client; automated JSON checks alone are not a visual approval.

## Blockbench and professional model production

Primary editor: https://blockbench.net/ . Install the official stable desktop release on a graphical desktop; the current remote Ubuntu machines are headless. STAR should not claim Blockbench was installed on the user's offline Windows PC.

- Source files are Blockbench .bbmodel, textures and animation timelines. Check model format, JSON, element UUIDs, outliner bones, positions, rotations, pivot, UV scale, face textures, unused UVs, texture palette consistency and animation event markers.
- Model targets: Java block/item models; entity display transforms; ModelEngine and BetterModel-specific animated rigs; Bedrock geometry, entity animations and animation controllers; modded GeckoLib rigs where allowed.
- Style rules: hand-authored pixel detail; consistent material palette; avoid generated random texture noise; compare front/back/side/equipment/inventory/first-person views; inspect texture seams, occlusion, scales, pivot jitter and animation loop transitions.
- Animation quality: anticipation/recovery, controlled easing, attack timing, bone parenting, secondary motion, pose readability, loop fidelity, cosmetics physics approximations. Exported rig and display interpolation need tests in actual game.
- Cosmetics: hats, hairstyles, wings, backpacks, pets, companions, mounts, capes where technically permitted, trails, auras, footsteps, victory emotes, nameplates and season skins. Each needs a separate attachment method, persistence rules, visibility controls and device performance budget.
- Functional furniture and pets require hitboxes, seating/follow logic and server authority. A visual model alone does not implement interaction.
- Compare off-the-shelf plugins only under their license and exact version compatibility. See ModelEngine https://mythiccraft.io/ and BetterModel https://github.com/toxicity188/BetterModel and GeckoLib https://github.com/bernie-g/geckolib.

## Plugin content providers: Nexo, Oraxen, ItemsAdder

Nexo documentation: https://docs.nexomc.com/
Nexo is a commercial plugin supporting items, blocks, armor, glyphs, furniture and generated/dispatched packs. It is tested on Paper/Folia with per-version support boundaries. Its configuration includes items, glyphs and resourcepack-related sections; external packs can be merged. It supports optional obfuscation/caching and various item-component approaches. Never guess the syntax from a different version.

For a first Nexo provider implement parse_existing -> plan -> render_preview -> generate -> validate -> diff -> stage -> verify -> rollback. Compile STAR's neutral content schema to the exact licensed Nexo version and read-only inspect existing configurations before writing. Test item, glyph and furniture fixtures before adding animation/VFX. Do not download, distribute or install commercial jars without the owner's licensed copy.

Oraxen documentation: https://docs.oraxen.com/
ItemsAdder documentation: https://itemsadder.devs.beer/
These need independent parsers and exporters; they are not Nexo YAML aliases. Avoid operating multiple conflicting pack generators until an explicit one-owner pack strategy is selected. Oraxen and ItemsAdder must be version-pinned before compiling.

Alternatives: Packman https://github.com/seksea/packman for plugin-based custom pack composition; Fabric Polymer https://github.com/Patbox/polymer for server-side custom content and generated packs. Polymer is NOT a Paper plugin and does NOT automatically convert any installed mod into vanilla-client content.

## Plugin and mod coding: Java mastery

Paper/Purpur: Java toolchains (Java 25 for current 26.3, version-specific for older versions), Gradle/Maven, plugin.yml or paper-plugin.yml, exact Paper API, event lifecycle, Adventure components, permissions, persistent data containers, commands, InventoryHolder/menu isolation, inventory transaction and duping defenses, data serialization and DB migrations.

Display entities: BlockDisplay, ItemDisplay and TextDisplay for static/dynamic props, UI world text, transformations, teleport/interpolation, culling, visibility and particle/VFX stage sequences. An ItemDisplay cannot magically create custom collision: separate it from real collision/interaction logic.

Scheduling: never block a world tick with network requests/database work; never call unsafe Bukkit world APIs asynchronously. For Folia, use ownership-aware global/region/entity scheduling. The folia-supported flag alone does not prove compatibility.

Fabric / NeoForge: registries, events, Mixins, networking, source sets separating common/server/client, data generation, mappings, world generation, resources and animations. For modern 26.x Mojang naming and runtime changes, inspect project metadata; don't copy old Yarn/Forge APIs.

Datapacks and commands: entity selectors, scoreboard, commands/functions, scheduled functions, advancements, predicates, recipes, loot, tags, item data components, enchantments, dimensions, structures, worldgen and interaction entities. Current datapack directories use singular names for many categories. Profile heavy tick functions rather than running an unbounded loop every tick.

Integrity and safety: item grants, purchases, achievements, rank permissions and economy changes must be server-authoritative; avoid trusting client display/meta fields. Secrets must not enter plugin configs in Git. Treat community examples as untrusted until tested.

## Bedrock/Geyser crossplay

Keep Java and Bedrock visual exports separate; maintain a feature compatibility matrix: Java-only, vanilla Bedrock/Geyser mappings, Geyser-specific extension, and native Bedrock behavior pack. Nexo's Scaffolding extension has documented gaps for some furniture/entity/GUI features. Validate a Bedrock client on an actual supported device rather than assuming translation correctness.

Bedrock: two manifests with UUIDs (behavior and resource), versioned module declarations, geometry .geo.json, animation controllers, render controllers, item/entity JSON, Script API and UI forms. Bedrock keyboard/touch/gamepad needs distinct UX QA. Resource packs cannot perform unrestricted server Java actions.

Sources: https://geysermc.org/wiki/geyser/ and https://learn.microsoft.com/en-us/minecraft/creator/

## Server network and infrastructure

- Inventory: exact Paper/Folia/Velocity/Geyser/Floodgate versions, online players, TPS/MSPT, memory, CPU, Java JDK, installed plugins and mods, world configuration, databases, available disks, session allocation and region placement.
- Proxy layer: Velocity for Java; Geyser/Floodgate ingress for Bedrock. Firewall backends, enforce authenticated proxy forwarding, protect private databases and management ports, rotate secrets.
- Server orchestration: container/systemd templates, minigame instances, lobby/fallback routing, graceful drain, queueing, backups and restore drills. Each world is bounded by actual tick budgets; thousands of players spread over independent servers is fundamentally different from thousands on a single game thread.
- Observability: spark and JFR profiles, p50/p95/p99 MSPT, stalled ticks, GC, entity counts, chunk-generation stalls, per-world memory pressure, network packet rates, login/pack download and Geyser translation errors.
- Reliability: staged deployments, artifact SHA checks, blue/green or canary server groups, rapid rollback, database schema migrations, retention and tested restore.
- Permission model: read-only discovery by default. Workspace edits require owner opt-in; production plugin installs, config changes, server restarts and firewall/network changes require explicit authorization with backups and rollback.

## Implementation phases

**Phase A (this branch):** offline, workspace-bound Java pack audits for directory/ZIP, pack.mcmeta formats, JSON/PNG/Ogg checks and missing model warnings; Blockbench .bbmodel structural checks; read-only server folder, plugin/mod JAR metadata and sanitized settings inventory; Java 2D item pack generator using an owner-supplied CRC-verified PNG; deterministic ZIP exporter. Generating items and ZIPs requires workspace edit permission. Nothing deploys or runs JARs. This phase is NOT a Blockbench visual exporter or live game test.

**Phase B:** versioned official-doc retrieval with version citations; existing plugin/server inventory, syntax-aware YAML config parsers, ContentSpec schema and asset dependency graphs; Nexo source fixture generation plus Blockbench visual QA exporters.

**Phase C:** full Java plugin generator and Gradle test sandbox, disposable Paper/Folia integration tests, display entity animation test lab, static Java linters and JVM profile benchmarks.

**Phase D:** Nexo/Oraxen/ItemsAdder provider adapters, Bedrock exporter, Geyser mapping and extension checks with true cross-client screenshots, automated regressions.

**Phase E:** production permissions, network health dashboard, canary rollouts, backup verification, AI-assisted diagnosis with evidence and reversible changes.

## Non-negotiable release gates

Research != implementation; source code != tested output; a passing unit suite != Minecraft visual correctness; a PR != a shipped Windows installer; an offline pack builder != live server management.

Each release must report exact Minecraft/JDK/plugin versions, test machine specs, compiler and import logs, asset-model references, actual client screenshots, Java/Bedrock parity, license provenance, 99th-percentile MSPT under controlled gameplay scenarios, known limitations and an undo/rollback route.

Developer note: keep STAR's existing Minecraft engine skill pack and expand it; don't duplicate the old Fabric/NeoForge/Bedrock research. Until evaluated and promoted, optional engine packs remain behind STAR_SKILL_PACKS rather than being silently activated.
