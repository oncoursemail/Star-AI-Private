// Headless render of one HTML file for star/design_render.py: screenshots at desktop and phone width plus the
// measurements only a browser can make (horizontal overflow, computed text contrast, fonts actually used, tiny text,
// tap targets). Usage: node design_render.mjs <file.html> <out_dir> [playwright-core dir]
// Prints one JSON object. Needs playwright-core (the one shipped with playwright-cli is fine) and its Chromium.
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";

const [file, outDir, pwDir] = process.argv.slice(2);
if (!file || !outDir) {
  console.error("usage: node design_render.mjs <file.html> <out_dir> [playwright-core dir]");
  process.exit(2);
}
const require = createRequire(import.meta.url);
const { chromium } = require(pwDir ? path.join(pwDir, "index.js") : "playwright-core");

const MEASURE = () => {
  const lum = (r, g, b) => {
    const c = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b);
  };
  const parse = (s) => {
    const m = s && s.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
    return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null;
  };
  const bgOf = (el) => {
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      const c = parse(cs.backgroundColor);
      if (cs.backgroundImage && cs.backgroundImage !== "none") return { gradient: true };
      if (c && c[3] > 0.6) return { rgb: c };
    }
    return { rgb: [255, 255, 255] };
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const pairs = [], fonts = new Set(), weights = new Set(), sizes = new Set();
  let tiny = 0, texts = 0;
  for (let n; (n = walker.nextNode());) {
    const t = n.textContent.trim();
    if (!t || !n.parentElement) continue;
    const el = n.parentElement;
    if (["SCRIPT", "STYLE", "NOSCRIPT"].includes(el.tagName)) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const cs = getComputedStyle(el);
    texts++;
    fonts.add(cs.fontFamily.split(",")[0].replace(/["']/g, "").trim().toLowerCase());
    weights.add(cs.fontWeight);
    const px = parseFloat(cs.fontSize);
    sizes.add(Math.round(px));
    if (px < 12) tiny++;
    const fg = parse(cs.color), bg = bgOf(el);
    if (fg && bg.rgb) {
      const l1 = lum(...fg), l2 = lum(...bg.rgb);
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      const big = px >= 24 || (px >= 18.66 && +cs.fontWeight >= 700);
      if (ratio < (big ? 3 : 4.5)) pairs.push({ text: t.slice(0, 40), ratio: +ratio.toFixed(2), px: Math.round(px) });
    }
  }
  let smallTargets = 0;
  for (const el of document.querySelectorAll("a,button,[role=button],input,select")) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && (r.height < 32 || r.width < 32)) smallTargets++;
  }
  const h1 = document.querySelector("h1");
  let h1Lines = 0;
  if (h1) {
    const lh = parseFloat(getComputedStyle(h1).lineHeight) || parseFloat(getComputedStyle(h1).fontSize) * 1.2;
    h1Lines = Math.round(h1.getBoundingClientRect().height / lh);
  }
  return {
    scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    scrollHeight: document.documentElement.scrollHeight,
    overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
    lowContrast: pairs.slice(0, 8), lowContrastCount: pairs.length, textNodes: texts, tinyText: tiny,
    fontsUsed: [...fonts], weightsUsed: [...weights].sort(), sizesUsed: [...sizes].sort((a, b) => a - b),
    smallTargets, h1Lines,
  };
};

const browser = await chromium.launch();
const result = { file, screenshots: {}, desktop: null, phone: null, error: "" };
try {
  const url = pathToFileURL(path.resolve(file)).href;
  for (const [name, viewport] of [["desktop", { width: 1280, height: 800 }], ["phone", { width: 390, height: 844 }]]) {
    const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
    page.setDefaultTimeout(15000);
    await page.goto(url, { waitUntil: "load" });
    await page.waitForTimeout(400);
    result[name] = await page.evaluate(MEASURE);
    const shot = path.join(outDir, `${name}.png`);
    await page.screenshot({ path: shot, fullPage: false });
    const full = path.join(outDir, `${name}-full.png`);
    await page.screenshot({ path: full, fullPage: true });
    result.screenshots[name] = shot;
    result.screenshots[name + "_full"] = full;
    await page.close();
  }
} catch (err) {
  result.error = String(err && err.message || err).slice(0, 300);
} finally {
  await browser.close();
}
process.stdout.write(JSON.stringify(result));
