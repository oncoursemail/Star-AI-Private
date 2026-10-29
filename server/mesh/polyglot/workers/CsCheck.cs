// Warm C# checker (Roslyn from the .NET SDK; runs as the compile-only user inside the star-polyglot container).
// stdin, one JSON per line: {"id", "code", "mode": "dotnet" | "unity" | "syntax" | "script"}
// stdout, one JSON per line: {"id", "diags": [{"code", "line", "message", "severity", "syntactic"}], "ms"}
// The reference assemblies (and the Unity stub assembly, compiled from UnityStubs.cs at start) are loaded once.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

static class CsCheck
{
    static List<MetadataReference> netRefs = new();
    static MetadataReference unityRef;

    static void Main(string[] args)
    {
        string refDir = args[0], stubs = args.Length > 1 ? args[1] : "";
        foreach (var f in Directory.GetFiles(refDir, "*.dll"))
        {
            try { netRefs.Add(MetadataReference.CreateFromFile(f)); } catch { }
        }
        if (stubs != "" && File.Exists(stubs))
        {
            var tree = CSharpSyntaxTree.ParseText(File.ReadAllText(stubs), new CSharpParseOptions(LanguageVersion.Latest));
            var comp = CSharpCompilation.Create("UnityEngine", new[] { tree }, netRefs,
                new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary, nullableContextOptions: NullableContextOptions.Disable));
            using var ms = new MemoryStream();
            var res = comp.Emit(ms);
            if (res.Success) unityRef = MetadataReference.CreateFromImage(ms.ToArray());
            else foreach (var d in res.Diagnostics.Where(d => d.Severity == DiagnosticSeverity.Error).Take(5)) Console.Error.WriteLine("stub: " + d);
        }
        Check("class W { void M() { } }", "dotnet");   // warm the compiler
        Console.WriteLine(JsonSerializer.Serialize(new Dictionary<string, object> { ["ready"] = true, ["unity"] = unityRef != null }));
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var sw = Stopwatch.StartNew();
            var reply = new Dictionary<string, object>();
            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                reply["id"] = root.GetProperty("id").GetString();
                reply["diags"] = Check(root.GetProperty("code").GetString(), root.GetProperty("mode").GetString());
            }
            catch (Exception e) { reply["error"] = e.GetType().Name + ": " + e.Message; }
            reply["ms"] = sw.ElapsedMilliseconds;
            Console.WriteLine(JsonSerializer.Serialize(reply));
        }
    }

    static List<Dictionary<string, object>> Check(string code, string mode)
    {
        var lang = mode == "unity" ? LanguageVersion.CSharp9 : LanguageVersion.Latest;
        var kind = mode == "script" ? SourceCodeKind.Script : SourceCodeKind.Regular;
        var tree = CSharpSyntaxTree.ParseText(code, new CSharpParseOptions(lang, kind: kind));
        var outp = new List<Dictionary<string, object>>();
        var syn = tree.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error).ToList();
        foreach (var d in syn) outp.Add(Diag(d, true));
        if (syn.Count > 0 || mode == "syntax" || mode == "script") return outp;
        var refs = new List<MetadataReference>(netRefs);
        if (mode == "unity" && unityRef != null) refs.Add(unityRef);
        var hasMain = code.Contains("static void Main") || code.Contains("static int Main") || code.Contains("static async Task Main");
        var opts = new CSharpCompilationOptions(mode == "dotnet" ? OutputKind.ConsoleApplication : OutputKind.DynamicallyLinkedLibrary,
            nullableContextOptions: mode == "unity" ? NullableContextOptions.Disable : NullableContextOptions.Enable,
            allowUnsafe: true);
        var comp = CSharpCompilation.Create("main", new[] { tree }, refs, opts);
        foreach (var d in comp.GetDiagnostics())
        {
            if (d.Severity != DiagnosticSeverity.Error && !(d.Severity == DiagnosticSeverity.Warning && d.Id == "CS0618")) continue;
            if (d.Id == "CS5001" && !hasMain) continue;     // a class library answer has no Main
            outp.Add(Diag(d, false));
        }
        return outp;
    }

    static Dictionary<string, object> Diag(Diagnostic d, bool syntactic)
    {
        var span = d.Location.GetLineSpan();
        return new Dictionary<string, object>
        {
            ["code"] = d.Id, ["line"] = span.StartLinePosition.Line + 1, ["syntactic"] = syntactic,
            ["severity"] = d.Severity.ToString().ToLowerInvariant(),
            ["message"] = d.GetMessage(System.Globalization.CultureInfo.InvariantCulture),
        };
    }
}
