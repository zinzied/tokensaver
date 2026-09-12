import * as config from './config.js';
import { readJson } from './utils.js';
import * as rtk from './filters/rtk.js';
import * as routingMod from './routing.js';
import { accountManager, resolveUpstream } from './proxy.js';
import { createRequire } from 'node:module';
import type { SqliteDb, SqliteRow } from './types.js';

const require = createRequire(import.meta.url);

let _db: SqliteDb | null = null;

function openIndexDb(): SqliteDb | null {
  if (_db !== null) return _db;
  if (!config.INDEX_DB_PATH) return (_db = null);
  try {
    const Database = require('better-sqlite3');
    _db = new Database(config.INDEX_DB_PATH, { readonly: true }) as SqliteDb;
    return _db;
  } catch {}
  try {
    const { DatabaseSync } = require('node:sqlite');
    _db = new DatabaseSync(config.INDEX_DB_PATH, { readOnly: true }) as unknown as SqliteDb;
    return _db;
  } catch {
    return (_db = null);
  }
}

export function usageSummary() {
  const ledger = readJson<Array<Record<string, any>>>(config.LEDGER_PATH) || [];
  const pcfg = readJson<Record<string, any>>(config.PROXY_CONFIG) || {};
  const history = Array.isArray(pcfg.history) ? pcfg.history : [];

  const ledgerTotals = { entries: ledger.length, raw_tokens: 0, saved_tokens: 0 };
  const byKind = new Map<string, { count: number; saved_tokens: number }>();
  for (const e of ledger) {
    const raw = e.raw_tokens || 0;
    const saved = e.saved_tokens || 0;
    ledgerTotals.raw_tokens += raw;
    ledgerTotals.saved_tokens += saved;
    const kind = e.kind || 'other';
    const cur = byKind.get(kind) || { count: 0, saved_tokens: 0 };
    cur.count++;
    cur.saved_tokens += saved;
    byKind.set(kind, cur);
  }

  let requests = 0;
  let reqSavedTokens = 0;
  let reqSavedBytes = 0;
  let frostSaved = 0;
  const perModel = new Map<string, { requests: number; saved_tokens: number; saved_bytes: number }>();
  for (const h of history) {
    requests++;
    const st = h.saved_tokens || 0;
    const sb = h.saved_bytes || 0;
    const fs2 = h.frost_saved || 0;
    reqSavedTokens += st;
    reqSavedBytes += sb;
    frostSaved += fs2;
    const model = h.model || 'unknown';
    const cur = perModel.get(model) || { requests: 0, saved_tokens: 0, saved_bytes: 0 };
    cur.requests++;
    cur.saved_tokens += st;
    cur.saved_bytes += sb;
    perModel.set(model, cur);
  }

  const recent = [
    ...ledger.slice(-10).map((e) => ({
      ts: Date.parse(e.timestamp) || 0,
      kind: e.kind || 'other',
      description: e.description || '',
      saved: e.saved_tokens || 0,
      unit: 'tok',
    })),
    ...history.slice(-10).map((h) => ({
      ts: typeof h.timestamp === 'number' ? h.timestamp * 1000 : Date.parse(h.timestamp || '') || 0,
      kind: 'request',
      description: `${h.model || 'unknown'} — ${h.path || ''}`,
      saved: h.saved_tokens || h.saved_bytes || 0,
      unit: h.saved_tokens ? 'tok' : 'B',
    })),
  ]
    .sort((a, b) => b.ts - a.ts)
    .slice(0, 10)
    .map((r) => ({ ...r, ts: r.ts ? new Date(r.ts).toLocaleString() : '' }));

  return {
    ledger: ledgerTotals,
    proxy: {
      requests,
      saved_tokens: reqSavedTokens + (pcfg.total_saved_tokens || 0),
      saved_bytes: reqSavedBytes + (pcfg.total_saved_bytes || 0),
      frost_saved: frostSaved + (pcfg.frost_total_saved_tokens || 0),
    },
    perModel: [...perModel.entries()]
      .map(([model, s]) => ({ model, ...s }))
      .sort((a, b) => b.saved_tokens - a.saved_tokens),
    byKind: [...byKind.entries()]
      .map(([kind, s]) => ({ kind, ...s }))
      .sort((a, b) => b.saved_tokens - a.saved_tokens),
    recent,
  };
}

