---
name: engine-minecraft
description: Minecraft modding: Java 26.3 with Fabric or NeoForge (Mojang names, mixins), data packs, and Bedrock 26.50 add-ons with Script API 2.x. Use when a request names Minecraft, Fabric, NeoForge or Bedrock.
---
# engine-minecraft
## Scope
Java 26.3 (Sept 2026, Java 25), Fabric API 0.162+26.3, NeoForge 26.3.0.x, Bedrock 26.50 with `@minecraft/server` 2.10.0. Year-based versions (1.21.11 -> 26.1 -> 26.3; no 1.22). Check `gradle.properties` or `manifest.json` first.

## Core model
- Java: logical server (also in singleplayer) + client; 20 ticks/s; registries keyed by `ResourceKey`/`Identifier`.
- Since 26.1 the jar is unobfuscated: Mojang names everywhere. Yarn ended at 1.21.11.
- Fabric: `fabric.mod.json` entrypoints, Fabric API events, Mixins. NeoForge: `@Mod` class, mod bus (constructor `IEventBus`) + `NeoForge.EVENT_BUS`.
- Data packs: `pack.mcmeta` + `data/<ns>/function/*.mcfunction`.
- Bedrock: behavior pack (JSON + JS) + resource pack (visuals).

## Idioms
- Fabric Gradle: `id 'net.fabricmc.fabric-loom'`, `implementation` deps, no mappings line, Java 25.
- Ids: `Identifier.fromNamespaceAndPath("modid", "ruby")`; key: `ResourceKey.create(Registries.ITEM, id)`.
- Fabric items/tabs: see Skeleton (`CreativeModeTabEvents` is in `api.creativetab.v1`).
- NeoForge: `DeferredRegister.createItems(MODID)`, `ITEMS.registerSimpleItem("ruby", p -> p)`, `ITEMS.register(modEventBus)`.
- Game logic only on the server: `if (!level.isClientSide())`.
- Bedrock 2.x: register custom components in `system.beforeEvents.startup`; touch the world in `world.afterEvents.worldLoad`; loops via `system.runInterval(fn, ticks)`.

## Pitfalls
1. Yarn names (`PlayerEntity`, `World`, `Text.literal`, `ItemGroup`) on 26.x: use Mojang names (`Player`, `Level`, `Component.literal`, `CreativeModeTab`).
2. `ResourceLocation` was renamed `Identifier` (package `net.minecraft.resources`); `new ResourceLocation(a, b)` is gone.
3. Items/blocks need `Item.Properties.setId(key)` (1.21.2+) or registration throws.
4. `InteractionResultHolder` removed (1.21.2+): `Item.use` returns `InteractionResult`.
5. Item visuals need `assets/<ns>/items/<id>.json` plus `models/item/<id>.json` (1.21.4+).
6. Forge vs NeoForge: no `net.minecraftforge`, `MinecraftForge.EVENT_BUS`, `FMLJavaModLoadingContext` or `mods.toml` in NeoForge; it uses `net.neoforged`, `NeoForge.EVENT_BUS`, `META-INF/neoforge.mods.toml`.
7. Fabric renamed API for Mojang names: `ItemGroupEvents` -> `CreativeModeTabEvents`, `KeyBindingHelper` -> `KeyMappingHelper`.
8. Data pack folders are singular since 1.21 (`function/`, `recipe/`, `loot_table/`, `tags/function/`); plural folders are ignored.
9. Item NBT in commands is dead since 1.20.5 (use `[minecraft:custom_name="X"]`); `pack.mcmeta` uses `min_format`/`max_format` (26.3 data: 121).
10. Bedrock 2.x: `worldInitialize` is gone (`system.beforeEvents.startup` / `world.afterEvents.worldLoad`); `runCommandAsync` removed (use `runCommand`); `isValid` is a property; world access at top level throws (early execution).
11. Client-only classes (`Minecraft`, renderers) in common code crash servers.

