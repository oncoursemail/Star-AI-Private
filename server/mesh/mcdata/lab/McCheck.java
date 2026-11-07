// The game's own parsers as a checker, without starting a server (no world, no network, no EULA screen): the same
// classes the data generator uses. Reads jobs (one JSON object per line) on stdin, writes one result line per job.
//   job:    {"id": "...", "commands": ["give @s stone", ...], "files": {"data/ns/recipe/x.json": "{...}", ...}}
//   result: {"id": "...", "commands": [{"i": 0, "ok": true|false, "error": "..."}],
//            "files": [{"path": "...", "ok": true|false|null, "error": "..."}]}
// Obfuscated 1.21.x jars: names come from Mojang's official server_mappings.txt (argument 1); 26.x has real names.
//   java -cp cls:server.jar:libraries/* starmc.McCheck [server_mappings.txt]
package starmc;
import com.google.gson.*;
import com.mojang.brigadier.*;
import com.mojang.brigadier.context.*;
import com.mojang.serialization.*;
import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

public class McCheck {
    static final Map<String, String> CLS = new HashMap<>();             // real -> obf class name
    static final Map<String, Map<String, String>> MEM = new HashMap<>(); // real class -> "name(args)" / field -> obf

    static void loadMappings(Path p) throws IOException {
        String cur = null;
        for (String line : Files.readAllLines(p)) {
            if (line.startsWith("#") || line.isBlank()) continue;
            if (!line.startsWith(" ")) {
                String[] a = line.split(" -> ");
                cur = a[0];
                CLS.put(cur, a[1].substring(0, a[1].length() - 1));
                MEM.put(cur, new HashMap<>());
            } else if (cur != null && !line.trim().startsWith("#")) {
                String s = line.trim();
                String[] a = s.split(" -> ");
                String left = a[0].replaceFirst("^\\d+:\\d+:", "");
                String[] tn = left.split(" ", 2);
                String key = tn.length > 1 ? tn[1].replaceAll(":\\d+:\\d+$", "") : left;
                MEM.get(cur).put(key, a[1]);
            }
        }
    }

    static String obf(String real) {
        String base = real.contains("$") && !CLS.containsKey(real) ? real : real;
        return CLS.getOrDefault(base, real);
    }

    static Class<?> C(String real) throws ClassNotFoundException {
        switch (real) {
            case "int": return int.class;
            case "boolean": return boolean.class;
            case "long": return long.class;
            case "float": return float.class;
            case "double": return double.class;
        }
        if (real.endsWith("[]")) return java.lang.reflect.Array.newInstance(C(real.substring(0, real.length() - 2)), 0).getClass();
        return Class.forName(obf(real));
    }

    static String memberName(String cls, String key) {
        Map<String, String> m = MEM.get(cls);
        return m == null ? null : m.get(key);
    }

    // a method by real name; params given as real type names ("" = any arity match on name)
    static Method M(String cls, String name, String... params) throws Exception {
        String key = name + "(" + String.join(",", params) + ")";
        String o = memberName(cls, key);
        Class<?> c = C(cls);
        Class<?>[] ps = new Class<?>[params.length];
        for (int i = 0; i < params.length; i++) ps[i] = C(params[i]);
        Method m = null;
        for (Class<?> k = c; k != null && m == null; k = k.getSuperclass()) {
            try { m = k.getDeclaredMethod(o != null ? o : name, ps); } catch (NoSuchMethodException e) { }
        }
        if (m == null) {
            for (Class<?> i : c.getInterfaces()) {
                try { m = i.getDeclaredMethod(o != null ? o : name, ps); break; } catch (NoSuchMethodException e) { }
            }
        }
        if (m == null) throw new NoSuchMethodException(cls + "." + key);
        m.setAccessible(true);
        return m;
    }

    static Object F(String cls, String name) throws Exception {
        String o = memberName(cls, name);
        Field f = C(cls).getDeclaredField(o != null ? o : name);
        f.setAccessible(true);
        return f.get(null);
    }

    static String real(Class<?> c) {
        for (Map.Entry<String, String> e : CLS.entrySet()) if (e.getValue().equals(c.getName())) return e.getKey();
        return c.getName();
    }

    static Object provider, dispatcher, source, ops;
    static Map<String, Object> codecs = new HashMap<>();   // datapack folder -> Codec

