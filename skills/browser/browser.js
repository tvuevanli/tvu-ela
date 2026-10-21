#!/usr/bin/env node
// The browser sense's driver: Playwright over the bundled Chromium, as the owner's own MediaHub session.
// Invoked only by browser.py; prints one JSON object. Cookies come from the site's session.json (`ela login tvu`
// keeps every .tvunetworks.com cookie there), because the gateway routes each service by per-user tag cookies —
// a SID alone lands on the gateway's default lane and proves nothing.
const fs = require("fs"), path = require("path");
const { chromium } = require("playwright");
const SITE = path.join(process.env.HOME, ".claude", "ela");

function cookies() {
  const s = (JSON.parse(fs.readFileSync(path.join(SITE, "session.json"), "utf8")).tvu) || {};
  if (!s.cookies || !Object.keys(s.cookies).length) throw new Error("no tvu cookies in session.json — run: ela login tvu --force");
  return Object.entries(s.cookies).map(([name, value]) => ({ name, value, domain: ".tvunetworks.com", path: "/", secure: name === "SID" }));
}

async function open(opts = {}) {
  const b = await chromium.launch();
  const ctx = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1600, height: 1000 } });
  await ctx.addCookies(cookies());
  const p = await ctx.newPage(); p.setDefaultTimeout(opts.timeout || 10000);
  const errors = []; p.on("pageerror", e => errors.push(String(e.message).split("\n")[0]));
  return { b, ctx, p, errors };
}

// The version panel: an el-tooltip on the MediaHub logo (tvu-common-ui top-header). Its text names every
// service's ENV and build; a panel without ENV lines is the unproven state.
async function panel(p, url) {
  await p.goto(url, { waitUntil: "networkidle", timeout: 60000 });
  await p.waitForTimeout(3000);
  await p.locator(".top-header-container .el-tooltip").first().hover();
  const pop = p.locator(".top-header-version").first();
  await pop.waitFor({ state: "visible", timeout: 8000 });
  const text = await pop.innerText();
  await p.mouse.move(800, 900);
  return text.replace(/\n\n+/g, "\n").trim();
}

(async () => {
  const [cmd, ...rest] = process.argv.slice(2);
  const arg = (k, d) => { const i = rest.indexOf(k); return i >= 0 ? rest[i + 1] : d; };
  const out = (o) => process.stdout.write(JSON.stringify(o) + "\n");
  const url = arg("--url");
  if (cmd === "env") {
    const { b, p } = await open(); try { out({ url, panel: await panel(p, url) }); } finally { await b.close(); }
  } else if (cmd === "shot") {
    const { b, p } = await open(); try {
      await p.goto(url, { waitUntil: "networkidle", timeout: 60000 }); await p.waitForTimeout(2000);
      await p.screenshot({ path: arg("--out"), fullPage: !!arg("--full", false) }); out({ url, out: arg("--out") });
    } finally { await b.close(); }
  } else if (cmd === "run") {
    // A case script exports `async ({ p, ctx, b, panel, url, shots }) => result`. It reads; it never saves unless
    // the owner's confirm reached the script by its own flag. `shots` is the directory for its screenshots.
    const script = path.resolve(arg("--script")); const shots = arg("--shots"); if (shots) fs.mkdirSync(shots, { recursive: true });
    const { b, ctx, p, errors } = await open(); let result, err = null;
    try { result = await require(script)({ p, ctx, b, panel, url, shots }); }
    catch (e) { err = String(e.message).split("\n")[0]; }
    finally { await b.close(); }
    out({ script, result, error: err, page_errors: errors });
  } else {
    process.stderr.write("usage: browser.js env|shot|run --url U [--out F] [--script S] [--shots D]\n"); process.exit(2);
  }
})().catch(e => { process.stderr.write(String(e.message).split("\n")[0] + "\n"); process.exit(5); });