## Roblox to Minecraft
Part -> block (`BlockState`) or display entity; Model -> structure / custom entity
Script -> mod common code, mcfunction, or Bedrock behavior script; LocalScript -> Java client entrypoint
RemoteEvent -> `CustomPacketPayload` + `StreamCodec` (Bedrock: not needed)
DataStore -> `SavedData` / data attachments; Bedrock dynamic properties (world-bound)
Players -> `world.getPlayers()` (Bedrock); Humanoid -> `LivingEntity`/`Player`
Heartbeat -> server tick event / `#minecraft:tick` / `system.runInterval(fn, 1)`
task.wait -> tick counters; Bedrock `await system.waitTicks(n)`
CollectionService tags -> registry tags; ScreenGui -> `Screen` / Bedrock forms
UserInputService -> `KeyMapping`; playtest -> `runClient`, Bedrock `/reload`

## Skeleton
```java
public class CoinMod implements ModInitializer {
    public static final ResourceKey<Item> COIN_KEY =
        ResourceKey.create(Registries.ITEM, Identifier.fromNamespaceAndPath("coinmod", "coin"));
    public static final Item COIN = Registry.register(BuiltInRegistries.ITEM, COIN_KEY,
        new Item(new Item.Properties().setId(COIN_KEY).stacksTo(64)));

    @Override
    public void onInitialize() {
        CreativeModeTabEvents.modifyOutputEvent(CreativeModeTabs.INGREDIENTS)
            .register(tab -> tab.accept(COIN));
    }
}
```

## Verification
Java: `./gradlew build`, then `./gradlew runClient` and read the log. Bedrock: use development_behavior_packs, `/reload`, read the content log. Say "not built" unless a build ran.

## Paper, Nexo, Blockbench and server-side visuals (2026-10-18)

- Paper/Purpur plugins are different from Fabric/NeoForge mods. Start from the owner's exact server version and Java toolchain. Use Paper API with plugin.yml or paper-plugin.yml; server-authoritative item grants, permissions and inventory actions. Do not call Bukkit world APIs from async callbacks. Folia requires its region/entity/global scheduler and actual integration tests; a folia-supported manifest flag is insufficient.
- Minecraft 26.3 resource-pack format **97.1** (data pack 121.0). For a 26.3-only Java pack use min_format [97,1] and max_format [97,1] within pack.mcmeta. Older formats differ. Asset folders include assets/namespace/items (modern item definitions), models, textures, blockstates, font, sounds, atlases and GUI sprites. Validate model parents/texture references and collisions when merging packs.
- Nexo is a *commercial* Paper/Folia plugin for custom items/blocks/armor/furniture/glyphs and pack generation. Generate YAML only against an identified licensed Nexo version. External pack merging, item components and glyphs have version-specific rules. Oraxen and ItemsAdder are separate providers with incompatible configuration syntax; never invent or blindly mix their schemas.
- Blockbench .bbmodel is editable project source, not a universal server asset. Check cubes, UUIDs, pivots, UV/textures, outliner bones, rig animations and export target. Java inventory item models, custom display transforms, ModelEngine/BetterModel rigs and Bedrock .geo.json need different export pipelines. Never claim model quality without visual previews and an in-game render test.
- Paper BlockDisplay/ItemDisplay/TextDisplay support interpolated visual entities. For furniture, pets, mounts, cosmetics and spells, plan hitboxes, gameplay logic, attachment points, persistent state, sound and culling separately. Particle/entity counts, textures, glyph size and animation update rates affect client/server performance.
- Geyser/Floodgate do not magically turn arbitrary Java custom assets into Bedrock assets. Provide Java/Bedrock compatibility matrix and version-pinned mapping/extension checks; actual Bedrock device tests are essential.
- STAR workspace tools: workspace_minecraft_audit (read-only Java pack directory/ZIP or Blockbench .bbmodel) and workspace_minecraft_package (deterministic Java pack ZIP, only when workspace edits are explicitly permitted). Neither installs plugins, runs a Minecraft server or creates a visual model.
- Always distinguish 'planned', 'files generated', 'compiled', 'loaded in disposable server', 'rendered on actual Java/Bedrock client' and 'deployed'. Consult docs/research/minecraft_asset_engineering_2026-10-18.md for the full architecture and primary documentation links.
