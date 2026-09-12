import http from 'node:http';
import https from 'node:https';
import fs from 'node:fs';
import { nowIso, readJson, writeJson } from './utils.js';
import { PROXY_CONFIG, CACHE_PATH, read_config, get_current_model, set_provider_base_urls } from './config.js';
import { readCatalogCache } from './models.js';
import * as rtk from './filters/rtk.js';
import * as routing from './routing.js';
import { QuotaTracker, parse_rate_limit_headers } from './quota.js';
import * as index from './index.js';
import type { CompressStats, ProxyConfig, ProxyStatus, RequestBody } from './types.js';

export const DEFAULT_PORT = 8199;

export const PROVIDER_BASE_URLS: Record<string, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com/v1',
  google: 'https://generativelanguage.googleapis.com/v1',
  deepseek: 'https://api.deepseek.com/v1',
  mistral: 'https://api.mistral.ai/v1',
  cohere: 'https://api.cohere.ai/v1',
  groq: 'https://api.groq.com/openai/v1',
  openrouter: 'https://openrouter.ai/api/v1',
  together: 'https://api.together.xyz/v1',
  fireworks: 'https://api.fireworks.ai/inference/v1',
  xai: 'https://api.x.ai/v1',
  perplexity: 'https://api.perplexity.ai',
  deepinfra: 'https://api.deepinfra.com/v1',
  nvidia: 'https://integrate.api.nvidia.com/v1',
  cerebras: 'https://api.cerebras.ai/public/v1',
  siliconflow: 'https://api.siliconflow.cn/v1',
  huggingface: 'https://api-inference.huggingface.co/v1',
  venice: 'https://api.venice.ai/api/v1',
  zenmux: 'https://zenmux.ai/api/v1',
  ollama: 'https://ollama.com/api',
  opencode: 'https://opencode.ai/zen/v1',
  opencode_go: 'https://opencode.ai/zen/v1',
  zai: 'https://api.z.ai/api/paas/v4',
  iflowcn: 'https://apis.iflow.cn/v1',
  anyapi: 'https://api.anyapi.ai/v1',
  llama: 'https://llama.developer.meta.com/api/v1',
  alibaba: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  glm: 'https://open.bigmodel.cn/api/paas/v4',
  minimax: 'https://api.minimax.chat/v1',
  kimi: 'https://api.moonshot.cn/v1',
  aihubmix: 'https://aihubmix.com/v1',
  vertex: 'https://us-central1-aiplatform.googleapis.com/v1',
  github: 'https://models.github.ai/inference',
  github_models: 'https://models.github.ai/inference',
  novita: 'https://api.novita.ai/v3/openai',
  sambanova: 'https://api.sambanova.ai/v1',
  replicate: 'https://api.replicate.com/v1',
  kiro: 'https://api.kiro.ai/v1',
  iflow: 'https://api.iflow.ai/v1',
  nano_gpt: 'https://nano-gpt.com/api/v1',
  claudinio: 'https://claudinio.com/api',
  nara: 'https://api.nara.ai/v1',
  llmgateway: 'https://llm-gateway.com/v1',
};

const HOP_BY_HOP = new Set([
  'host',
  'content-length',
  'connection',
  'transfer-encoding',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailers',
  'upgrade',
  'accept-encoding',
]);

const PREFER_HEADERS = new Set([
  'content-type',
  'authorization',
  'x-api-key',
  'user-agent',
  'accept',
  'anthropic-version',
  'anthropic-beta',
  'openai-organization',
  'openai-project',
  'x-title',
  'http-referer',
]);

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

let _server: http.Server | null = null;
let _port = DEFAULT_PORT;
const _metrics: {
  requestsServed: number;
  totalSavedBytes: number;
  hits: number;
  lastModel: string;
  lastAccount: string;
  startedAt: string | null;
} = {
  requestsServed: 0,
  totalSavedBytes: 0,
  hits: 0,
  lastModel: '',
  lastAccount: '',
  startedAt: null,
};

export const accountManager = new routing.AccountManager();
export const quotaTracker = new QuotaTracker();

export function loadConfig(): ProxyConfig {
  return readJson<ProxyConfig>(PROXY_CONFIG, null) || {};
}

