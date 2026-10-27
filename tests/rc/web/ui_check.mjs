// Drives launcher/web/rc/preview.html (the RC page with a pretend module) in a real browser and checks what the player
// would see. Run:   node tests/rc/web/ui_check.mjs
// Needs Playwright core (PLAYWRIGHT_CORE=<path to playwright-core>, default: the global @playwright/cli copy) and
// Microsoft Edge or Chrome. Serves launcher/web (plus ../art, ../css from the launcher repo when present) itself.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { createRequire } from "node:module";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import os from "node:os";

const here = fileURLToPath(new URL(".", import.meta.url));
const webRoot = resolve(here, "../../../launcher/web");
const extraRoot = process.env.LAUNCHER_WEB || ""; // the launcher's own launcher/web, for css/ art/ fonts/ (optional)
const coreGuess = join(os.homedir(), "AppData/Roaming/npm/node_modules/@playwright/cli/node_modules/playwright-core");
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE || coreGuess);

const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".jpg": "image/jpeg", ".woff2": "font/woff2", ".svg": "image/svg+xml" };
const server = createServer(async (req, res) => {
  const rel = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname)).replace(/^([/\\])+/, "");
  for (const root of [webRoot, extraRoot].filter(Boolean)) {
    const file = join(root, rel);
    if (!file.startsWith(root)) continue;
    try { if ((await stat(file)).isFile()) { res.writeHead(200, { "content-type": types[extname(file)] || "application/octet-stream" }); res.end(await readFile(file)); return; } } catch { /* try next root */ }
  }
  res.writeHead(404); res.end();
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/rc/preview.html`;

let failures = 0;
const check = (name, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  " + extra}`); if (!ok) failures++; };

let browser;
try { browser = await chromium.launch({ channel: "msedge", headless: true }); }
catch { browser = await chromium.launch({ channel: "chrome", headless: true }); }

async function open(scenario, size = { width: 1360, height: 900 }, extra = "") {
  const ctx = await browser.newContext({ viewport: size });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/favicon|404/.test(m.text())) errors.push(m.text()); });
  await page.goto(`${base}?scenario=${scenario}${extra}`);
  await page.waitForSelector(".rc-hero");
  page.errors = errors;
  return page;
}
const stagesOf = (page) => page.$$eval(".rc-hero .rc-stages li", (els) => els.map((e) => e.dataset.state));

// 1. typical: Play runs every stage and reports the real command
{
  const page = await open("typical");
  check("play button says Play and is enabled", (await page.textContent("#rcPlay")).trim() === "Play" && !(await page.isDisabled("#rcPlay")));
  check("what-Play-does names the command", (await page.textContent(".rc-does")).includes("+forcemode:screen"));
  await page.click("#rcPlay");
  await page.waitForSelector(".rc-hero .rc-task:not([hidden])");
  check("progress track shows 7 steps", (await stagesOf(page)).length === 7);
  check("play is disabled while starting", await page.isDisabled("#rcPlay"));
  await page.waitForSelector(".rc-ok-line", { timeout: 15000 });
  check("success line shows the exact command", (await page.textContent(".rc-ok-line")).includes("RecRoom.exe +forcemode:screen"));
  check("backend-stopped warning absent when running", (await page.$$(".rc-hero .rc-warn-line")).length === 0);
  check("no page errors", page.errors.length === 0, page.errors.join(" | "));
  await page.context().close();
}

// 2. VR without a runtime warns before and after
{
  const page = await open("offline-vr");
  await page.click(".rc-seg button:has-text('VR')");
  await page.waitForSelector(".rc-hero .rc-warn-line");
  check("VR hint appears with no runtime", (await page.textContent(".rc-hero .rc-warn-line")).includes("No VR runtime"));
  await page.click("#rcPlay");
  await page.waitForSelector(".rc-ok-line", { timeout: 15000 });
  check("VR launch passes +forcemode:vr", (await page.textContent(".rc-ok-line")).includes("+forcemode:vr"));
  await page.context().close();
}

