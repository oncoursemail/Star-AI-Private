"""Exact API facts for Minecraft Java plugin/mod questions (Paper/Spigot, Velocity, Fabric, NeoForge; Minecraft
1.21.11), added to the last user turn like the general helper's notes (the system prompt stays the cached prefix).

Every name below was compiled against the official API jars by the warm javac service (server/mesh/verify/jvm,
2026-10-29: paper-api 1.21.11-R0.1, spigot-api 1.21.11-R0.1, velocity-api 3.5.1, Fabric yarn 1.21.11+build.6 +
Fabric API 0.141.6, NeoForge 21.11.48). The mc-plugins eval measured the first-try effect
(docs/agents/mc-plugins-20261029.md).

    platform, note = facts_for(question)        # (None, "") when the question is not about a plugin/mod
    hdr = apply(req)                            # appends the note to the last user turn -> {"X-Mesh-MCJava": platform}
"""
from __future__ import annotations

import re

DEFAULTS = {"mc_java_facts": True}    # ("mc_facts" is the mc-data lane's vanilla facts block)

COMMON = ("(Facts for Litha, not from the user: checked against the real Minecraft 1.21.11 API jars. Use exactly these "
          "names; never invent classes or methods. Give every file the user needs, each with its path.)\n")
PAPER = (
    "Paper 1.21.11 plugin facts:\n"
    "- plugin.yml: name, version, main (full class name of the class that extends JavaPlugin), api-version: '1.21'. "
    "Every getCommand(\"x\") needs x under commands: in plugin.yml, or getCommand returns null.\n"
    "- paper-plugin.yml has NO commands: section; register commands in onEnable with Brigadier: "
    "getLifecycleManager().registerEventHandler(LifecycleEvents.COMMANDS, event -> event.registrar().register("
    "Commands.literal(\"fly\").executes(ctx -> { CommandSender s = ctx.getSource().getSender(); ... return "
    "Command.SINGLE_SUCCESS; }).build(), \"description\")); imports io.papermc.paper.command.brigadier.Commands, "
    "io.papermc.paper.plugin.lifecycle.event.types.LifecycleEvents, com.mojang.brigadier.Command.\n"
    "- Text is Adventure: Component.text(\"Hi\", NamedTextColor.GOLD) (net.kyori.adventure.text.Component, "
    "net.kyori.adventure.text.format.NamedTextColor); player.sendMessage(component), player.sendActionBar(component), "
    "event.joinMessage(component), player.playerListName(component), event.motd(component) on ServerListPingEvent, "
    "signChangeEvent.line(i) / line(i, component); & codes: LegacyComponentSerializer.legacyAmpersand().deserialize(s). "
    "ChatColor is deprecated on Paper.\n"
    "- Boss bar: BossBar.bossBar(Component, 1.0f, BossBar.Color.RED, BossBar.Overlay.PROGRESS) "
    "(net.kyori.adventure.bossbar.BossBar), player.showBossBar(bar) / hideBossBar(bar), bar.progress(f), bar.name(c).\n"
    "- Max health: player.getAttribute(Attribute.MAX_HEALTH).getValue() (GENERIC_MAX_HEALTH and getMaxHealth() are "
    "gone/deprecated). setFireTicks(0) clears fire.\n"
    "- PersistentDataContainer: NamespacedKey key = new NamespacedKey(plugin, \"kills\"); "
    "player.getPersistentDataContainer().getOrDefault(key, PersistentDataType.INTEGER, 0) / set(key, "
    "PersistentDataType.INTEGER, n); keys are NamespacedKey, never a String. Item meta: item.editMeta(meta -> "
    "meta.getPersistentDataContainer().set(...)).\n"
    "- EntityDeathEvent: e.getEntity() is a LivingEntity, e.getEntity().getKiller() is a Player or null.\n"
    "- Scheduler: Bukkit.getScheduler().runTaskTimer(plugin, task -> {...}, 0L, 20L) (task.cancel() stops it); "
    "runTaskAsynchronously(plugin, () -> ...) for file IO, then runTask(plugin, ...) to touch the world again.\n"
    "- saveDefaultConfig() needs a config.yml in src/main/resources (show it), then getConfig().getString(\"path\"); "
    "reloadConfig() reloads.\n"
    "- Register listeners: getServer().getPluginManager().registerEvents(listener, this); handlers need @EventHandler.\n")