    static void setup(Path mappings) throws Exception {
        if (mappings != null) loadMappings(mappings);
        M("net.minecraft.SharedConstants", "tryDetectVersion").invoke(null);
        M("net.minecraft.server.Bootstrap", "bootStrap").invoke(null);
        try {
            provider = M("net.minecraft.data.registries.VanillaRegistries", "createLookup").invoke(null);
        } catch (NoSuchMethodException e) {                                     // 26.x
            provider = M("net.minecraft.data.registries.VanillaRegistries", "createWorldLookup").invoke(null);
        }
        Object ctx = M("net.minecraft.commands.Commands", "createValidationContext",
                "net.minecraft.core.HolderLookup$Provider").invoke(null, provider);
        Class<?> sel = C("net.minecraft.commands.Commands$CommandSelection");
        Object dedicated = null;
        for (Object e : sel.getEnumConstants()) if (((Enum<?>) e).ordinal() == 2 || e.toString().equals("DEDICATED")) dedicated = e;
        Object commands = null;
        for (Constructor<?> k : C("net.minecraft.commands.Commands").getDeclaredConstructors()) {
            if (k.getParameterCount() == 2) { k.setAccessible(true); commands = k.newInstance(dedicated, ctx); }
        }
        dispatcher = M("net.minecraft.commands.Commands", "getDispatcher").invoke(commands);
        source = makeSource();
        ops = M("net.minecraft.core.HolderLookup$Provider", "createSerializationContext",
                "com.mojang.serialization.DynamicOps").invoke(provider, JsonOps.INSTANCE);
        // reloadable folders
        tryCodec("recipe", "net.minecraft.world.item.crafting.Recipe", "CODEC");
        tryCodec("advancement", "net.minecraft.advancements.Advancement", "CODEC");
        tryCodec("loot_table", "net.minecraft.world.level.storage.loot.LootTable", "DIRECT_CODEC");
        tryCodec("predicate", "net.minecraft.world.level.storage.loot.predicates.LootItemCondition", "DIRECT_CODEC");
        tryCodec("item_modifier", "net.minecraft.world.level.storage.loot.functions.LootItemFunctions", "ROOT_CODEC");
        tryCodec("tags", "net.minecraft.tags.TagFile", "CODEC");
        // data-driven registries (enchantment, painting_variant, jukebox_song, damage_type, worldgen/..., dialog ...)
        for (String list : new String[]{"WORLDGEN_REGISTRIES", "DIMENSION_REGISTRIES", "SYNCHRONIZED_REGISTRIES"}) {
            Object l;
            try { l = F("net.minecraft.resources.RegistryDataLoader", list); } catch (Exception e) { continue; }
            for (Object rd : (List<?>) l) {
                Object key = null, codec = null;
                for (Method m : rd.getClass().getDeclaredMethods()) {
                    if (m.getParameterCount() != 0) continue;
                    m.setAccessible(true);
                    Object v = m.invoke(rd);
                    if (v instanceof Codec<?> && codec == null) codec = v;
                    else if (v != null && real(v.getClass()).equals("net.minecraft.resources.ResourceKey")) key = v;
                }
                if (key == null || codec == null) continue;
                String ks = key.toString();                        // ResourceKey[minecraft:root / minecraft:x]
                String path = ks.substring(ks.lastIndexOf(" / ") + 3, ks.length() - 1).replaceFirst("^minecraft:", "");
                codecs.putIfAbsent(path, codec);
            }
        }
    }

    static void tryCodec(String folder, String cls, String field) {
        try { codecs.put(folder, F(cls, field)); } catch (Exception e) { System.err.println("no codec " + folder + ": " + e); }
    }