export function saveConfig(cfg: ProxyConfig): void {
  writeJson(PROXY_CONFIG, cfg);
}

export function providerBaseUrl(pid: string): string {
  if (!pid) return '';
  const cfg = loadConfig();
  const saved = cfg.saved_base_urls?.[pid] || cfg.upstreams?.[pid];
  if (saved) return String(saved).replace(/\/+$/, '');
  if (pid === 'openai' && process.env.OPENAI_BASE_URL) {
    return String(process.env.OPENAI_BASE_URL).replace(/\/+$/, '');
  }
  return PROVIDER_BASE_URLS[pid] || '';
}

export function modelProvider(modelId: string): string {
  if (!modelId) return '';
  const m = String(modelId).trim();
  if (!m) return '';
  const first = m.split('/')[0];
  return first || '';
}

export function canonicalEndpoint(pathOnly: string): string {
  if (!pathOnly) return '';
  if (pathOnly.endsWith('/chat/completions')) return '/chat/completions';
  if (pathOnly.endsWith('/responses')) return '/responses';
  if (pathOnly.endsWith('/messages')) return '/messages';
  if (pathOnly.endsWith('/models')) return '/models';
  return pathOnly;
}

function isSelfUrl(url: string): boolean {
  const port = _port || loadConfig().port || DEFAULT_PORT;
  return new RegExp(`127\\.0\\.0\\.1:${port}|localhost:${port}`).test(url || '');
}

export function defaultUpstream(): { pid: string; base: string } {
  const cfg = loadConfig();
  const candidates: string[] = [];
  for (const pid of cfg.proxied_providers || []) candidates.push(pid);
  for (const pid of Object.keys(cfg.saved_base_urls || {})) candidates.push(pid);
  for (const pid of Object.keys(cfg.upstreams || {})) candidates.push(pid);
  for (const pid of [...new Set(candidates)]) {
    const base = providerBaseUrl(pid);
    if (base && !isSelfUrl(base)) return { pid, base };
  }
  const envBase = process.env.OPENAI_BASE_URL;
  if (envBase) return { pid: 'openai', base: String(envBase).replace(/\/+$/, '') };
  return { pid: 'openai', base: PROVIDER_BASE_URLS.openai };
}

let _modelProviderCache: Record<string, string[]> | null = null;
let _modelProviderCacheMtime = 0;

function modelToProviders(): Record<string, string[]> {
  let mtime = 0;
  try {
    mtime = fs.statSync(CACHE_PATH).mtimeMs;
  } catch {}
  if (_modelProviderCache && mtime === _modelProviderCacheMtime) return _modelProviderCache;
  const map: Record<string, string[]> = {};
  try {
    const catalog = readCatalogCache();
    if (catalog) {
      for (const [pid, pdata] of Object.entries(catalog)) {
        if (!pdata || typeof pdata !== 'object') continue;
        const models = (pdata as Record<string, any>).models || {};
        if (typeof models === 'object') {
          for (const mid of Object.keys(models)) {
            (map[mid] = map[mid] || []).push(pid);
          }
        }
      }
    }
  } catch {}
  _modelProviderCache = map;
  _modelProviderCacheMtime = mtime;
  return map;
}

export function catalogProviderForModel(modelId: string): string {
  if (!modelId) return '';
  const providers = modelToProviders()[modelId];
  if (!providers || !providers.length) return '';
  const cfg = loadConfig();
  const proxied = new Set(cfg.proxied_providers || []);
  const candidates = [...providers];
  const routed = candidates.filter((p) => {
    const base = providerBaseUrl(p);
    return base && !isSelfUrl(base) && (proxied.has(p) || (cfg.saved_base_urls?.[p] ?? cfg.upstreams?.[p]));
  });
  const pool = routed.length ? routed : candidates.filter((p) => {
    const base = providerBaseUrl(p);
    return base && !isSelfUrl(base);
  });
  if (!pool.length) return '';
  const curPid = modelProvider(get_current_model());
  if (curPid && pool.includes(curPid)) return curPid;
  return pool[0];
}