SPIGOT = (
    "Spigot 1.21.11 (Spigot API only, no Paper/Adventure methods):\n"
    "- plugin.yml as above (name, version, main, api-version: '1.21', commands:).\n"
    "- Text is String + ChatColor (org.bukkit.ChatColor): player.sendMessage(ChatColor.GREEN + \"Hi\"); action bar: "
    "player.spigot().sendMessage(ChatMessageType.ACTION_BAR, new TextComponent(\"hi\")) (net.md_5.bungee.api).\n"
    "- player.getPing() is the ping in ms. Chat: AsyncPlayerChatEvent, e.getMessage() / e.setMessage(s).\n")
VELOCITY = (
    "Velocity 3.5 proxy plugin facts:\n"
    "- Main class: @Plugin(id = \"lowercase-id\", name = \"Name\", version = \"1.0.0\") "
    "(com.velocitypowered.api.plugin.Plugin); constructor @Inject (com.google.inject.Inject) public "
    "MyPlugin(ProxyServer server, org.slf4j.Logger logger). The annotation processor writes velocity-plugin.json.\n"
    "- Start: @Subscribe public void onInit(ProxyInitializeEvent e) (com.velocitypowered.api.event.Subscribe, "
    "...event.proxy.ProxyInitializeEvent).\n"
    "- Commands: CommandManager cm = server.getCommandManager(); cm.register(cm.metaBuilder(\"hub\").aliases(\"lobby\")"
    ".plugin(this).build(), (SimpleCommand) inv -> { if (!(inv.source() instanceof Player p)) return; ... }); "
    "inv.arguments() is String[]; inv.source().hasPermission(\"x\").\n"
    "- Send to a backend: server.getServer(\"lobby\").ifPresent(s -> player.createConnectionRequest(s).fireAndForget()); "
    "server.getAllServers() -> RegisteredServer: getServerInfo().getName(), getPlayersConnected().size(); "
    "server.getPlayerCount().\n"
    "- Events: PostLoginEvent (e.getPlayer().getUsername()), ServerConnectedEvent (e.getServer().getServerInfo()), "
    "LoginEvent (deny: e.setResult(ResultedEvent.ComponentResult.denied(Component.text(\"..\", NamedTextColor.RED)))), "
    "ProxyPingEvent (e.setPing(e.getPing().asBuilder().description(component).maximumPlayers(n).build())). Player is "
    "com.velocitypowered.api.proxy.Player; text is Adventure Component.\n")
FABRIC = (
    "Fabric 1.21.11 mod facts (Yarn names, Fabric API 0.141.6):\n"
    "- Entry: class implements net.fabricmc.api.ModInitializer { public void onInitialize() }. fabric.mod.json: "
    "\"schemaVersion\": 1, \"id\": \"lowercase_id\", \"version\": \"1.0.0\", \"entrypoints\": {\"main\": "
    "[\"com.example.MyMod\"]}, \"depends\": {\"fabricloader\": \">=0.16\", \"minecraft\": \"~1.21.11\", "
    "\"fabric-api\": \"*\"}; list \"mixins\": [\"modid.mixins.json\"] only when you show that file.\n"
    "- Commands: CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> "
    "dispatcher.register(CommandManager.literal(\"hello\").executes(ctx -> { ServerPlayerEntity p = "
    "ctx.getSource().getPlayer(); ctx.getSource().sendFeedback(() -> Text.literal(\"Hi\"), false); return 1; }))); "
    "imports net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback, net.minecraft.server.command."
    "CommandManager, net.minecraft.text.Text, net.minecraft.server.network.ServerPlayerEntity.\n"
    "- Join: ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> handler.player.sendMessage("
    "Text.literal(\"Welcome\").formatted(Formatting.GREEN), false)) (net.fabricmc.fabric.api.networking.v1).\n"
    "- Block break: PlayerBlockBreakEvents.AFTER.register((world, player, pos, state, blockEntity) -> { if "
    "(state.isOf(Blocks.DIAMOND_ORE)) ... }). Ticks: ServerTickEvents.END_SERVER_TICK.register(server -> ...).\n"
    "- Items (1.21.2+ need a registry key in the settings): Identifier id = Identifier.of(MOD_ID, \"ruby\"); "
    "Item RUBY = Registry.register(Registries.ITEM, id, new Item(new Item.Settings().registryKey(RegistryKey.of("
    "RegistryKeys.ITEM, id)))); creative tab: ItemGroupEvents.modifyEntriesEvent(ItemGroups.INGREDIENTS).register("
    "entries -> entries.add(RUBY)).\n"
    "- With official Mojang names (loom.officialMojangMappings()) the classes are net.minecraft.commands.Commands, "
    "net.minecraft.network.chat.Component, net.minecraft.server.level.ServerPlayer, "
    "ctx.getSource().sendSuccess(() -> Component.literal(\"..\"), false).\n")
