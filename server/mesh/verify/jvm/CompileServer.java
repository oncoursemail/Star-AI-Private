// Warm in-process javac for Minecraft plugin/mod answers (lane mc-plugins-20261029).
//
// One JVM keeps javac, the per-target file managers (jar indexes) and a reflection class loader warm, so a check of a
// typical answer takes a few hundred ms instead of a cold Gradle build. Targets are the folders under the classpath
// root (default /opt/mcp/cp): paper, spigot, velocity, fabric (yarn names), fabric-mojmap, neoforge.
//
//   POST /compile  {"target": "paper", "files": {"src/main/java/a/B.java": "..."}, "outdir": "/tmp/x" (optional)}
//     -> {"ok", "ms", "diagnostics": [{kind, code, file, line, col, message, symbol, location, candidates, note}],
//         "classes": [...], "resources": [...]}
//   GET  /members?target=paper&class=org.bukkit.entity.Player   -> public methods/fields (reflection, no init)
//   GET  /health
// Auth: "Authorization: Bearer <token>" where the token is the content of --token-file (not in git).
// Run: java -Xmx2g -cp <gson.jar>:. CompileServer --port 8105 --token-file /opt/mcp/token --cp-root /opt/mcp/cp
import com.google.gson.*;
import com.sun.net.httpserver.*;

import javax.tools.*;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.Executors;
import java.util.jar.*;
import java.util.regex.*;

public class CompileServer {
    static final Gson GSON = new GsonBuilder().disableHtmlEscaping().create();
    static final JavaCompiler JAVAC = ToolProvider.getSystemJavaCompiler();
    static final Map<String, Target> TARGETS = new TreeMap<>();
    static Map<String, String> DEPRECATIONS = new HashMap<>();   // "owner#member(" -> javadoc note
    static String token = "";

    static final class Target {
        final String name;
        final List<File> cp;
        final StandardJavaFileManager fm;
        final URLClassLoader loader;
        final Map<String, List<String>> bySimple = new HashMap<>();   // simple class name -> FQNs
        final Set<String> packages = new TreeSet<>();
        final boolean proc;

        Target(String name, List<File> cp) throws IOException {
            this.name = name;
            this.cp = cp;
            this.fm = JAVAC.getStandardFileManager(null, Locale.ROOT, StandardCharsets.UTF_8);
            this.fm.setLocation(StandardLocation.CLASS_PATH, cp);
            this.proc = name.equals("velocity");                     // @Plugin -> velocity-plugin.json
            if (proc) this.fm.setLocation(StandardLocation.ANNOTATION_PROCESSOR_PATH, cp);
            URL[] urls = new URL[cp.size()];
            for (int i = 0; i < cp.size(); i++) urls[i] = cp.get(i).toURI().toURL();
            this.loader = new URLClassLoader(urls, ClassLoader.getPlatformClassLoader());
            for (File f : cp) {
                try (JarFile jf = new JarFile(f)) {
                    for (Enumeration<JarEntry> e = jf.entries(); e.hasMoreElements(); ) {
                        String n = e.nextElement().getName();
                        if (!n.endsWith(".class") || n.contains("$") || n.startsWith("META-INF")) continue;
                        String fqn = n.substring(0, n.length() - 6).replace('/', '.');
                        int dot = fqn.lastIndexOf('.');
                        if (dot < 0) continue;
                        packages.add(fqn.substring(0, dot));
                        bySimple.computeIfAbsent(fqn.substring(dot + 1), k -> new ArrayList<>()).add(fqn);
                    }
                }
            }
            // the platform's own API first (Subscribe -> com.velocitypowered..., not Guava; Plugin -> not Maven)
            for (List<String> l : bySimple.values())
                l.sort(Comparator.comparingInt((String f) -> rank(name, f)).thenComparingInt(String::length));
        }
    }

    // ---- compile ------------------------------------------------------------------------------------------------
    static final class Src extends SimpleJavaFileObject {
        final String code;
        Src(String path, String code) { super(URI.create("string:///" + path.replace('\\', '/')), Kind.SOURCE); this.code = code; }
        @Override public CharSequence getCharContent(boolean ignore) { return code; }
    }

    static final class Out extends SimpleJavaFileObject {
        final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        final String rel;
        Out(String rel, Kind kind) { super(URI.create("mem:///" + rel), kind); this.rel = rel; }
        @Override public OutputStream openOutputStream() { return bytes; }
        @Override public Writer openWriter() { return new OutputStreamWriter(bytes, StandardCharsets.UTF_8); }
    }