export function resolveUpstream(modelId: string, pathOnly: string): { pid: string; url: string } {
  const pid = modelProvider(modelId);
  const base = pid ? providerBaseUrl(pid) : '';
  if (base && !isSelfUrl(base)) return { pid, url: base + canonicalEndpoint(pathOnly) };
  if (pid && !base) {
    const catalogPid = catalogProviderForModel(modelId);
    const catBase = catalogPid ? providerBaseUrl(catalogPid) : '';
    if (catalogPid && catBase && !isSelfUrl(catBase)) {
      return { pid: catalogPid, url: catBase + canonicalEndpoint(pathOnly) };
    }
  }
  const def = defaultUpstream();
  return { pid: def.pid, url: def.base + canonicalEndpoint(pathOnly) };
}

function pickHeaders(headers: http.IncomingHttpHeaders): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(headers)) {
    if (!v) continue;
    const lk = k.toLowerCase();
    if (HOP_BY_HOP.has(lk)) continue;
    if (PREFER_HEADERS.has(lk) || lk.startsWith('x-')) out[k] = Array.isArray(v) ? v.join(', ') : String(v);
  }
  if (!out['Content-Type']) out['Content-Type'] = 'application/json';
  if (!out['User-Agent']) out['User-Agent'] = UA;
  if (!out['Accept']) out['Accept'] = 'text/event-stream, application/json';
  return out;
}