export function quotaSummary() {
  const quota = readJson(config.QUOTA_TRACKER_PATH) || {};
  const budget = readJson(config.BUDGET_PATH) || null;
  return { quota, budget };
}

export function routingSummary() {
  const pcfg = readJson<Record<string, any>>(config.PROXY_CONFIG) || {};
  const fallback = readJson<Record<string, string[]>>(config.FALLBACK_PATH) || {};
  const model = config.get_current_model();
  const chain = fallback[model] || [];
  let upstream: { pid: string; url: string } | null = null;
  try {
    upstream = resolveUpstream(model, '');
  } catch {}
  const proxied = pcfg.proxied_providers || [];
  const configured = config.get_configured_providers();
  const upstreams = pcfg.upstreams || {};
  const routing: { provider: string; proxied: boolean; configured: boolean; baseURL: string | null }[] = [];
  for (const pid of [...new Set([...configured, ...proxied, ...Object.keys(upstreams)])]) {
    routing.push({
      provider: pid,
      proxied: proxied.includes(pid),
      configured: configured.includes(pid),
      baseURL: upstreams[pid] || null,
    });
  }
  routing.sort((a, b) => a.provider.localeCompare(b.provider));

  const provider = model.split('/')[0];
  const tier = routingMod.get_tier_for_provider(provider);
  const router = new routingMod.TieredRouter();
  const tieredChain = router.build_fallback_chain(provider);
  let accounts: { id: string; provider: string; status: string; priority: number }[] = [];
  try {
    accounts = accountManager.get_summary();
  } catch {}

  return {
    currentModel: model,
    upstream,
    fallbackChain: chain,
    tier,
    tieredChain,
    accounts,
    accountStrategy: pcfg.account_strategy || 'round-robin',
    proxied,
    routing,
    upstreams,
  };
}

export function providersList() {
  const configured = new Set(config.get_configured_providers());
  const working = new Set(config.get_working_providers());
  const envDetected = new Set(config.get_providers_from_env());
  const authDetected = new Set(config.get_providers_from_auth());
  const inHistory = new Set(config.get_providers_from_model_history());
  const pcfg = readJson<Record<string, any>>(config.PROXY_CONFIG) || {};
  const upstreams = pcfg.upstreams || {};
  const proxiedProviders = pcfg.proxied_providers || [];
  const cfg = config.read_config() || {};

  const all = new Set<string>([
    ...configured,
    ...working,
    ...envDetected,
    ...authDetected,
    ...inHistory,
    ...Object.keys(upstreams),
  ]);
  const result: {
    provider: string;
    configured: boolean;
    working: boolean;
    envDetected: boolean;
    authDetected: boolean;
    inHistory: boolean;
    proxied: boolean;
    baseURL: string | null;
    envVars: string[];
  }[] = [];
  for (const pid of [...all].sort()) {
    const pdata = cfg.provider && cfg.provider[pid];
    const opts = pdata && pdata.options ? pdata.options : {};
    const baseURL = opts.baseURL || upstreams[pid] || null;
    const envVars = (config.KNOWN_PROVIDER_ENV_VARS[pid] || []).filter(
      (v) => process.env[v] && process.env[v].trim()
    );
    result.push({
      provider: pid,
      configured: configured.has(pid),
      working: working.has(pid),
      envDetected: envDetected.has(pid),
      authDetected: authDetected.has(pid),
      inHistory: inHistory.has(pid),
      proxied: proxiedProviders.includes(pid),
      baseURL,
      envVars: envVars.map((v) =>
        /KEY|TOKEN|SECRET/i.test(v) ? `${v}=•••` : `${v}=${process.env[v]}`
      ),
    });
  }
  return result;
}