    static JsonObject compile(Target t, Map<String, String> files, String outdir) throws IOException {
        long t0 = System.nanoTime();
        List<Src> srcs = new ArrayList<>();
        for (Map.Entry<String, String> e : files.entrySet())
            if (e.getKey().endsWith(".java")) srcs.add(new Src(e.getKey(), e.getValue()));
        Map<String, Out> outs = new LinkedHashMap<>();
        JavaFileManager fm = new ForwardingJavaFileManager<StandardJavaFileManager>(t.fm) {
            @Override public JavaFileObject getJavaFileForOutput(Location loc, String cls, JavaFileObject.Kind kind, FileObject sib) {
                Out o = new Out(cls.replace('.', '/') + kind.extension, kind);
                outs.put(o.rel, o);
                return o;
            }
            @Override public FileObject getFileForOutput(Location loc, String pkg, String rel, FileObject sib) {
                String r = (pkg == null || pkg.isEmpty() ? "" : pkg.replace('.', '/') + "/") + rel;
                Out o = new Out(r, JavaFileObject.Kind.OTHER);
                outs.put(o.rel, o);
                return o;
            }
        };
        List<String> opts = new ArrayList<>(List.of("--release", "21", "-encoding", "UTF-8", "-Xlint:deprecation,removal",
                "-Xmaxerrs", "60", "-Xmaxwarns", "60", "-implicit:none", "-g:none"));
        if (!t.proc) opts.add("-proc:none");
        DiagnosticCollector<JavaFileObject> dc = new DiagnosticCollector<>();
        boolean ok;
        synchronized (t) {
            ok = srcs.isEmpty() || JAVAC.getTask(null, fm, dc, opts, null, srcs).call();
        }
        JsonArray diags = new JsonArray();
        for (Diagnostic<? extends JavaFileObject> d : dc.getDiagnostics()) diags.add(describe(t, d));
        JsonArray classes = new JsonArray(), resources = new JsonArray();
        for (Out o : outs.values()) {
            if (o.getKind() == JavaFileObject.Kind.CLASS) classes.add(o.rel.substring(0, o.rel.length() - 6).replace('/', '.'));
            else resources.add(o.rel);
            if (outdir != null && ok) {
                Path p = Paths.get(outdir).resolve(o.rel).normalize();
                if (!p.startsWith(Paths.get(outdir).normalize())) continue;
                Files.createDirectories(p.getParent());
                Files.write(p, o.bytes.toByteArray());
            }
        }
        JsonObject r = new JsonObject();
        r.addProperty("ok", ok);
        r.addProperty("target", t.name);
        r.addProperty("ms", (System.nanoTime() - t0) / 1_000_000);
        r.add("diagnostics", diags);
        r.add("classes", classes);
        r.add("resources", resources);
        return r;
    }

    static final Pattern SYMBOL = Pattern.compile("symbol:\\s+(class|method|variable|static|interface|enum)\\s+([\\w$]+)(\\([^)]*\\))?");
    static final Pattern LOCATION = Pattern.compile("location:\\s+(?:(class|interface|enum|package|variable|record|@interface)\\s+)?([\\w.$<>]+)(?:\\s+of type\\s+([\\w.$<>]+))?");
    static final Pattern NO_PKG = Pattern.compile("package ([\\w.]+) does not exist");
    static final Pattern DEPREC = Pattern.compile("([\\w$<>]+)\\(([^)]*)\\) in ([\\w.$]+) has been deprecated");
    static final Pattern CONVERT = Pattern.compile("cannot be converted to ([\\w.$]+)");
    static final Pattern DEPREC_CLS = Pattern.compile("^([\\w.$]+) in ([\\w.$]+) has been deprecated");