function respondJson(res: http.ServerResponse, code: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  res.writeHead(code, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function readBody(req: http.IncomingMessage, cb: (err: Error | null, body?: string) => void): void {
  const chunks: Buffer[] = [];
  req.on('data', (c: Buffer) => chunks.push(c));
  req.on('end', () => cb(null, Buffer.concat(chunks).toString('utf-8')));
  req.on('error', (e: Error) => cb(e));
}

function streamBack(upRes: http.IncomingMessage, res: http.ServerResponse): void {
  const ct = upRes.headers['content-type'] || 'application/json';
  const headers: Record<string, string> = { 'Content-Type': String(ct) };
  if (/text\/event-stream/i.test(String(ct))) {
    headers['Cache-Control'] = 'no-cache';
    headers['X-Accel-Buffering'] = 'no';
  }
  res.writeHead(upRes.statusCode || 200, headers);
  upRes.pipe(res);
}

interface RecordStats {
  bytesBefore: number;
  bytesAfter: number;
}

function recordHistory(
  pathOnly: string,
  modelId: string,
  stats: CompressStats | null,
  upstreamUrl: string,
  rawBody: string,
  outBody: string
): void {
  try {
    const cfg = loadConfig();
    const rawBytes = Buffer.byteLength(rawBody || '');
    const outBytes = Buffer.byteLength(outBody || '');
    const rawTokens = rawBytes >> 2;
    const savedTokens = Math.max(0, rawTokens - (outBytes >> 2));
    const saved = stats ? Math.max(0, stats.bytesBefore - stats.bytesAfter) : 0;
    const history = cfg.history || [];
    history.push({
      path: pathOnly,
      model: modelId || 'unknown',
      saved_tokens: savedTokens,
      frost_saved: 0,
      saved_bytes: saved,
      upstream: upstreamUrl,
      timestamp: Math.floor(Date.now() / 1000),
      ts_iso: nowIso(),
    });
    saveConfig({
      ...cfg,
      history: history.slice(-200),
      total_saved_bytes: (Number(cfg.total_saved_bytes) || 0) + saved,
      total_saved_tokens: (Number(cfg.total_saved_tokens) || 0) + savedTokens,
    });
    index.logProxyRequest(pathOnly, modelId || 'unknown', rawTokens, savedTokens);
  } catch {}
}

function forward(
  req: http.IncomingMessage,
  res: http.ServerResponse,
  upstreamUrl: string,
  outBody: string,
  rawBody: string,
  pathOnly: string,
  modelId: string,
  stats: CompressStats | null,
  account: routing.Account | null
): void {
  const u = new URL(upstreamUrl);
  const transport = u.protocol === 'https:' ? https : http;

  function pick(): Record<string, string> {
    const headers = pickHeaders(req.headers);
    if (account && account.api_key) headers['Authorization'] = `Bearer ${account.api_key}`;
    return headers;
  }

  function finish(statusCode: number, upRes: http.IncomingMessage | null): void {
    const provider = modelProvider(modelId);
    try {
      if (statusCode >= 400) {
        const cooldown = routing.check_fallback_error(statusCode, '').cooldown_ms;
        quotaTracker.mark_rate_limited(provider, modelId, cooldown, account && account.id);
      } else {
        const parsed = parse_rate_limit_headers((upRes && upRes.headers) || null);
        if (parsed) {
          quotaTracker.update_quota(provider, modelId, {
            total: parsed.total,
            used: parsed.used,
            remaining: parsed.remaining,
            reset_at: parsed.reset_at,
            account_id: account && account.id,
          });
        }
        quotaTracker.log_request(provider, modelId, 0, 0, 0, account && account.id);
      }
    } catch {}
    if (!account) return;
    try {
      if (statusCode >= 400) accountManager.mark_error(account.id, statusCode, '');
      else accountManager.mark_success(account.id);
    } catch {}
  }

  function send(body: string): void {
    const headers = pick();
    headers['Content-Length'] = String(Buffer.byteLength(body));
    const upReq = transport.request(
      u,
      { method: 'POST', headers },
      (upRes) => {
        if (upRes.statusCode === 400 && body !== rawBody) {
          upRes.resume();
          const retryReq = transport.request(
            u,
            { method: 'POST', headers: { ...pick(), 'Content-Length': String(Buffer.byteLength(rawBody)) } },
            (res2) => {
              streamBack(res2, res);
              recordHistory(pathOnly, modelId, stats, upstreamUrl, rawBody, outBody);
              finish(res2.statusCode || 0, res2);
            }
          );
          retryReq.on('error', () => {
            try {
              respondJson(res, 502, {
                error: { message: 'Proxy upstream failed', type: 'proxy_error', code: 'upstream_failed', upstream: upstreamUrl },
              });
            } catch {}
          });
          retryReq.write(rawBody);
          retryReq.end();
          return;
        }
        streamBack(upRes, res);
        recordHistory(pathOnly, modelId, stats, upstreamUrl, rawBody, outBody);
        finish(upRes.statusCode || 0, upRes);
      }
    );
    upReq.on('error', () => {
      finish(0, null);
      try {
        respondJson(res, 502, {
          error: { message: 'Proxy upstream failed', type: 'proxy_error', code: 'upstream_failed', upstream: upstreamUrl },
        });
      } catch {}
    });
    upReq.write(body);
    upReq.end();
  }

  send(outBody);
}

function forwardGet(req: http.IncomingMessage, res: http.ServerResponse, pathOnly: string): void {
  const def = defaultUpstream();
  const url = def.base + canonicalEndpoint(pathOnly);
  const u = new URL(url);
  const transport = u.protocol === 'https:' ? https : http;
  const upReq = transport.request(u, { method: 'GET', headers: pickHeaders(req.headers) }, (upRes) =>
    streamBack(upRes, res)
  );
  upReq.on('error', () => {
    try {
      respondJson(res, 502, {
        error: { message: 'Proxy upstream failed', type: 'proxy_error', code: 'upstream_failed', upstream: url },
      });
    } catch {}
  });
  upReq.end();
}

function handleRequest(req: http.IncomingMessage, res: http.ServerResponse): void {
  const pathOnly = (req.url || '').split('?')[0];

  if (req.method === 'GET' && (pathOnly === '/health' || pathOnly === '/status')) {
    return respondJson(res, 200, status());
  }
  if (req.method === 'GET' && pathOnly.endsWith('/models')) {
    return forwardGet(req, res, pathOnly);
  }
  if (req.method !== 'POST') {
    return respondJson(res, 405, {
      error: { message: 'method not allowed', type: 'proxy_error', code: 'method_not_allowed' },
    });
  }

  readBody(req, (err, raw) => {
    if (err || raw === undefined) {
      return respondJson(res, 400, {
        error: { message: err ? err.message : 'no body', type: 'proxy_error', code: 'bad_request' },
      });
    }

    let data: RequestBody | null = null;
    try {
      data = JSON.parse(raw);
    } catch {}

    const modelId = (data && (data.model || '')) || '';
    if (data && typeof data.model === 'string' && data.model.includes('/')) {
      const prefix = data.model.split('/', 1)[0];
      if (prefix && (providerBaseUrl(prefix) || prefix === 'opencode' || prefix === 'opencode_go' || prefix === 'opencode-go')) {
        data.model = data.model.slice(prefix.length + 1);
      }
    }
    const resolved = resolveUpstream(modelId, pathOnly);
    let upstreamUrl = resolved.url;
    if (!upstreamUrl) {
      return respondJson(res, 502, {
        error: {
          message: `Proxy has no upstream URL configured for path ${pathOnly} (model '${modelId}')`,
          type: 'proxy_error',
          code: 'no_upstream',
        },
      });
    }

    let account: routing.Account | null = null;
    try {
      const provider = modelProvider(modelId);
      const strategy = loadConfig().account_strategy || 'round-robin';
      account = accountManager.select_account(provider, strategy, 1, modelId);
      if (account && account.base_url) {
        upstreamUrl = String(account.base_url).replace(/\/+$/, '') + canonicalEndpoint(pathOnly);
      }
    } catch {}

    _metrics.requestsServed += 1;
    _metrics.lastModel = modelId || 'unknown';
    if (account) _metrics.lastAccount = account.id;

    let outBody = raw;
    let stats: CompressStats | null = null;
    if (data) {
      const compressed = rtk.compress_messages(data, true);
      if (compressed) {
        const serialized = JSON.stringify(data);
        if (serialized.length < raw.length) {
          outBody = serialized;
          stats = compressed;
          const log = rtk.format_rtk_log(stats);
          if (log) console.log(log);
          _metrics.hits += 1;
          _metrics.totalSavedBytes += Math.max(0, stats.bytesBefore - stats.bytesAfter);
        }
      }
    }

    forward(req, res, upstreamUrl, outBody, raw, pathOnly, modelId, stats, account);
  });
}

export function status(): ProxyStatus {
  const cfg = loadConfig();
  let actualPort = _port;
  try {
    if (_server && _server.address()) actualPort = Number((_server.address() as any).port);
  } catch {}
  return {
    running: !!_server,
    port: actualPort,
    enabled: !!cfg.enabled,
    requestsServed: _metrics.requestsServed,
    totalSavedBytes: _metrics.totalSavedBytes,
    compressionHits: _metrics.hits,
    lastModel: _metrics.lastModel,
    lastAccount: _metrics.lastAccount,
    startedAt: _metrics.startedAt,
    proxiedProviders: cfg.proxied_providers || [],
    upstreams: cfg.upstreams || {},
  };
}

function _httpGet(urlStr: string, timeoutMs: number): Promise<{ ok: boolean; code: number; error?: string; body?: string }> {
  return new Promise((resolve) => {
    let u: URL;
    try {
      u = new URL(urlStr);
    } catch {
      return resolve({ ok: false, code: 0, error: 'invalid url' });
    }
    const transport = u.protocol === 'https:' ? https : http;
    const req = transport.request(
      u,
      { method: 'GET', headers: { Accept: 'application/json' } },
      (res) => {
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk: string) => {
          body += chunk;
          if (body.length > 20000) req.destroy();
        });
        res.on('end', () =>
          resolve({ ok: res.statusCode !== undefined && res.statusCode >= 200 && res.statusCode < 600, code: res.statusCode || 0, body })
        );
      }
    );
    req.on('error', (e) => resolve({ ok: false, code: 0, error: e.message }));
    req.setTimeout(timeoutMs, () => req.destroy(new Error('timeout')));
    req.end();
  });
}