// 3. changed files: launch stops, offers the baseline action only as a confirm step
{
  const page = await open("changed");
  await page.click("#rcPlay");
  await page.waitForSelector(".rc-error", { timeout: 15000 });
  check("files-changed card with title", (await page.textContent(".rc-error strong")).includes("Client files changed"));
  check("the error card gives the cause under Details", (await page.textContent(".rc-error .rc-details")).includes("GameAssembly.dll"));
  await page.click(".rc-error button:has-text('baseline')");
  await page.waitForSelector(".rc-confirm");
  check("accepting new files asks first", (await page.textContent(".rc-confirm")).includes("Only accept if you know why"));
  await page.click(".rc-confirm button:has-text('Accept the current files')");
  await page.waitForSelector(".rc-client[aria-current='true'] .rc-chip.info", { timeout: 15000 });
  check("client goes back to Added after accepting", (await page.textContent(".rc-client[aria-current='true']")).includes("Added"));
  await page.context().close();
}

// 4. fresh PC: Play installs the tools, with a progress track and a verified result
{
  const page = await open("fresh");
  check("play says Install RC tools", (await page.textContent("#rcPlay")).includes("Install RC tools"));
  await page.click("#rcPlay");
  await page.waitForSelector(".rc-panel[aria-label='RC tools'] .rc-task:not([hidden])");
  check("tools task shows its steps", (await page.$$(".rc-panel[aria-label='RC tools'] .rc-stages li")).length === 5);
  await page.waitForFunction(() => /Version 0\.3/.test(document.querySelector(".rc-panel[aria-label='RC tools']").textContent), null, { timeout: 15000 });
  check("tools now show a managed version", (await page.textContent(".rc-panel[aria-label='RC tools'] .rc-chip")).includes("v0.3"));
  check("clients list is back after install", (await page.$$(".rc-client")).length >= 4);
  await page.context().close();
}

// 5. backend: start then stop, with honest capability rows
{
  const page = await open("backend-off");
  const panel = ".rc-panel[aria-label='RC backend']";
  check("backend shows Stopped", (await page.textContent(`${panel} .rc-chip`)).includes("Stopped"));
  await page.click(`${panel} button:has-text('Start')`);
  await page.waitForSelector(`${panel} .rc-chip.ok`, { timeout: 15000 });
  const caps = await page.textContent(`${panel} .rc-caps`);
  check("native sign-in is reported as not yet", /Original game sign-in\s*Not yet/.test(caps));
  check("the honesty line is present", (await page.textContent(panel)).includes("has not logged into it"));
  await page.click(`${panel} button:has-text('Stop')`);
  await page.waitForSelector(`${panel} .rc-chip.off`, { timeout: 15000 });
  check("backend stopped again", (await page.textContent(`${panel} .rc-chip`)).includes("Stopped"));
  await page.context().close();
}

// 6. partner revival with its own launcher asks for confirmation
{
  const page = await open("typical");
  await page.click(".rc-client:has-text('Campus') .rc-client-main");
  check("external client disables the screen/VR switch", await page.isDisabled(".rc-seg button:has-text('VR')"));
  await page.click("#rcPlay");
  await page.waitForSelector(".rc-confirm");
  check("confirm names the launcher exe", (await page.textContent(".rc-confirm")).includes("Campus.exe"));
  await page.click(".rc-confirm button:has-text('Cancel')");
  check("cancel closes the confirm", (await page.$$(".rc-confirm")).length === 0);
  await page.click("#rcPlay");
  await page.click(".rc-confirm .primary");
  await page.waitForSelector(".rc-ok-line", { timeout: 15000 });
  check("Campus runs through its launcher", (await page.textContent(".rc-ok-line")).includes("Campus.exe"));
  await page.context().close();
}

// 7. keyboard: tab order reaches Play first; every button has a name
{
  const page = await open("typical");
  await page.keyboard.press("Tab");
  check("first tab stop is Play", (await page.evaluate(() => document.activeElement.id)) === "rcPlay");
  const unnamed = await page.$$eval("button", (bs) => bs.filter((b) => !b.textContent.trim() && !b.getAttribute("aria-label")).length);
  check("all buttons have names", unnamed === 0);
  await page.context().close();
}

// 8. layout: narrow window has no horizontal scroll; light theme renders
for (const [name, size, extra] of [["narrow", { width: 700, height: 900 }, ""], ["light", { width: 1360, height: 900 }, "&theme=light"]]) {
  const page = await open("typical", size, extra);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check(`${name}: no horizontal overflow`, overflow <= 0, String(overflow));
  await page.context().close();
}

await browser.close();
server.close();
console.log(failures ? `\n${failures} check(s) failed` : "\nall UI checks passed");
process.exit(failures ? 1 : 0);