    static JsonObject describe(Target t, Diagnostic<? extends JavaFileObject> d) {
        JsonObject o = new JsonObject();
        String msg = d.getMessage(Locale.ROOT);
        o.addProperty("kind", d.getKind().name());
        o.addProperty("code", d.getCode());
        o.addProperty("file", d.getSource() == null ? "" : d.getSource().toUri().getPath().replaceFirst("^/", ""));
        o.addProperty("line", d.getLineNumber());
        o.addProperty("col", d.getColumnNumber());
        o.addProperty("message", msg);
        try {
            Matcher s = SYMBOL.matcher(msg), l = LOCATION.matcher(msg), np = NO_PKG.matcher(msg);
            if (s.find()) {
                String kind = s.group(1), name = s.group(2);
                o.addProperty("symbol", name);
                String owner = null;
                String inPkg = null;
                if (l.find()) {
                    owner = l.group(3) != null ? l.group(3) : ("package".equals(l.group(1)) ? null : l.group(2));
                    if ("package".equals(l.group(1))) inPkg = l.group(2);
                }
                if (owner != null) owner = owner.replaceAll("<.*>", "");
                if (owner != null) o.addProperty("location", owner);
                JsonArray cands = new JsonArray();
                if (kind.equals("class") || (owner == null && Character.isUpperCase(name.charAt(0)))) {
                    List<String> fq = t.bySimple.get(name);
                    if (fq != null) {
                        for (String f : fq.subList(0, Math.min(6, fq.size()))) cands.add(f);
                        o.addProperty("note", "class exists: import " + fq.get(0));
                    } else {                        // same package first (org.bukkit.event.block.SignEvent -> SignChangeEvent)
                        if (inPkg != null) {
                            List<String> here = new ArrayList<>();
                            for (Map.Entry<String, List<String>> e : t.bySimple.entrySet())
                                for (String f : e.getValue()) if (f.equals(inPkg + "." + e.getKey())) here.add(e.getKey());
                            for (String c : closest(name, here, 4)) cands.add(inPkg + "." + c);
                        }
                        for (String c : closest(name, t.bySimple.keySet(), 6))
                            if (cands.size() < 6 && !cands.contains(new JsonPrimitive(t.bySimple.get(c).get(0)))) cands.add(t.bySimple.get(c).get(0));
                    }
                } else if (owner != null) {
                    Class<?> c = load(t, owner);
                    if (c != null) {
                        o.addProperty("api", true);        // the owner is a real class of the target's API jars
                        Set<String> names = members(c, kind.equals("method"));
                        for (String n : closest(name, names, 8)) cands.add(n);
                        if (kind.equals("method")) {        // also say when the name is a field or vice versa
                            Set<String> other = members(c, false);
                            if (other.contains(name)) o.addProperty("note", name + " is a field of " + owner + ", not a method");
                            else {                          // the method exists, but on another type (a subtype?)
                                List<String> on = declaredOn(t, name, c);
                                if (!on.isEmpty()) o.addProperty("note", name + "() is not on " + owner + "; it exists on "
                                        + String.join(", ", on) + (subtype(t, on.get(0), c) ? " (a subtype: check/cast to it, or use the event method that returns it)" : ""));
                            }
                        }
                    }
                }
                if (cands.size() > 0) o.add("candidates", cands);
            } else if (d.getCode() != null && d.getCode().equals("compiler.err.prob.found.req") && CONVERT.matcher(msg).find()) {
                Matcher cm = CONVERT.matcher(msg);
                cm.find();
                Class<?> want = load(t, cm.group(1));
                if (want != null) {
                    List<String> ways = makers(want);
                    if (!ways.isEmpty()) o.addProperty("note", "make a " + want.getSimpleName() + " with: " + String.join(", ", ways));
                }
            } else if (np.find()) {
                String pkg = np.group(1);
                JsonArray cands = new JsonArray();
                String last = pkg.substring(pkg.lastIndexOf('.') + 1);
                List<String> pk = new ArrayList<>();
                for (String p : t.packages) if (p.endsWith("." + last)) pk.add(p);
                if (pk.isEmpty()) pk = closest(pkg, t.packages, 5);
                for (String p : pk.subList(0, Math.min(5, pk.size()))) cands.add(p);
                if (cands.size() > 0) o.add("candidates", cands);
            } else if (d.getKind() == Diagnostic.Kind.WARNING || d.getKind() == Diagnostic.Kind.MANDATORY_WARNING) {
                Matcher dm = DEPREC.matcher(msg), dc = DEPREC_CLS.matcher(msg);
                String key = null;
                if (dm.find()) key = dm.group(3) + "#" + dm.group(1) + "(";
                else if (dc.find()) key = dc.group(1);
                if (key != null) {
                    String note = DEPRECATIONS.get(key);
                    if (note == null && key.contains("#")) note = DEPRECATIONS.get(key.substring(0, key.indexOf('#')));
                    if (note != null) o.addProperty("note", note);
                }
            }
        } catch (Throwable ignored) { }
        return o;
    }