export function searchQuery(q: string, limit?: number) {
  q = String(q || '').trim();
  const resultLimit = Number.isInteger(limit) && (limit as number) > 0 ? limit : 25;
  const out: Record<string, any>[] = [];
  if (!q) return out;
  const like = `%${q.replace(/[%_\\]/g, (m) => '\\' + m)}%`;
  const db = openIndexDb();

  if (db) {
    const run = (sql: string, ...params: unknown[]): SqliteRow[] => {
      try {
        return db.prepare(sql).all(...params);
      } catch {
        return [];
      }
    };
    for (const r of run(
      `select kind, description, raw_tokens, compressed_tokens, saved_tokens, compression_pct, timestamp
       from events
       where description like ? escape '\\' or kind like ? escape '\\' or metadata like ? escape '\\'
       order by timestamp desc limit ?`,
      like, like, like, resultLimit
    )) {
      out.push({ source: 'event', ...r });
    }
    for (const r of run(
      `select f.path, e.kind, e.description, e.saved_tokens, e.compression_pct, e.timestamp
       from files_touched f join events e on e.id = f.event_id
       where f.path like ? escape '\\'
       order by e.timestamp desc limit ?`,
      like, resultLimit
    )) {
      out.push({ source: 'file', ...r });
    }
    for (const r of run(
      `select path, model, saved_tokens, timestamp from proxy_requests
       where path like ? escape '\\' or model like ? escape '\\'
       order by timestamp desc limit ?`,
      like, like, resultLimit
    )) {
      out.push({ source: 'request', ...r });
    }
  }

  const ledger = readJson<Array<Record<string, any>>>(config.LEDGER_PATH) || [];
  const lower = q.toLowerCase();
  for (const e of ledger) {
    const hay = [e.description, e.kind, e.metadata && JSON.stringify(e.metadata)].join(' ');
    if (hay.toLowerCase().includes(lower)) {
      out.push({
        source: 'ledger',
        kind: e.kind,
        description: e.description,
        raw_tokens: e.raw_tokens,
        compressed_tokens: e.compressed_tokens,
        saved_tokens: e.saved_tokens,
        compression_pct: e.compression_pct,
        timestamp: e.timestamp,
      });
    }
  }

  const toMs = (t: unknown): number => {
    if (!t) return 0;
    if (typeof t === 'number') return t * 1000;
    const n = Date.parse(String(t));
    return Number.isNaN(n) ? 0 : n;
  };
  out.sort((a, b) => toMs(b.timestamp) - toMs(a.timestamp));
  return out.slice(0, resultLimit);
}

export function compressTest(text: string) {
  text = String(text || '');
  const length = text.length;
  if (length < rtk.MIN_COMPRESS_SIZE) {
    return { detected: null, tooSmall: true, min: rtk.MIN_COMPRESS_SIZE, length };
  }
  const fn = rtk.auto_detect_filter(text);
  if (!fn) {
    return { detected: null, tooSmall: false, length };
  }
  const out = rtk.safe_apply(fn, text);
  const same = !out || out.length >= length;
  return {
    detected: fn.name,
    tooSmall: false,
    length,
    compressed_length: same ? length : out.length,
    saved: same ? 0 : length - out.length,
    pct: same ? 0 : Number((((length - out.length) / length) * 100).toFixed(1)),
    compressed: same ? null : out,
  };
}

export function settingsGet() {
  const cfg = config.read_config() || {};
  return {
    path: config.CONFIG_PATH,
    model: cfg.model || '',
    small_model: cfg.small_model || '',
    current: config.get_current_model(),
    providerCount: Object.keys(cfg.provider || {}).length,
    compaction: cfg.compaction || null,
    backups: config.list_backups(),
    providers: Object.keys(cfg.provider || {}).sort(),
  };
}

export function settingsSave(opts: { model?: string; small_model?: string } = {}) {
  const { model, small_model } = opts;
  const current = settingsGet();
  const nextModel = typeof model === 'string' && model.trim() ? model.trim() : current.model;
  const nextSmall =
    typeof small_model === 'string' && small_model.trim() ? small_model.trim() : current.small_model;
  config.write_config(nextModel, nextSmall);
  return settingsGet();
}
