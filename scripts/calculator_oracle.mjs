#!/usr/bin/env node
// Runs FantasyCalc's and KeepTradeCut's own trade-calculator code, fetched live,
// so ff's Python ports (src/ff/analysis/calculators.py) can be checked against
// the sites instead of against a re-typed formula. Needs Node 18+ (global fetch);
// no npm packages. Writes nothing to disk: every mode prints JSON to stdout.
//
//   node scripts/calculator_oracle.mjs --generate > tests/fixtures/calculator_vectors.json
//   node scripts/calculator_oracle.mjs --check tests/fixtures/calculator_vectors.json
//   echo '{"trades":[...]}' | node scripts/calculator_oracle.mjs --eval
//
// --generate  builds golden vectors (seeded, deterministic) and fails unless every
//             KTC branch that random + targeted search can reach has >= 5 vectors.
// --check     recomputes every vector with today's live code; exit 1 on any diff.
// --eval      reads {"fc_params":{...}, "ktc_tep":0..3, "ktc_format":1|2, "ktc_html"?:page,
//             "trades":[{"side1":[{"fc":name,"ktc":name}],"side2":[...]}]} and prints
//             each asset's value as the sites look it up, the KTC top value, and the
//             sites' adjustments, totals and verdicts.

import vm from "node:vm";
import { readFileSync } from "node:fs";

const UA = { "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)" };
const FC_SITE = "https://fantasycalc.com";
const KTC_SITE = "https://keeptradecut.com";

async function text(url) {
  const res = await fetch(url, { headers: UA });
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.text();
}

// Brace-matched source of every definition of `name` (function or class method).
function extractFunctions(js, name) {
  const out = [];
  const re = new RegExp(`(?<![\\w$.])${name.replace(/\$/g, "\\$")}\\(`, "g");
  let m;
  while ((m = re.exec(js))) {
    let i = m.index + m[0].length - 1, depth = 0, endParams = -1;
    for (; i < js.length; i++) {
      const ch = js[i];
      if (ch === '"' || ch === "'" || ch === "`") { i = skipString(js, i); continue; }
      if (ch === "(") depth++;
      else if (ch === ")" && --depth === 0) { endParams = i + 1; break; }
    }
    if (endParams < 0) continue;
    let j = endParams;
    while (/\s/.test(js[j])) j++;
    if (js[j] !== "{") continue; // a call, not a definition
    depth = 0;
    for (let k = j; k < js.length; k++) {
      const ch = js[k];
      if (ch === '"' || ch === "'" || ch === "`") { k = skipString(js, k); continue; }
      if (ch === "{") depth++;
      else if (ch === "}" && --depth === 0) { out.push(js.slice(m.index, k + 1)); break; }
    }
  }
  return out;
}

function skipString(js, i) {
  const q = js[i];
  for (let k = i + 1; k < js.length; k++) {
    if (js[k] === "\\") { k++; continue; }
    if (js[k] === q) return k;
  }
  return js.length;
}

function one(js, name) {
  const defs = extractFunctions(js, name);
  if (!defs.length) throw new Error(`function ${name} not found in bundle`);
  return defs[0];
}

// ---------------------------------------------------------------- FantasyCalc

async function loadFantasyCalc() {
  const page = await text(`${FC_SITE}/trade-calculator`);
  const main = (page.match(/src="(main-[A-Z0-9]+\.js)"/) || [])[1];
  if (!main) throw new Error("FantasyCalc main bundle not found");
  const mainJs = await text(`${FC_SITE}/${main}`);
  const chunk = (mainJs.match(/path:"trade-calculator"[^}]*?import\("\.\/(chunk-[A-Z0-9]+\.js)"\)/) || [])[1];
  if (!chunk) throw new Error("FantasyCalc trade-calculator chunk not found");
  const js = await text(`${FC_SITE}/${chunk}`);
  const consts = [...js.matchAll(/([\w$]+)=(\{pctFactor:[\d.]+,adjustmentFactor:[\d.]+,adjustmentScalar:[\d.]+\})/g)];
  if (consts.length < 2) throw new Error("FantasyCalc adjustment constants not found");
  const src =
    consts.map(([, n, obj]) => `const ${n}=${obj};`).join("") +
    `class S{${one(js, "getValueAdjustment")}${one(js, "getLegacyRedraftValueAdjustment")}}; new S()`;
  const svc = vm.runInNewContext(src, {});
  return {
    main, chunk,
    dynasty: (s1, s2) => { const r = svc.getValueAdjustment(true, s1.map(value => ({ value })), s2.map(value => ({ value }))); return [r.side1Adj, r.side2Adj]; },
  };
}

