# Paper/Nexo/Blockbench and resource packs (Oct 2026)

- Paper/Purpur plugins differ from Fabric/NeoForge mods: detect server version/JDK, use documented API and plugin.yml or paper-plugin.yml. Folia has region/entity/global schedulers; never use Bukkit world operations from ordinary async threads. Gameplay grants, purchases and permissions stay server-authoritative.
- Java 26.3 resource packs use format **97.1** (data packs 121.0). Modern pack.mcmeta requires min_format [97,1] and max_format [97,1] for a 26.3-only pack. Check assets/<namespace>/items, models, textures, blockstates, font, atlases and sounds; validate references and pack merge collisions.
- Nexo is a paid Paper/Folia pack manager for items, blocks, armor, glyphs, furniture and auto-generated packs. Target exact licensed Nexo YAML versions; Oraxen/ItemsAdder use DIFFERENT adapters. Do not install commercial jars or invent config keys.
- Blockbench .bbmodel is editable source. Validate UVs, textures, UUIDs, pivots, outliner bones and animations, then choose the right exporter for Java items/displays, ModelEngine/BetterModel rigs or Bedrock geometry. Visual QA must run in-game.
- ItemDisplay/BlockDisplay/TextDisplay can animate props but do not supply collision, persistence or gameplay. Cosmetics, particles, mounts and VFX need performance budgets and attachment/visibility logic.
- Geyser does not automatically convert all Java custom assets to Bedrock. Version-pin mappings and extensions; test Java and Bedrock separately.
- STAR: workspace_minecraft_audit and workspace_minecraft_inspect are read-only; workspace_minecraft_item_scaffold creates a 2D item pack from an existing PNG; workspace_minecraft_package exports a ZIP. Writes require opt-in; no live server edits. Full guide: docs/research/minecraft_asset_engineering_2026-10-18.md.
- Report stages separately: planned, generated, compiled, disposable-server loaded, client rendered, deployed.
