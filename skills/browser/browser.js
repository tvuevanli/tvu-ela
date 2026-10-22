#!/usr/bin/env node
// The browser sense's driver: Playwright over the bundled Chromium, as the owner's own MediaHub session.
// Invoked only by browser.py; prints one JSON object. Cookies come from the site's session.json (`ela login tvu`
// keeps every .tvunetworks.com cookie there), because the gateway routes each service by per-user tag cookies —
// a SID alone lands on the gateway's default lane and proves nothing.
const fs = require("fs"), path = require("path");
const { chromium } = require("playwright");
const SITE = path.join(process.env.HOME, ".claude", "ela");

// Two hosts, two sessions. prod (the gateway with the test, daily and prod lanes) is the owner's own login, captured by
// `ela login tvu`; qa (the separate QA deployment) is ela's own session with the QA test account, captured by
// `browser.js login` below. Each session's cookies live under their own key in session.json and are set on their own
// domain; the gateway routes by per-user tag cookies, so a SID alone lands on the default lane and proves nothing.
const HOST = process.env.ELA_BROWSER_HOST === "qa" ? "qa" : "prod";
const SESSION_KEY = HOST === "qa" ? "qa" : "tvu";
const DOMAIN = process.env.ELA_BROWSER_DOMAIN || (HOST === "qa" ? ".tvutest.com" : ".tvunetworks.com");

function cookies() {
  const s = (JSON.parse(fs.readFileSync(path.join(SITE, "session.json"), "utf8"))[SESSION_KEY]) || {};
  if (!s.cookies || !Object.keys(s.cookies).length) throw new Error(`no ${SESSION_KEY} cookies in session.json — run: ` + (HOST === "qa" ? "ela browser login --host qa" : "ela login tvu --force"));
  return Object.entries(s.cookies).map(([name, value]) => ({ name, value, domain: DOMAIN, path: "/", secure: name === "SID" }));
}

// The QA deployment's own login: the user service's sign-in page (account + password fields, a Sign In button),
// reached by opening the product without a session; every cookie on the QA domain is kept afterwards.
async function login(url) {
  const account = process.env.TVUTEST_ACCOUNT, password = process.env.TVUTEST_PASSWORD;
  if (!account || !password) throw new Error("TVUTEST_ACCOUNT / TVUTEST_PASSWORD missing");
  const b = await chromium.launch();
  const ctx = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1600, height: 1000 } });
  const p = await ctx.newPage();
  try {
    await p.goto(url, { waitUntil: "networkidle", timeout: 60000 });
    await p.locator("#account").fill(account);
    await p.locator("#password").fill(password);
    await p.locator("button.sign-submit-btn").click();
    await p.waitForURL(u => !/signIn/.test(String(u)), { timeout: 60000 });
    await p.waitForLoadState("networkidle", { timeout: 60000 }).catch(() => {});
    await p.waitForTimeout(3000);
    const jar = {};
    for (const c of await ctx.cookies()) if (c.domain.endsWith(DOMAIN.replace(/^\./, ""))) jar[c.name] = c.value;
    const file = path.join(SITE, "session.json");
    const all = JSON.parse(fs.readFileSync(file, "utf8"));
    all[SESSION_KEY] = { cookies: jar, obtained_at: new Date().toISOString(), source: "browser login (test account)", account };
    fs.writeFileSync(file, JSON.stringify(all, null, 2));
    return { landed: p.url(), cookies: Object.keys(jar).length };
  } finally { await b.close(); }
}

async function open(opts = {}) {
  const b = await chromium.launch();
  // The clock the page sees: the site's timezone (browser.py passes ELA_TZ), so a cross-day or a scheduled-time
  // case reads the same wall clock the owner reads; the resolved zone and time go into every result.
  const opt = { ignoreHTTPSErrors: true, viewport: { width: 1600, height: 1000 } };
  if (process.env.ELA_TZ) opt.timezoneId = process.env.ELA_TZ;
  if (process.env.ELA_LOCALE) opt.locale = process.env.ELA_LOCALE;
  const ctx = await b.newContext(opt);
  await ctx.addCookies(cookies());
  const p = await ctx.newPage(); p.setDefaultTimeout(opts.timeout || 10000);
  const errors = []; p.on("pageerror", e => errors.push(String(e.message).split("\n")[0]));
  return { b, ctx, p, errors };
}

async function clockOf(p) {
  return p.evaluate(() => ({ tz: Intl.DateTimeFormat().resolvedOptions().timeZone, now: new Date().toISOString() }));
}

// The version panel: an el-tooltip on the MediaHub logo (tvu-common-ui top-header). Its text names every
// service's ENV and build; a panel without ENV lines is the unproven state.
async function panel(p, url, shot) {
  await p.goto(url, { waitUntil: "networkidle", timeout: 60000 });
  await p.waitForTimeout(3000);
  await p.locator(".top-header-container .el-tooltip").first().hover();
  const pop = p.locator(".top-header-version").first();
  await pop.waitFor({ state: "visible", timeout: 8000 });
  const text = await pop.innerText();
  if (shot) { await p.waitForTimeout(400); await p.screenshot({ path: shot, fullPage: false }); } // the panel open, after its fade-in
  await p.mouse.move(800, 900);
  return text.replace(/\n\n+/g, "\n").trim();
}

