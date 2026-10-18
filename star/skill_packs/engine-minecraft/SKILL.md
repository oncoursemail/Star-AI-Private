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

## Paper/Nexo/Blockbench and resource packs (Oct 2026)
- Paper/Purpur plugins differ from Fabric/NeoForge mods: detect server version/JDK, use documented API and plugin.yml or paper-plugin.yml. Folia has region/entity/global schedulers; never use Bukkit world operations from ordinary async threads. Gameplay grants, purchases and permissions stay server-authoritative.
- Java 26.3 resource packs use format **97.1** (data packs 121.0). Modern pack.mcmeta requires min_format [97,1] and max_format [97,1] for a 26.3-only pack. Check assets/<namespace>/items, models, textures, blockstates, font, atlases and sounds; validate references and pack merge collisions.
- Nexo is a paid Paper/Folia pack manager for items, blocks, armor, glyphs, furniture and auto-generated packs. Target exact licensed Nexo YAML versions; Oraxen/ItemsAdder use DIFFERENT adapters. Do not install commercial jars or invent config keys.
- Blockbench .bbmodel is editable source. Validate UVs, textures, UUIDs, pivots, outliner bones and animations, then choose the right exporter for Java items/displays, ModelEngine/BetterModel rigs or Bedrock geometry. Visual QA must run in-game.
- ItemDisplay/BlockDisplay/TextDisplay can animate props but do not supply collision, persistence or gameplay. Cosmetics, particles, mounts and VFX need performance budgets and attachment/visibility logic.
- Geyser does not automatically convert all Java custom assets to Bedrock. Version-pin mappings and extensions; test Java and Bedrock separately.
- STAR: workspace_minecraft_audit is read-only; workspace_minecraft_package is opt-in ZIP export; neither edits running servers. Full guide: docs/research/minecraft_asset_engineering_2026-10-18.md.
- Report stages separately: planned, generated, compiled, disposable-server loaded, client rendered, deployed.

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

