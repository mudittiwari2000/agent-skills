// Render a Mermaid diagram to PNG with a local headless Chromium.
// usage: LD_LIBRARY_PATH=<libasound dir> node render_mermaid.mjs <diagram.mmd> <out.png>
// Needs: `npm ci` in this folder once (playwright-core), a Chromium headless shell, and network
// access to cdn.jsdelivr.net for mermaid (pinned below).
// Browser lookup, first hit wins:
//   CHROMIUM_EXECUTABLE       full path to a chrome-headless-shell / chromium binary;
//   PLAYWRIGHT_BROWSERS_PATH  a Playwright browser cache (default ~/.cache/ms-playwright), searched
//                             for the newest chromium_headless_shell-*/chrome-headless-shell-<os>/ build.
import { chromium } from "playwright-core";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

const [, , src, out] = process.argv;
if (!src || !out) { console.error("usage: node render_mermaid.mjs <diagram.mmd> <out.png>"); process.exit(2); }

const MERMAID_VERSION = "11.17.2";
function findChromium() {
  const explicit = process.env.CHROMIUM_EXECUTABLE;
  if (explicit) {
    if (!existsSync(explicit)) { console.error(`CHROMIUM_EXECUTABLE does not exist: ${explicit}`); process.exit(1); }
    return explicit;
  }
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || join(homedir(), ".cache/ms-playwright");
  const shells = existsSync(cache) ? readdirSync(cache).filter(d => d.startsWith("chromium_headless_shell-")).sort() : [];
  if (!shells.length) { console.error(`no chromium_headless_shell in ${cache} (set CHROMIUM_EXECUTABLE or PLAYWRIGHT_BROWSERS_PATH)`); process.exit(1); }
  const dir = join(cache, shells.at(-1));
  const sub = readdirSync(dir).find(d => d.startsWith("chrome-headless-shell-"));
  const bin = sub && ["chrome-headless-shell", "chrome-headless-shell.exe"].map(b => join(dir, sub, b)).find(existsSync);
  if (!bin) { console.error(`no chrome-headless-shell binary under ${dir} (set CHROMIUM_EXECUTABLE)`); process.exit(1); }
  return bin;
}
const exe = findChromium();

const diagram = readFileSync(src, "utf8").replace(/</g, "&lt;");
const html = `<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;padding:24px;background:#fff;font-family:Arial,Helvetica,sans-serif}#d{display:inline-block}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@${MERMAID_VERSION}/dist/mermaid.min.js"></script></head>
<body><pre id="d" class="mermaid">${diagram}</pre><script>
mermaid.initialize({startOnLoad:false,theme:"base",themeVariables:{fontSize:"16px",fontFamily:"Arial, Helvetica, sans-serif",
  primaryColor:"#eef2ff",primaryBorderColor:"#6366f1",lineColor:"#475569"},
  flowchart:{htmlLabels:true,curve:"basis",useMaxWidth:false,wrappingWidth:320,nodeSpacing:40,rankSpacing:55,padding:14}});
mermaid.run({querySelector:"#d"}).then(()=>document.body.dataset.r="yes").catch(e=>document.body.dataset.r="error: "+e);
</script></body></html>`;

const browser = await chromium.launch({ executablePath: exe });
const page = await browser.newPage({ deviceScaleFactor: 2, viewport: { width: 1600, height: 1200 } });
await page.setContent(html, { waitUntil: "load" });
await page.waitForFunction(() => document.body.dataset.r, null, { timeout: 30000 });
const state = await page.evaluate(() => document.body.dataset.r);
if (state !== "yes") { console.error("mermaid failed:", state); await browser.close(); process.exit(1); }
const el = await page.$("#d svg");
const box = await el.boundingBox();
await el.screenshot({ path: out });
console.log(`rendered ${out}: ${Math.round(box.width)}x${Math.round(box.height)} css px (2x PNG)`);
await browser.close();