    static Object makeSource() throws Exception {
        Class<?> css = C("net.minecraft.commands.CommandSourceStack");
        Constructor<?> best = null;
        for (Constructor<?> k : css.getDeclaredConstructors()) {
            Class<?>[] ps = k.getParameterTypes();
            boolean hasSource = ps.length > 0 && real(ps[0]).equals("net.minecraft.commands.CommandSource");
            if (hasSource && (best == null || ps.length > best.getParameterCount())) best = k;
        }
        Class<?>[] ps = best.getParameterTypes();
        Object[] args = new Object[ps.length];
        StringBuilder sig = new StringBuilder();
        for (int i = 0; i < ps.length; i++) {
            String r = real(ps[i]);
            sig.append(r).append(' ');
            if (ps[i] == int.class) args[i] = 4;
            else if (ps[i] == boolean.class) args[i] = false;
            else if (ps[i] == String.class) args[i] = "check";
            else if (r.equals("net.minecraft.commands.CommandSource")) args[i] = F(r, "NULL");
            else if (r.equals("net.minecraft.world.phys.Vec3") || r.equals("net.minecraft.world.phys.Vec2")) args[i] = F(r, "ZERO");
            else if (r.equals("net.minecraft.network.chat.Component"))
                args[i] = M(r, "literal", "java.lang.String").invoke(null, "check");
            else if (r.startsWith("net.minecraft.server.permissions")) args[i] = permissionsAll(r);
            else args[i] = null;
        }
        System.err.println("source ctor: " + sig);
        best.setAccessible(true);
        return best.newInstance(args);
    }