    static Class<?> load(Target t, String name) {
        String n = name;
        for (int i = 0; i < 4; i++) {
            try { return Class.forName(n, false, t.loader); } catch (Throwable e) { /* try as nested class */ }
            int dot = n.lastIndexOf('.');
            if (dot < 0) break;
            n = n.substring(0, dot) + "$" + n.substring(dot + 1);
        }
        if (!name.contains(".")) {
            List<String> fq = t.bySimple.get(name);
            if (fq != null && fq.size() == 1) return load(t, fq.get(0));
            if (fq == null) for (String p : List.of("java.lang.", "java.util.")) {
                try { return Class.forName(p + name, false, t.loader); } catch (Throwable e) { /* next */ }
            }
        }
        return null;
    }

    // method name -> API classes that declare it publicly (built lazily per target, API packages only)
    static final Map<String, Map<String, List<String>>> BY_METHOD = new HashMap<>();
    static final Map<String, String> ROOTS = Map.of("paper", "org.bukkit io.papermc com.destroystokyo net.kyori",
            "spigot", "org.bukkit org.spigotmc net.md_5", "velocity", "com.velocitypowered",
            "fabric", "net.minecraft net.fabricmc", "fabric-mojmap", "net.minecraft net.fabricmc",
            "neoforge", "net.minecraft net.neoforged");

    static synchronized Map<String, List<String>> methodIndex(Target t) {
        Map<String, List<String>> idx = BY_METHOD.get(t.name);
        if (idx != null) return idx;
        idx = new HashMap<>();
        String[] roots = ROOTS.getOrDefault(t.name, "").split(" ");
        for (List<String> fqs : t.bySimple.values()) for (String fq : fqs) {
            boolean api = false;
            for (String r : roots) if (!r.isEmpty() && fq.startsWith(r + ".")) api = true;
            if (!api) continue;
            try {
                Class<?> c = Class.forName(fq, false, t.loader);
                for (Method m : c.getDeclaredMethods())
                    if (Modifier.isPublic(m.getModifiers())) {
                        List<String> l = idx.computeIfAbsent(m.getName(), k -> new ArrayList<>());
                        if (!l.contains(fq)) l.add(fq);
                    }
            } catch (Throwable ignored) { }
        }
        BY_METHOD.put(t.name, idx);
        return idx;
    }

    static int rank(String target, String fq) {
        int r = 3;
        for (String root : ROOTS.getOrDefault(target, "").split(" "))
            if (!root.isEmpty() && fq.startsWith(root + ".")) r = 0;
        if (r == 3 && (fq.startsWith("java.") || fq.startsWith("javax."))) r = 1;
        if (fq.contains(".impl.") || fq.contains(".internal.")) r += 2;
        return r;
    }

    static boolean subtype(Target t, String fq, Class<?> of) {
        try { return of.isAssignableFrom(Class.forName(fq, false, t.loader)); } catch (Throwable e) { return false; }
    }

    static List<String> declaredOn(Target t, String method, Class<?> from) {
        List<String> on = new ArrayList<>(methodIndex(t).getOrDefault(method, List.of()));
        on.sort(Comparator.comparing((String fq) -> !subtype(t, fq, from)).thenComparing(String::length));
        return on.subList(0, Math.min(4, on.size()));
    }

    static List<String> makers(Class<?> c) {             // public constructors + static factories returning c
        List<String> out = new ArrayList<>();
        try {
            for (Constructor<?> k : c.getConstructors()) {
                if (k.isAnnotationPresent(Deprecated.class)) continue;
                StringBuilder sb = new StringBuilder("new " + c.getSimpleName() + "(");
                Class<?>[] ps = k.getParameterTypes();
                for (int i = 0; i < ps.length; i++) sb.append(i > 0 ? ", " : "").append(ps[i].getSimpleName());
                out.add(sb.append(')').toString());
            }
            for (Method m : c.getMethods())
                if (Modifier.isStatic(m.getModifiers()) && m.getReturnType() == c && !m.isAnnotationPresent(Deprecated.class)) {
                    StringBuilder sb = new StringBuilder(c.getSimpleName() + "." + m.getName() + "(");
                    Class<?>[] ps = m.getParameterTypes();
                    for (int i = 0; i < ps.length; i++) sb.append(i > 0 ? ", " : "").append(ps[i].getSimpleName());
                    String sig = sb.append(')').toString();
                    if (!out.contains(sig)) out.add(sig);
                }
        } catch (Throwable ignored) { }
        return out.subList(0, Math.min(6, out.size()));
    }