NEOFORGE = (
    "NeoForge 21.11 (Minecraft 1.21.11) mod facts (official Mojang names):\n"
    "- @Mod(MyMod.MODID) (net.neoforged.fml.common.Mod) on a public class whose constructor is "
    "public MyMod(IEventBus modBus, ModContainer container). Game events: NeoForge.EVENT_BUS.addListener(this::method) "
    "(net.neoforged.neoforge.common.NeoForge); mod-bus events (registries, creative tabs): modBus.addListener(...).\n"
    "- src/main/resources/META-INF/neoforge.mods.toml (not mods.toml): modLoader=\"javafml\", loaderVersion=\"[1,)\", "
    "license=\"MIT\", then [[mods]] modId=\"same_as_MODID\", version=\"1.0.0\", displayName=\"..\".\n"
    "- Commands: RegisterCommandsEvent e -> e.getDispatcher().register(Commands.literal(\"hello\").executes(c -> { "
    "c.getSource().sendSuccess(() -> Component.literal(\"Hi\"), false); return 1; })) (net.minecraft.commands.Commands, "
    "net.minecraft.network.chat.Component, net.neoforged.neoforge.event.RegisterCommandsEvent).\n"
    "- Items: DeferredRegister.Items ITEMS = DeferredRegister.createItems(MODID); DeferredItem<Item> SAPPHIRE = "
    "ITEMS.registerSimpleItem(\"sapphire\"); ITEMS.register(modBus); creative tab: BuildCreativeModeTabContentsEvent "
    "e -> if (e.getTabKey() == CreativeModeTabs.INGREDIENTS) e.accept(SAPPHIRE).\n"
    "- Events: PlayerEvent.PlayerLoggedInEvent (e.getEntity() is the Player; e.getEntity().getPersistentData() is a "
    "CompoundTag: getBooleanOr(\"key\", false) / putBoolean), BlockEvent.BreakEvent (e.getState().is(BlockTags.LOGS), "
    "e.getPlayer().giveExperiencePoints(5)), ServerTickEvent.Post (e.getServer().getPlayerList()"
    ".broadcastSystemMessage(Component.literal(\"..\"), false)).\n"
    "- Config: ModConfigSpec.Builder b = new ModConfigSpec.Builder(); ModConfigSpec.ConfigValue<String> GREETING = "
    "b.define(\"greeting\", \"Hello!\"); ModConfigSpec SPEC = b.build(); container.registerConfig(ModConfig.Type.COMMON, "
    "SPEC); read with GREETING.get().\n")

TOPIC = re.compile(r"\b(minecraft|paper|spigot|bukkit|velocity|fabric|neoforge|forge)\b", re.I)
KIND = re.compile(r"\b(plugin|mod|mods|modding|plugin\.yml|fabric\.mod\.json|mods\.toml|mixin|loom|mdk)\b", re.I)
PLATFORMS = [("velocity", re.compile(r"\bvelocity\b", re.I), VELOCITY),
             ("neoforge", re.compile(r"\bneo\s?forge\b", re.I), NEOFORGE),
             ("fabric", re.compile(r"\bfabric\b", re.I), FABRIC),
             ("spigot", re.compile(r"\bspigot\b", re.I), SPIGOT),
             ("paper", re.compile(r"\b(paper|bukkit|spigot)\b", re.I), PAPER)]


def facts_for(question: str) -> tuple[str | None, str]:
    """The platform and its facts note, or (None, "") when the question is not a Java plugin/mod question."""
    if not question or not TOPIC.search(question) or not KIND.search(question):
        return None, ""
    for name, rx, text in PLATFORMS:
        if rx.search(question):
            if name == "spigot" and re.search(r"\bpaper\b", question, re.I) and \
                    not re.search(r"\b(not|no|without)\s+(the\s+)?paper\b", question, re.I):
                continue                       # "Spigot/Paper plugin": Paper facts
            return name, COMMON + text
    return None, ""


def apply(req: dict) -> dict:
    msgs = req.get("messages")
    if not isinstance(msgs, list) or not msgs or not isinstance(msgs[-1], dict) or msgs[-1].get("role") != "user" \
            or not isinstance(msgs[-1].get("content"), str):
        return {}
    platform, note = facts_for(msgs[-1]["content"])
    if not platform:
        return {}
    msgs[-1] = {**msgs[-1], "content": msgs[-1]["content"] + "\n\n" + note}
    return {"X-Mesh-MCJava": platform}