    static Object permissionsAll(String r) throws Exception {
        // 1.21.11+: a permission set; take the static one with every permission (owners level)
        for (String name : new String[]{"ALL_PERMISSIONS", "ALL", "OWNERS", "LEVEL_OWNERS", "ENTITY_OWNERS"}) {
            try { return F(r, name); } catch (Exception e) { }
        }
        Class<?> c = C(r);
        if (c.isEnum()) { Object[] e = c.getEnumConstants(); return e[e.length - 1]; }
        for (Field f : c.getDeclaredFields())
            if (Modifier.isStatic(f.getModifiers()) && c.isAssignableFrom(f.getType())) { f.setAccessible(true); Object v = f.get(null); if (v != null) return v; }
        for (String name : new String[]{"net.minecraft.server.permissions.LevelBasedPermissionSet", "net.minecraft.server.permissions.PermissionSet"}) {
            try { return F(name, "OWNER"); } catch (Exception e) { }
            try { return F(name, "ALL_PERMISSIONS"); } catch (Exception e) { }
        }
        return null;
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    static String parseCommand(String line) {
        try {
            CommandDispatcher d = (CommandDispatcher) dispatcher;
            ParseResults r = d.parse(new com.mojang.brigadier.StringReader(line), source);
            if (r.getReader().canRead()) {
                if (r.getExceptions().size() == 1) return ((Exception) r.getExceptions().values().iterator().next()).getMessage();
                if (r.getContext().getRange().isEmpty()) return "Unknown command: " + line;
                return "Incorrect argument for command at position " + r.getReader().getCursor() + ": ..."
                        + line.substring(Math.max(0, r.getReader().getCursor() - 10), r.getReader().getCursor()) + "<--[HERE]";
            }
            CommandContext ctx = r.getContext().build(line);
            if (ContextChain.tryFlatten(ctx).isEmpty()) return "Unknown or incomplete command: " + line;
            return null;
        } catch (Throwable t) {
            return "checker exception: " + t;
        }
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    static Object[] checkFile(String path, String content) {
        String p = path.replace('\\', '/');
        if (p.startsWith("pack.mcmeta")) return checkPackMeta(content, p.endsWith("#resource"));
        int k = p.indexOf("data/");
        if (k < 0) return new Object[]{null, "not a data pack file"};
        String[] parts = p.substring(k + 5).split("/");
        if (parts.length < 3) return new Object[]{null, "too short"};
        String rest = String.join("/", Arrays.copyOfRange(parts, 1, parts.length));
        if (rest.endsWith(".mcfunction")) {
            String folder = parts[1];
            if (!folder.equals("function")) return new Object[]{false, "functions go in data/<ns>/function/ (found " + folder + "/), the game ignores this file"};
            int n = 0;
            for (String raw : content.replace("\\\n", " ").split("\n")) {
                n++;
                String s = raw.strip();
                if (s.isEmpty() || s.startsWith("#") || s.startsWith("$")) continue;
                String err = parseCommand(s);
                if (err != null) return new Object[]{false, "line " + n + ": " + err};
            }
            return new Object[]{true, null};
        }
        if (!rest.endsWith(".json")) return new Object[]{null, "not checked"};
        String folder = null;
        String noext = rest.substring(0, rest.length() - 5);
        if (noext.startsWith("tags/")) folder = "tags";
        else {
            for (String f : codecs.keySet()) if (noext.startsWith(f + "/") && (folder == null || f.length() > folder.length())) folder = f;
        }
        if (folder == null) return new Object[]{false, "the game does not read data/<ns>/" + noext.split("/")[0] + "/ in this version"};
        JsonElement json;
        try { json = JsonParser.parseString(content); } catch (Exception e) { return new Object[]{false, "not valid JSON: " + e.getMessage()}; }
        Codec codec = (Codec) codecs.get(folder);
        DataResult res = codec.parse((DynamicOps) ops, json);
        Optional err = res.error();
        if (err.isPresent()) {
            Object pe = err.get();
            try { Method m = pe.getClass().getMethod("message"); m.setAccessible(true); return new Object[]{false, folder + ": " + m.invoke(pe)}; }
            catch (Exception e) { return new Object[]{false, folder + ": " + pe}; }
        }
        return new Object[]{true, null};
    }

    // pack.mcmeta "pack" section through the game's own metadata codec (1.21.9+: per pack type, with min/max_format)
    @SuppressWarnings({"unchecked", "rawtypes"})
    static Object[] checkPackMeta(String content, boolean resource) {
        JsonElement json;
        try { json = JsonParser.parseString(content); } catch (Exception e) { return new Object[]{false, "not valid JSON: " + e.getMessage()}; }
        if (!json.isJsonObject() || !json.getAsJsonObject().has("pack")) return new Object[]{false, "no \"pack\" section"};
        JsonElement pack = json.getAsJsonObject().get("pack");
        Codec codec = null;
        String cls = "net.minecraft.server.packs.metadata.pack.PackMetadataSection";
        try {
            Class<?> pt = C("net.minecraft.server.packs.PackType");
            Object type = null;
            for (Object e : pt.getEnumConstants()) if (((Enum<?>) e).ordinal() == (resource ? 0 : 1)) type = e;
            codec = (Codec) M(cls, "codecForPackType", "net.minecraft.server.packs.PackType").invoke(null, type);
        } catch (Exception e) {
            try { codec = (Codec) F(cls, "CODEC"); } catch (Exception e2) { return new Object[]{null, "no pack codec: " + e2}; }
        }
        DataResult res = codec.parse((DynamicOps) ops, pack);
        Optional err = res.error();
        if (err.isPresent()) {
            Object pe = err.get();
            try { Method m = pe.getClass().getMethod("message"); m.setAccessible(true); return new Object[]{false, "pack.mcmeta: " + m.invoke(pe)}; }
            catch (Exception e) { return new Object[]{false, "pack.mcmeta: " + pe}; }
        }
        return new Object[]{true, String.valueOf(res.result().orElse(null))};
    }

    public static void main(String[] a) throws Exception {
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);                 // game logging goes to stderr; results to the real stdout
        setup(a.length > 0 && !a[0].isEmpty() ? Paths.get(a[0]) : null);
        System.err.println("codecs: " + new TreeSet<>(codecs.keySet()));
        out.println("{\"ready\": true}");
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
        Gson gson = new Gson();
        String line;
        while ((line = in.readLine()) != null) {
            if (line.isBlank()) continue;
            JsonObject job = JsonParser.parseString(line).getAsJsonObject();
            JsonObject res = new JsonObject();
            res.add("id", job.get("id"));
            JsonArray cr = new JsonArray();
            if (job.has("commands")) {
                int i = 0;
                for (JsonElement c : job.getAsJsonArray("commands")) {
                    String err = parseCommand(c.getAsString());
                    JsonObject o = new JsonObject();
                    o.addProperty("i", i++);
                    o.addProperty("ok", err == null);
                    if (err != null) o.addProperty("error", err);
                    cr.add(o);
                }
            }
            res.add("commands", cr);
            JsonArray fr = new JsonArray();
            if (job.has("files")) {
                for (Map.Entry<String, JsonElement> e : job.getAsJsonObject("files").entrySet()) {
                    Object[] r = checkFile(e.getKey(), e.getValue().getAsString());
                    JsonObject o = new JsonObject();
                    o.addProperty("path", e.getKey());
                    if (r[0] == null) o.add("ok", JsonNull.INSTANCE); else o.addProperty("ok", (Boolean) r[0]);
                    if (r[1] != null) o.addProperty("error", (String) r[1]);
                    fr.add(o);
                }
            }
            res.add("files", fr);
            out.println(gson.toJson(res));
        }
    }
}
