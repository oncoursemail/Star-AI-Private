// Exercise the actual dashboard's first render without a browser, network or user state.
// Run npm ci in metallic/dashboard first, then node scripts/verify_metallic_dashboard_fragment.mjs.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import vm from "node:vm";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dashboard = resolve(root, "metallic/dashboard");
const requireDashboard = createRequire(resolve(dashboard, "package.json"));
const { build } = await import(pathToFileURL(requireDashboard.resolve("vite")).href);
const React = requireDashboard("react");
const { renderToString } = requireDashboard("react-dom/server");
const context = vm.createContext({
  location: { hash: "" },
  fetch() { throw new Error("The fragment check must not make a network request"); },
});

const entry = resolve(dashboard, "fragment-check-entry.ts").replaceAll("\\", "/");
const virtualEntry = "\0fragment-check";
const sourcePath = (name) => JSON.stringify(resolve(dashboard, "src", name).replaceAll("\\", "/"));
const result = await build({
  root: dashboard,
  configFile: false,
  logLevel: "silent",
  plugins: [{
    name: "fragment-check-entry",
    resolveId(id) { return id.replaceAll("\\", "/") === entry ? virtualEntry : null; },
    load(id) {
      return id === virtualEntry
        ? `export { default as App } from ${sourcePath("App.tsx")};\nexport { projectFromHash } from ${sourcePath("model.ts")};`
        : null;
    },
  }],
  build: {
    write: false,
    minify: false,
    lib: { entry, formats: ["cjs"], fileName: "fragment-check" },
    rolldownOptions: { external: (id) => id === "react" || id.startsWith("react/") },
  },
});
const output = (Array.isArray(result) ? result[0] : result).output;
const chunk = output.find((file) => file.type === "chunk" && file.isEntry);
assert.ok(chunk, "The in-memory build must contain the actual dashboard entry");
const module = { exports: {} };
const compiled = vm.runInContext(`(function(require, module, exports) {\n${chunk.code}\n})`, context);
compiled(requireDashboard, module, module.exports);
const { App, projectFromHash } = module.exports;
const cases = [
  ["", null],
  ["#", null],
  ["#STAR", "STAR"],
  ["#Metallic%20MC", "Metallic MC"],
  ["#%E6%98%9F%20%F0%9F%8C%9F", "星 🌟"],
  ["#%23project%25", "#project%"],
  ["#%2525", "%25"],
  ["#with+plus", "with+plus"],
  ["#%", null],
  ["#%2", null],
  ["#%GG", null],
  ["#%E0%A4%A", null],
  ["#%ED%A0%80", null],
];

for (const [hash, expected] of cases) {
  assert.equal(projectFromHash(hash), expected, `Selection for ${JSON.stringify(hash)}`);
  context.location.hash = hash;
  const markup = renderToString(React.createElement(App));
  assert.match(markup, /Loading data\.json/, `Dashboard failed to start for ${JSON.stringify(hash)}`);
  assert.equal(context.location.hash, hash, "Rendering must preserve the original link");
}
console.log(`${cases.length} project fragments passed helper and actual React first-render checks; no network or browser.`);