// Services the panel does not list but the account's session reaches through the gateway, which routes each
// service by the session's own tags: the scheduler (tvu-aioc-service) answers GET /base/version with
// "<build>|<common build>" (its BaseController). The gateway host is the one the product itself was handed in
// /base/initConfig (store.initConfig.gatewayUrl), captured off the wire, never configured here. A version read
// this way is recorded beside the panel; it is the account's lane by construction and has no map entry to match.
const GATEWAY_SERVICES = { "tvu-aioc-service": "/tvu-aioc-service/base/version" };
async function gatewayVersions(p, gateway) {
  const out = {};
  for (const [slug, path] of Object.entries(GATEWAY_SERVICES)) {
    try {
      const r = await p.request.get(gateway + path, { timeout: 15000 });
      const t = (await r.text()).trim();
      out[slug] = { path, status: r.status(), version: r.status() === 200 && t.length < 200 && !/</.test(t) ? t : null };
    } catch (e) { out[slug] = { path, status: 0, version: null, error: String(e).slice(0, 120) }; }
  }
  return out;
}

(async () => {
  const [cmd, ...rest] = process.argv.slice(2);
  const arg = (k, d) => { const i = rest.indexOf(k); return i >= 0 ? rest[i + 1] : d; };
  const out = (o) => process.stdout.write(JSON.stringify(o) + "\n");
  const url = arg("--url");
  if (cmd === "login") {
    out(await login(url));
  } else if (cmd === "env") {
    const { b, p } = await open(); try {
      let gateway = null;
      p.on("response", async (res) => {
        if (gateway || !/\/base\/initConfig/.test(res.url())) return;
        try { const j = await res.json(); const g = j && j.result && j.result.gatewayUrl; if (g) gateway = /^https?:/.test(g) ? g : new URL(url).protocol + "//" + g; } catch (e) {}
      });
      const shot = arg("--shot");
      const text = await panel(p, url, shot);
      const services = gateway ? await gatewayVersions(p, gateway) : {};
      out({ url, panel: text, clock: await clockOf(p), shot: shot || null, gateway_seen: !!gateway, services });
    } finally { await b.close(); }
  } else if (cmd === "shot") {
    const { b, p } = await open(); try {
      await p.goto(url, { waitUntil: "networkidle", timeout: 60000 }); await p.waitForTimeout(2000);
      await p.screenshot({ path: arg("--out"), fullPage: !!arg("--full", false) }); out({ url, out: arg("--out") });
    } finally { await b.close(); }
  } else if (cmd === "pdf") {
    // Print a local page (the verify report) to PDF: Jira previews a PDF inline where an HTML is shown as source.
    const { b, p } = await open(); try {
      await p.goto("file://" + path.resolve(arg("--in")), { waitUntil: "load", timeout: 60000 });
      await p.emulateMedia({ media: "print" });
      await p.pdf({ path: arg("--out"), format: "A4", printBackground: true, margin: { top: "14mm", bottom: "14mm", left: "12mm", right: "12mm" } });
      out({ in: arg("--in"), out: arg("--out") });
    } finally { await b.close(); }
  } else if (cmd === "run") {
    // A case script exports `async ({ p, ctx, b, panel, url, shots, phase, state, fakeTime }) => result`. It reads; it
    // never saves unless the owner's confirm reached the script by its own flag. `shots` is the directory for its
    // screenshots. A scheduled behaviour spans two runs: `--phase create` leaves what it made in `--state F` (ids,
    // the scheduled time), `--phase observe` reads it back later. `fakeTime(iso)` installs a fake browser clock for a
    // form or display case (the server's clock stays real); the result records it so the report can say so.
    const script = path.resolve(arg("--script")); const shots = arg("--shots"); if (shots) fs.mkdirSync(shots, { recursive: true });
    const phase = arg("--phase", null), stateFile = arg("--state", null);
    let state = {}; if (stateFile && fs.existsSync(stateFile)) state = JSON.parse(fs.readFileSync(stateFile, "utf8"));
    const { b, ctx, p, errors } = await open(); let result, err = null, faked = null;
    const fakeTime = async (iso) => { await p.clock.install({ time: new Date(iso) }); faked = iso; };
    try { result = await require(script)({ p, ctx, b, panel, url, shots, phase, state, fakeTime }); }
    catch (e) { err = String(e.message).split("\n")[0]; }
    const clock = await clockOf(p).catch(() => null);
    await b.close();
    if (stateFile) fs.writeFileSync(stateFile, JSON.stringify(state, null, 1));
    out({ script, phase, result, error: err, page_errors: errors, clock, fake_time: faked, state: stateFile ? state : undefined });
  } else {
    process.stderr.write("usage: browser.js login|env|shot|run|pdf --url U [--in F] [--out F] [--script S] [--shots D] [--phase P] [--state F]\n"); process.exit(2);
  }
})().catch(e => { process.stderr.write(String(e.message).split("\n")[0] + "\n"); process.exit(5); });
