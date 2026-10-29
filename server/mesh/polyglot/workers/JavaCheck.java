// Warm Java checker (javax.tools in one JVM; runs as the compile-only user inside the star-polyglot container).
// stdin: a header line "<id> <mode> <bytes>" (mode: full | syntax) followed by <bytes> of UTF-8 source.
// stdout: one JSON line {"id", "diags": [{"code", "line", "message", "syntactic"}], "ms"}. Nothing is written to disk.
import com.sun.source.util.JavacTask;
import java.io.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.*;
import javax.tools.*;

public class JavaCheck {
    static final JavaCompiler JC = ToolProvider.getSystemJavaCompiler();
    static final Pattern PUBLIC_TYPE = Pattern.compile("(?m)^\\s*public\\s+(?:(?:final|abstract|sealed|non-sealed|static)\\s+)*(?:class|interface|enum|record|@interface)\\s+(\\w+)");

    static class Src extends SimpleJavaFileObject {
        final String code;
        Src(String name, String code) { super(URI.create("string:///" + name + ".java"), Kind.SOURCE); this.code = code; }
        @Override public CharSequence getCharContent(boolean ignore) { return code; }
    }

    static String esc(String s) {
        StringBuilder b = new StringBuilder();
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c == '\n') b.append("\\n");
            else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
            else b.append(c);
        }
        return b.toString();
    }

    static String check(String code, String mode) throws IOException {
        Matcher m = PUBLIC_TYPE.matcher(code);
        String name = m.find() ? m.group(1) : "Main";
        DiagnosticCollector<JavaFileObject> dc = new DiagnosticCollector<>();
        StandardJavaFileManager fm = JC.getStandardFileManager(dc, Locale.ROOT, StandardCharsets.UTF_8);
        List<String> opts = Arrays.asList("-proc:none", "-Xlint:none", "-XDshould-stop.ifError=FLOW", "-implicit:none");
        JavacTask task = (JavacTask) JC.getTask(null, fm, dc, opts, null, List.of(new Src(name, code)));
        task.parse();
        boolean syntaxErr = dc.getDiagnostics().stream().anyMatch(d -> d.getKind() == Diagnostic.Kind.ERROR);
        if (!syntaxErr && mode.equals("full")) task.analyze();
        StringBuilder out = new StringBuilder("[");
        for (Diagnostic<? extends JavaFileObject> d : dc.getDiagnostics()) {
            if (d.getKind() != Diagnostic.Kind.ERROR && !(d.getKind() == Diagnostic.Kind.MANDATORY_WARNING && d.getCode().contains("deprecat"))) continue;
            if (out.length() > 1) out.append(',');
            out.append("{\"code\":\"").append(esc(d.getCode())).append("\",\"line\":").append(d.getLineNumber())
               .append(",\"syntactic\":").append(syntaxErr).append(",\"message\":\"")
               .append(esc(d.getMessage(Locale.ROOT).split("\n")[0])).append("\"}");
        }
        return out.append(']').toString();
    }

    public static void main(String[] args) throws Exception {
        check("class W { void m() { } }", "full");      // warm
        System.out.println("{\"ready\":true}");
        System.out.flush();
        DataInputStream in = new DataInputStream(new BufferedInputStream(System.in));
        while (true) {
            StringBuilder hdr = new StringBuilder();
            int c;
            while ((c = in.read()) != -1 && c != '\n') hdr.append((char) c);
            if (c == -1) break;
            String[] h = hdr.toString().trim().split(" ");
            if (h.length != 3) continue;
            byte[] buf = new byte[Integer.parseInt(h[2])];
            in.readFully(buf);
            long t0 = System.currentTimeMillis();
            String reply;
            try {
                reply = "{\"id\":\"" + esc(h[0]) + "\",\"diags\":" + check(new String(buf, StandardCharsets.UTF_8), h[1]);
            } catch (Throwable e) {
                reply = "{\"id\":\"" + esc(h[0]) + "\",\"error\":\"" + esc(String.valueOf(e)) + "\"";
            }
            System.out.println(reply + ",\"ms\":" + (System.currentTimeMillis() - t0) + "}");
            System.out.flush();
        }
    }
}