export interface ProxyTestResult {
  running: boolean;
  port?: number;
  health?: { ok: boolean; code: number; error?: string };
  forward?: Record<string, any> | null;
}

export async function testConnection(): Promise<ProxyTestResult> {
  if (!_server) return { running: false };
  const port = (_server.address() && (_server.address() as any).port) || _port;
  const base = `http://127.0.0.1:${port}`;
  const health = await _httpGet(`${base}/health`, 4000);
  let forward: Record<string, any> | null = null;
  if (health.code === 200) {
    const def = defaultUpstream();
    forward = await _httpGet(`${base}/v1/models`, 10000);
    forward.upstream = def ? `${def.pid} -> ${def.base}` : null;
  }
  return {
    running: true,
    port,
    health: { ok: health.code === 200, code: health.code, error: health.error },
    forward,
  };
}

export interface ProxifyResult {
  added: string[];
  already: string[];
  skipped: string[];
  rewritten: string[];
}

export function ensureProxiedProviders(port?: number, rewriteConfig = false): ProxifyResult {
  const cfg = loadConfig();
  const targetPort = port !== undefined && port !== null ? port : cfg.port || DEFAULT_PORT;
  const proxyUrl = `http://127.0.0.1:${targetPort}/v1`;

  const set = new Set<string>();
  for (const pid of cfg.proxied_providers || []) set.add(pid);
  for (const pid of Object.keys(cfg.saved_base_urls || {})) set.add(pid);
  for (const pid of Object.keys(cfg.upstreams || {})) set.add(pid);
  const opencfg = read_config();
  if (opencfg && typeof opencfg.provider === 'object') {
    for (const pid of Object.keys(opencfg.provider)) set.add(pid);
  }
  const curPid = modelProvider(get_current_model());
  if (curPid) set.add(curPid);

  const added: string[] = [];
  const already: string[] = [];
  const skipped: string[] = [];
  for (const pid of [...set].sort()) {
    if (cfg.saved_base_urls?.[pid] || cfg.upstreams?.[pid]) {
      already.push(pid);
      continue;
    }
    let base = opencfg && opencfg.provider?.[pid]
      ? String((opencfg.provider[pid].options || {}).baseURL || '').replace(/\/+$/, '')
      : '';
    if (base && /127\.0\.0\.1:\d+|localhost:\d+/.test(base)) {
      already.push(pid);
      continue;
    }
    if (!base) base = PROVIDER_BASE_URLS[pid] || '';
    if (!base) {
      skipped.push(pid);
      continue;
    }
    cfg.saved_base_urls = cfg.saved_base_urls || {};
    cfg.upstreams = cfg.upstreams || {};
    cfg.saved_base_urls[pid] = base;
    cfg.upstreams[pid] = base;
    if (!cfg.proxied_providers) cfg.proxied_providers = [];
    if (!cfg.proxied_providers.includes(pid)) cfg.proxied_providers.push(pid);
    added.push(pid);
  }
  if (added.length || already.length) {
    cfg.proxied_providers = [...new Set(cfg.proxied_providers || [])].sort();
    try {
      saveConfig(cfg);
    } catch {}
  }

  const rewritten: string[] = [];
  if (rewriteConfig) {
    try {
      rewritten.push(...set_provider_base_urls(proxyUrl, [...added, ...already]));
    } catch {}
  }
  return { added, already, skipped, rewritten };
}