// ------------------------------------------------------------------------ KTC

const BRANCH_TAG = /adjustment\.value=(?!=)/g;

async function loadKtc() {
  const page = await text(`${KTC_SITE}/trade-calculator`);
  const version = (page.match(/site\.min\.js\?v=([\w-]+)/) || [])[1];
  if (!version) throw new Error("KTC site.min.js version not found");
  const js = await text(`${KTC_SITE}/js/site.min.js?v=${version}`);
  for (const [re, what] of [[/\bALGOTOUSE=2\b/, "ALGOTOUSE=2"], [/\bMAXPLAYERVAL=1e4\b/, "MAXPLAYERVAL=1e4"], [/\btcFilters=\{variance:5,pickVal:0\b/, "tcFilters defaults"]]) {
    if (!re.test(js)) throw new Error(`KTC ${what} changed`);
  }
  let tag = 0;
  const adjust = one(js, "adjustPackageNew").replace(BRANCH_TAG, () => `__hit(${tag++}),adjustment.value=`);
  const branchCount = tag;
  const noop = new Proxy(function () {}, { get: (t, k) => (k === Symbol.toPrimitive ? () => "" : noop), apply: () => noop });
  const ctx = {
    Math, JSON, parseInt, parseFloat, console,
    $: noop, d3: noop, setURLParams() {}, displayAdjustment() {}, displayPlayerToEven() {},
    tradeExamples() {}, tradeGraphs() {}, clearGraphs() {},
    updateSummary(t, r) { ctx.__summary = [t, r]; },
    ALGOTOUSE: 2, MAXPLAYERVAL: 1e4, CURTRADE: 0,
    tcFilters: { variance: 5, pickVal: 0, leagueSize: 12 },
    adjustment: { side: -1, value: 0, display: false },
    playersArray: [{ value: 9999 }],
    __hits: new Array(branchCount).fill(0),
    __hit(i) { ctx.__branch.push(i); },
    __branch: [],
  };
  vm.createContext(ctx);
  vm.runInContext(
    [one(js, "checkEquality"), adjust, one(js, "processVNew"), one(js, "reverseAdjustNew"),
     one(js, "solveForX"), one(js, "evaluateTrade")].map(s => `function ${s}`).join("\n") +
    "\nvar tOne,tTwo;", ctx);

  const team = values => ({
    totalValue: values.reduce((a, b) => a + b, 0), totalPlayers: values.length,
    players: values.map(value => ({ value, position: "WR" })), adjust: 0, adjTotal: 0, rawAdj: 0,
    maxVal: Math.max(0, ...values),
  });
  function run(s1, s2, top, variance = 5) {
    ctx.playersArray = [{ value: top }];
    ctx.tcFilters.variance = variance;
    ctx.teamOne = team(s1); ctx.teamTwo = team(s2);
    ctx.__branch = []; ctx.__summary = null; ctx.CURTRADE = 0;
    let error = null;
    try { vm.runInContext("evaluateTrade(true, false)", ctx); } catch (e) { error = String(e.message || e); }
    const a = ctx.adjustment;
    return {
      adj1: ctx.teamOne.adjust, adj2: ctx.teamTwo.adjust, side: a.side,
      shown: Boolean(a.display) && (s1.length > 1 || s2.length > 1),
      total1: ctx.__summary ? ctx.__summary[0] : null, total2: ctx.__summary ? ctx.__summary[1] : null,
      fair: ctx.CURTRADE === 1, error,
      branches: ctx.__branch.filter(i => i !== 0),
    };
  }
  return { version, run, branchCount, js };
}

// -------------------------------------------------------------------- vectors

function rng(seed) { // mulberry32
  return () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const randSide = (r, n, lo, hi) => Array.from({ length: n }, () => Math.round(lo + r() * (hi - lo)));

async function generate() {
  const fc = await loadFantasyCalc();
  const ktc = await loadKtc();
  const r = rng(20260930);

  const fcCases = [[[1446, 1344], [3068]], [[3068], [1446, 1344]], [[5000], [3000, 2000]], [[8000], [3000, 2500, 2000]],
    [[9000], [2000, 2000, 2000, 2000]], [[100], [50, 40]], [[10], [5, 3, 1]], [[4000, 3000], [2000, 1500]], [[1078], [1078, 1078]],
    [[1079], [1079, 1079]], [[9000], [1, 1, 1, 1, 1, 1, 1]], [[5000], [1000, 1000, 1000]], [[], [5000]], [[5000], []]];
  for (let i = 0; i < 200; i++) {
    const n1 = 1 + Math.floor(r() * 4), n2 = 1 + Math.floor(r() * 4);
    fcCases.push([randSide(r, n1, 50, 11000), randSide(r, n2, 50, 11000)]);
  }
  const fcVectors = fcCases.map(([side1, side2]) => { const [a1, a2] = fc.dynasty(side1, side2); return { side1, side2, adj1: a1, adj2: a2 }; });

  const ktcVectors = [];
  const hits = new Array(ktc.branchCount).fill(0);
  const add = (side1, side2, top, variance = 5) => {
    const out = ktc.run(side1, side2, top, variance);
    out.branches.forEach(b => hits[b]++);
    ktcVectors.push({ side1, side2, top, variance, ...out });
  };
  const fixed = [[[2484, 2815], [4736]], [[2454, 2824], [4729]], [[5000], [5000]], [[5100], [5000]], [[6000], [5000]],
    [[9999], [3000]], [[9999], [9997]], [[8000], [4000, 4000]], [[8000], [6000, 5000]], [[8000], [6000, 4500]],
    [[6000, 3000], [5000, 4000]], [[4628], [9967, 8531, 6620]], [[3075, 4014, 4047], [970]], [[9731, 7730], [9962, 6198, 3787]],
    [[1000, 1000, 1000, 1000, 1000], [5000]], [[5000, 5000], [5000, 5000]], [[0], [5000]], [[0], [0]], [[0, 0], [0]]];
  for (const [a, b] of fixed) add(a, b, 9999);
  add([2454, 2824], [4729], 9000);
  add([9731, 7730], [9962, 6198, 3787], 9999, 10);
  for (let i = 0; i < 400; i++) {
    const n1 = 1 + Math.floor(r() * 4), n2 = 1 + Math.floor(r() * 4);
    add(randSide(r, n1, 100, 9999), randSide(r, n2, 100, 9999), 9990 + Math.floor(r() * 10));
  }
  // Targeted search: keep sampling until every branch reachable by 1-6 vs 1-6
  // trades has >= 5 vectors (rare ones are ~0.1% of random trades).
  const MIN = 5;
  for (let i = 0; i < 400000 && hits.some((h, b) => b > 0 && h > 0 && h < MIN); i++) {
    const n1 = 1 + Math.floor(r() * 6), n2 = 1 + Math.floor(r() * 6);
    const s1 = randSide(r, n1, 50, 9999), s2 = randSide(r, n2, 50, 9999);
    const out = ktc.run(s1, s2, 9999);
    if (out.branches.some(b => hits[b] < MIN)) { out.branches.forEach(b => hits[b]++); ktcVectors.push({ side1: s1, side2: s2, top: 9999, variance: 5, ...out }); }
  }
  const unreached = hits.map((h, b) => [b, h]).filter(([b, h]) => b > 0 && h === 0).map(([b]) => b);
  const thin = hits.map((h, b) => [b, h]).filter(([b, h]) => b > 0 && h > 0 && h < MIN);
  if (thin.length) throw new Error(`KTC branches with fewer than ${MIN} vectors: ${JSON.stringify(thin)}`);

  return {
    meta: {
      generated: process.argv.includes("--date") ? process.argv[process.argv.indexOf("--date") + 1] : "unknown",
      fantasycalc: { main: fc.main, chunk: fc.chunk },
      ktc: { version: ktc.version, branch_tags: ktc.branchCount - 1, branch_hits: hits.slice(1), unreached_branches: unreached },
    },
    fc_dynasty: fcVectors,
    ktc: ktcVectors.map(({ branches, ...v }) => ({ ...v, branches })),
  };
}

async function check(path) {
  const fixture = JSON.parse(readFileSync(path, "utf8"));
  const fc = await loadFantasyCalc();
  const ktc = await loadKtc();
  const diffs = [];
  if (fc.chunk !== fixture.meta.fantasycalc.chunk) diffs.push(`FantasyCalc chunk ${fixture.meta.fantasycalc.chunk} -> ${fc.chunk}`);
  if (ktc.version !== fixture.meta.ktc.version) diffs.push(`KTC version ${fixture.meta.ktc.version} -> ${ktc.version}`);
  for (const v of fixture.fc_dynasty) {
    const [a1, a2] = fc.dynasty(v.side1, v.side2);
    if (a1 !== v.adj1 || a2 !== v.adj2) diffs.push(`FC ${JSON.stringify([v.side1, v.side2])}: fixture ${v.adj1}/${v.adj2}, site ${a1}/${a2}`);
  }
  for (const v of fixture.ktc) {
    const o = ktc.run(v.side1, v.side2, v.top, v.variance);
    const same = (x, y) => (Number.isNaN(x) && Number.isNaN(y)) || x === y;
    if (!same(o.adj1, v.adj1) || !same(o.adj2, v.adj2) || o.fair !== v.fair || o.shown !== v.shown)
      diffs.push(`KTC ${JSON.stringify([v.side1, v.side2, v.top])}: fixture ${v.adj1}/${v.adj2}/${v.fair}, site ${o.adj1}/${o.adj2}/${o.fair}`);
  }
  console.log(JSON.stringify({ ok: diffs.length === 0, checked: { fc: fixture.fc_dynasty.length, ktc: fixture.ktc.length }, diffs: diffs.slice(0, 50) }, null, 1));
  process.exit(diffs.length ? 1 : 0);
}

async function evaluate() {
  const input = JSON.parse(readFileSync(0, "utf8"));
  const fc = await loadFantasyCalc();
  const ktc = await loadKtc();
  // FantasyCalc values: the same public endpoint the site's client calls.
  const q = new URLSearchParams(input.fc_params || {});
  const fcRows = JSON.parse(await text(`https://api.fantasycalc.com/values/current?${q}`));
  const fcByName = new Map(fcRows.map(e => [e.player.name, e.value]));
  // KTC values: the page's own payload, prepared by the site's own function. KTC's
  // crowdsourced values move between fetches, so a caller can pass the exact page
  // snapshot it priced from ("ktc_html") to compare like with like.
  const page = input.ktc_html || await text(`${KTC_SITE}/trade-calculator`);
  const payload = JSON.parse(page.match(/<script[^>]*id="ktc-players"[^>]*>([\s\S]*?)<\/script>/)[1]);
  // The page's own globals that its value selection reads, taken from the bundle.
  const pageGlobal = name => Number((ktc.js.match(new RegExp(`\\b${name}=(\\d+)`)) || [])[1]);
  const prep = vm.createContext({
    Math, console, hideForValueSource() {}, $: new Proxy(function () {}, { get: () => () => {}, apply: () => undefined }),
    LEAGUEYEAR: pageGlobal("LEAGUEYEAR"), LEAGUEYEARPHASE: pageGlobal("LEAGUEYEARPHASE"), DRAFTYEAR: pageGlobal("DRAFTYEAR"),
  });
  vm.runInContext(`function ${one(ktc.js, "updateSingleDynastyAsset")}`, prep);
  const cfg = [input.ktc_format === 1 ? 1 : 2, input.ktc_tep || 0, 1];
  const assets = payload.filter(e => e.superflexValues.value > 0 || e.oneQBValues.value > 0);
  for (const a of assets) prep.updateSingleDynastyAsset(cfg, a);
  const top = Math.max(...assets.map(a => a.value));
  const ktcByName = new Map(assets.map(a => [a.playerName, a.value]));
  const results = input.trades.map(t => {
    const look = (side, key, map) => side.map(x => (map.has(x[key]) ? map.get(x[key]) : null));
    const f1 = look(t.side1, "fc", fcByName), f2 = look(t.side2, "fc", fcByName);
    const k1 = look(t.side1, "ktc", ktcByName), k2 = look(t.side2, "ktc", ktcByName);
    const res = { fc_values: [f1, f2], ktc_values: [k1, k2], ktc_top: top };
    if (![...f1, ...f2].includes(null)) {
      const [a1, a2] = fc.dynasty(f1, f2);
      res.fc = { adj1: a1, adj2: a2, total1: f1.reduce((a, b) => a + b, 0) + a1, total2: f2.reduce((a, b) => a + b, 0) + a2 };
    }
    if (![...k1, ...k2].includes(null)) res.ktc = ktc.run(k1, k2, top);
    return res;
  });
  console.log(JSON.stringify({ fantasycalc: { chunk: fc.chunk }, ktc: { version: ktc.version }, results }, null, 1));
}

const mode = process.argv[2];
try {
  if (mode === "--generate") console.log(JSON.stringify(await generate()));
  else if (mode === "--check") await check(process.argv[3]);
  else if (mode === "--eval") await evaluate();
  else { console.error("usage: --generate | --check <fixture> | --eval < trades.json"); process.exit(2); }
} catch (e) {
  console.error(String(e.stack || e));
  process.exit(1);
}
