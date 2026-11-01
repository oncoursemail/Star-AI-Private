// Warm TypeScript/JavaScript checker (runs as the compile-only user inside the star-polyglot container).
// One JSON request per stdin line: {"id", "code", "lang": "ts"|"js", "tsx": bool}
// One JSON reply per stdout line: {"id", "diags": [{"code", "line", "message", "syntactic": bool}], "ms"}
// The lib .d.ts files are parsed once and reused, so a check costs ~50-300 ms instead of a cold tsc (~1.2 s).
"use strict";
const ts = require(process.env.PG_TS || "/opt/pg/node/node_modules/typescript");
const readline = require("readline");

const OPTIONS = {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
  lib: ["lib.es2023.d.ts", "lib.dom.d.ts", "lib.dom.iterable.d.ts"], strict: true, noEmit: true, skipLibCheck: true,
  jsx: ts.JsxEmit.Preserve, esModuleInterop: true, allowJs: true, checkJs: false, types: ["node"],
  typeRoots: [process.env.PG_TYPES || "/opt/pg/node/node_modules/@types"], noUnusedLocals: false,
  allowImportingTsExtensions: true, resolveJsonModule: true, isolatedModules: false,
};
const cache = new Map();   // fileName -> SourceFile (libs and @types only)
const base = ts.createCompilerHost(OPTIONS, true);

function host(name, text) {
  return Object.assign({}, base, {
    getSourceFile(fileName, languageVersion) {
      if (fileName === name) return ts.createSourceFile(fileName, text, languageVersion, true);
      let sf = cache.get(fileName);
      if (!sf) {
        sf = base.getSourceFile(fileName, languageVersion);
        if (sf) cache.set(fileName, sf);
      }
      return sf;
    },
    fileExists: (f) => f === name || base.fileExists(f),
    readFile: (f) => (f === name ? text : base.readFile(f)),
    writeFile: () => {},
  });
}

function check(req) {
  const ext = req.lang === "js" ? (req.tsx ? ".jsx" : ".js") : (req.tsx ? ".tsx" : ".ts");
  const name = "/virtual/main" + ext;
  const program = ts.createProgram([name], OPTIONS, host(name, req.code));
  const sf = program.getSourceFile(name);
  const out = [];
  const add = (d, syntactic) => {
    if (d.file && d.file.fileName !== name) return;
    const line = d.file && d.start !== undefined ? d.file.getLineAndCharacterOfPosition(d.start).line + 1 : null;
    out.push({ code: d.code, line, syntactic, message: ts.flattenDiagnosticMessageText(d.messageText, "\n").slice(0, 400) });
  };
  program.getSyntacticDiagnostics(sf).forEach((d) => add(d, true));
  if (req.lang !== "js" && out.length === 0) program.getSemanticDiagnostics(sf).forEach((d) => add(d, false));
  return out;
}

const rl = readline.createInterface({ input: process.stdin });
rl.on("line", (line) => {
  let req;
  try { req = JSON.parse(line); } catch (e) { return; }
  const t0 = Date.now();
  let reply;
  try { reply = { id: req.id, diags: check(req) }; } catch (e) { reply = { id: req.id, error: String(e).slice(0, 300) }; }
  reply.ms = Date.now() - t0;
  process.stdout.write(JSON.stringify(reply) + "\n");
});
process.stdout.write(JSON.stringify({ ready: true, ts: ts.version }) + "\n");