    static Set<String> members(Class<?> c, boolean methods) {
        Set<String> out = new TreeSet<>();
        try {
            if (methods) { for (Method m : c.getMethods()) out.add(m.getName()); }
            else { for (Field f : c.getFields()) out.add(f.getName()); }
        } catch (Throwable e) {            // a missing optional dependency: fall back to declared members up the chain
            for (Class<?> k = c; k != null; k = k.getSuperclass()) {
                try {
                    if (methods) { for (Method m : k.getDeclaredMethods()) if (Modifier.isPublic(m.getModifiers())) out.add(m.getName()); }
                    else { for (Field f : k.getDeclaredFields()) if (Modifier.isPublic(f.getModifiers())) out.add(f.getName()); }
                } catch (Throwable ignored) { }
            }
        }
        return out;
    }

    static List<String> closest(String name, Collection<String> pool, int n) {
        String low = name.toLowerCase(Locale.ROOT);
        List<Map.Entry<String, Double>> scored = new ArrayList<>();
        for (String p : pool) {
            String pl = p.toLowerCase(Locale.ROOT);
            double s = lev(low, pl) / (double) Math.max(low.length(), pl.length());
            if ((pl.contains(low) || low.contains(pl)) && 3 * Math.min(pl.length(), low.length()) >= 2 * Math.max(pl.length(), low.length()))
                s -= 0.25;                                   // getKiller is not "get"
            if (s <= 0.5 || (s <= 0.6 && pl.startsWith(low.substring(0, Math.min(4, low.length()))))) scored.add(Map.entry(p, s));
        }
        scored.sort(Map.Entry.comparingByValue());
        List<String> out = new ArrayList<>();
        for (int i = 0; i < Math.min(n, scored.size()); i++) out.add(scored.get(i).getKey());
        return out;
    }

    static int lev(String a, String b) {
        if (Math.abs(a.length() - b.length()) > 12) return 99;
        int[] prev = new int[b.length() + 1], cur = new int[b.length() + 1];
        for (int j = 0; j <= b.length(); j++) prev[j] = j;
        for (int i = 1; i <= a.length(); i++) {
            cur[0] = i;
            for (int j = 1; j <= b.length(); j++)
                cur[j] = Math.min(Math.min(cur[j - 1] + 1, prev[j] + 1), prev[j - 1] + (a.charAt(i - 1) == b.charAt(j - 1) ? 0 : 1));
            int[] tmp = prev; prev = cur; cur = tmp;
        }
        return prev[b.length()];
    }

    static JsonObject membersOf(Target t, String cls) {
        JsonObject r = new JsonObject();
        Class<?> c = load(t, cls);
        if (c == null) { r.addProperty("found", false); return r; }
        r.addProperty("found", true);
        r.addProperty("class", c.getName());
        JsonArray ms = new JsonArray();
        try {
            for (Method m : c.getMethods()) {
                if (m.getDeclaringClass() == Object.class) continue;
                StringBuilder sb = new StringBuilder();
                if (Modifier.isStatic(m.getModifiers())) sb.append("static ");
                sb.append(m.getReturnType().getSimpleName()).append(' ').append(m.getName()).append('(');
                Class<?>[] ps = m.getParameterTypes();
                for (int i = 0; i < ps.length; i++) sb.append(i > 0 ? ", " : "").append(ps[i].getSimpleName());
                sb.append(')');
                if (m.isAnnotationPresent(Deprecated.class)) sb.append(" @Deprecated");
                ms.add(sb.toString());
            }
        } catch (Throwable e) { r.addProperty("error", e.toString()); }
        r.add("methods", ms);
        return r;
    }

    // ---- http ---------------------------------------------------------------------------------------------------
    static void reply(HttpExchange ex, int code, Object body) throws IOException {
        byte[] b = GSON.toJson(body).getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(code, b.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(b); }
    }

    static boolean authed(HttpExchange ex) {
        String h = ex.getRequestHeaders().getFirst("Authorization");
        return h != null && !token.isEmpty() && MessageDigestEq(h, "Bearer " + token);
    }