export function start(port?: number): Promise<ProxyStatus> {
  return new Promise((resolve, reject) => {
    if (_server) return resolve(status());
    const targetPort = port !== undefined && port !== null ? port : loadConfig().port || DEFAULT_PORT;
    const proxify = ensureProxiedProviders(targetPort, true);
    if (proxify.rewritten.length) {
      console.log(`[proxy] routed through proxy: ${proxify.rewritten.join(', ')} (restart opencode if running)`);
    }
    const server = http.createServer(handleRequest);
    server.on('error', (e) => {
      _server = null;
      reject(e);
    });
    server.listen(targetPort, '127.0.0.1', () => {
      _server = server;
      _port = (server.address() as any).port as number;
      _metrics.startedAt = nowIso();
      console.log(`[proxy] listening on http://127.0.0.1:${_port}`);
      resolve(status());
    });
  });
}

export function stop(): Promise<ProxyStatus> {
  return new Promise((resolve) => {
    if (!_server) return resolve(status());
    const server = _server;
    server.close(() => {
      if (_server === server) _server = null;
      resolve(status());
    });
  });
}

export function enable(enabled: boolean, port?: number): ProxyConfig {
  const cfg = loadConfig();
  cfg.enabled = !!enabled;
  if (port) cfg.port = Number(port);
  saveConfig(cfg);
  return cfg;
}