    static boolean MessageDigestEq(String a, String b) {
        return java.security.MessageDigest.isEqual(a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8));
    }

    static Map<String, String> query(URI u) {
        Map<String, String> q = new HashMap<>();
        if (u.getRawQuery() == null) return q;
        for (String kv : u.getRawQuery().split("&")) {
            int i = kv.indexOf('=');
            if (i > 0) q.put(URLDecoder.decode(kv.substring(0, i), StandardCharsets.UTF_8), URLDecoder.decode(kv.substring(i + 1), StandardCharsets.UTF_8));
        }
        return q;
    }

    public static void main(String[] args) throws Exception {
        int port = 8105;
        String cpRoot = "/opt/mcp/cp", tokenFile = "/opt/mcp/token", deprec = "/opt/mcp/index/deprecations.json";
        for (int i = 0; i + 1 < args.length; i += 2) {
            switch (args[i]) {
                case "--port" -> port = Integer.parseInt(args[i + 1]);
                case "--cp-root" -> cpRoot = args[i + 1];
                case "--token-file" -> tokenFile = args[i + 1];
                case "--deprecations" -> deprec = args[i + 1];
                default -> throw new IllegalArgumentException(args[i]);
            }
        }
        token = Files.readString(Paths.get(tokenFile)).trim();
        if (Files.exists(Paths.get(deprec)))
            DEPRECATIONS = GSON.fromJson(Files.readString(Paths.get(deprec)), new com.google.gson.reflect.TypeToken<Map<String, String>>() { }.getType());
        File[] dirs = new File(cpRoot).listFiles(File::isDirectory);
        Arrays.sort(dirs);
        for (File dir : dirs) {
            File[] jars = dir.listFiles((d, n) -> n.endsWith(".jar"));
            if (jars == null || jars.length == 0) continue;
            Arrays.sort(jars);
            Target t = new Target(dir.getName(), Arrays.asList(jars));
            TARGETS.put(t.name, t);
            long t0 = System.nanoTime();                 // warm up javac + the jar index for this target
            for (int k = 0; k < 3; k++)
                compile(t, Map.of("w/W.java", "package w; public class W { java.util.List<String> l = new java.util.ArrayList<>(); }"), null);
            System.out.printf("target %s: %d jars, %d classes, warm %d ms%n", t.name, jars.length, t.bySimple.size(), (System.nanoTime() - t0) / 1_000_000);
        }
        Thread idx = new Thread(() -> { for (Target t : TARGETS.values()) methodIndex(t); System.out.println("method index ready"); });
        idx.setDaemon(true);
        idx.start();
        HttpServer srv = HttpServer.create(new InetSocketAddress(port), 32);
        srv.setExecutor(Executors.newFixedThreadPool(4));
        srv.createContext("/health", ex -> {
            JsonObject r = new JsonObject();
            r.addProperty("ok", true);
            r.add("targets", GSON.toJsonTree(TARGETS.keySet()));
            r.addProperty("deprecations", DEPRECATIONS.size());
            reply(ex, 200, r);
        });
        srv.createContext("/compile", ex -> {
            try {
                if (!authed(ex)) { reply(ex, 401, Map.of("error", "unauthorized")); return; }
                JsonObject req = JsonParser.parseString(new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8)).getAsJsonObject();
                Target t = TARGETS.get(req.has("target") ? req.get("target").getAsString() : "paper");
                if (t == null) { reply(ex, 400, Map.of("error", "unknown target", "targets", TARGETS.keySet())); return; }
                Map<String, String> files = new LinkedHashMap<>();
                for (Map.Entry<String, JsonElement> e : req.getAsJsonObject("files").entrySet()) files.put(e.getKey(), e.getValue().getAsString());
                String outdir = req.has("outdir") ? req.get("outdir").getAsString() : null;
                if (outdir != null && !outdir.startsWith("/opt/mcp/work/")) outdir = null;
                reply(ex, 200, compile(t, files, outdir));
            } catch (Throwable e) {
                reply(ex, 500, Map.of("error", e.toString()));
            }
        });
        srv.createContext("/members", ex -> {
            try {
                if (!authed(ex)) { reply(ex, 401, Map.of("error", "unauthorized")); return; }
                Map<String, String> q = query(ex.getRequestURI());
                Target t = TARGETS.get(q.getOrDefault("target", "paper"));
                if (t == null) { reply(ex, 400, Map.of("error", "unknown target")); return; }
                reply(ex, 200, membersOf(t, q.getOrDefault("class", "")));
            } catch (Throwable e) {
                reply(ex, 500, Map.of("error", e.toString()));
            }
        });
        srv.start();
        System.out.println("CompileServer on :" + port + " targets " + TARGETS.keySet());
    }
}
