import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { sha256Hex, md5Hex, nowIso, ensureDir, readJson, writeJson } from './utils.js';

export const TS_VERSION = '10.0.0';

const BASE_HOME = process.env.TOKENSAVER_HOME || os.homedir();

export const CONFIG_PATH = path.join(BASE_HOME, '.config', 'opencode', 'opencode.jsonc');
export const BACKUP_DIR = path.join(BASE_HOME, '.config', 'opencode');
export const CACHE_PATH = path.join(BASE_HOME, '.config', 'opencode', 'models_cache.json');
export const SNAPSHOT_PATH = path.join(BASE_HOME, '.config', 'opencode', 'models_snapshot.json');
export const CACHE_TTL = 86400;
export const MAX_BACKUPS = 5;

export const COMPRESS_DIR = path.join(BASE_HOME, '.config', 'opencode', 'compress');
export const CONTENT_CACHE = path.join(COMPRESS_DIR, 'cache');
export const CONTENT_STORE = path.join(COMPRESS_DIR, 'store');
export const LEDGER_PATH = path.join(COMPRESS_DIR, 'savings_ledger.json');
export const BUDGET_PATH = path.join(COMPRESS_DIR, 'budget.json');
export const PROXY_CONFIG = path.join(COMPRESS_DIR, 'proxy.json');
export const FALLBACK_PATH = path.join(COMPRESS_DIR, 'fallback.json');
export const DASHBOARD_CONFIG = path.join(COMPRESS_DIR, 'dashboard.json');
export const QUOTA_TRACKER_PATH = path.join(COMPRESS_DIR, 'quota_tracker.json');
export const ACCOUNTS_PATH = path.join(COMPRESS_DIR, 'accounts.json');
export const COST_PRICING_PATH = path.join(COMPRESS_DIR, 'proxy_pricing.json');
export const SAVER_POLICY_PATH = path.join(COMPRESS_DIR, 'saver_policy.json');
export const INDEX_DB_PATH = path.join(COMPRESS_DIR, 'index.db');

ensureDir(COMPRESS_DIR);
ensureDir(CONTENT_CACHE);
ensureDir(CONTENT_STORE);

export const KNOWN_PROVIDER_ENV_VARS: Record<string, string[]> = {
  openai: ['OPENAI_API_KEY', 'OPENAI_ORG_ID', 'OPENAI_BASE_URL'],
  anthropic: ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'],
  google: ['GOOGLE_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_GENAI_API_KEY'],
  vertex: ['VERTEX_CREDENTIALS', 'VERTEX_PROJECT_ID', 'GOOGLE_APPLICATION_CREDENTIALS'],
  aws: ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'],
  azure: ['AZURE_API_KEY', 'AZURE_OPENAI_API_KEY', 'AZURE_API_BASE'],
  cohere: ['COHERE_API_KEY'],
  mistral: ['MISTRAL_API_KEY'],
  groq: ['GROQ_API_KEY'],
  together: ['TOGETHER_API_KEY'],
  deepseek: ['DEEPSEEK_API_KEY'],
  openrouter: ['OPENROUTER_API_KEY'],
  fireworks: ['FIREWORKS_API_KEY'],
  perplexity: ['PERPLEXITY_API_KEY'],
  replicate: ['REPLICATE_API_TOKEN', 'REPLICATE_API_KEY'],
  huggingface: ['HUGGINGFACE_API_KEY', 'HUGGINGFACE_TOKEN', 'HF_API_KEY'],
  xai: ['XAI_API_KEY'],
  github: ['GITHUB_TOKEN', 'GITHUB_API_KEY'],
  github_models: ['GITHUB_TOKEN'],
  claudinio: ['CLAUDINIO_API_KEY'],
  qwen: ['QWEN_API_KEY', 'DASHSCOPE_API_KEY'],
  siliconflow: ['SILICONFLOW_API_KEY'],
  deepinfra: ['DEEPINFRA_API_KEY'],
  novita: ['NOVITA_API_KEY'],
  sambanova: ['SAMBANOVA_API_KEY'],
  nvidia: ['NVIDIA_API_KEY', 'NVIDIA_NIM_API_KEY'],
  zenmux: ['ZENMUX_API_KEY'],
  nara: ['NARA_API_KEY'],
  venice: ['VENICE_API_KEY'],
  llmgateway: ['LLMGATEWAY_API_KEY', 'LLM_GATEWAY_API_KEY'],
  zai: ['ZAI_API_KEY'],
  nano_gpt: ['NANO_GPT_API_KEY', 'NANOGPT_API_KEY'],
  opencode: ['OPENCODE_ZEN_API_KEY', 'OPENCODE_API_KEY'],
};

const API_KEY_ENV_PATTERNS: [RegExp, (name: string) => string][] = [
  [/_(?:API_)?KEY$/, (name) => name.replace(/_API_KEY$/, '').replace(/_KEY$/, '').toLowerCase()],
  [/_(?:API_)?AUTH_TOKEN$/, (name) => name.replace(/_AUTH_TOKEN$/, '').toLowerCase()],
  [/_(?:API_)?API_TOKEN$/, (name) => name.replace(/_API_TOKEN$/, '').toLowerCase()],
  [/_(?:API_)?TOKEN$/, (name) => name.replace(/_TOKEN$/, '').toLowerCase()],
];

export function get_providers_from_env(): string[] {
  const detected = new Set<string>();
  for (const [providerId, envVars] of Object.entries(KNOWN_PROVIDER_ENV_VARS)) {
    for (const v of envVars) {
      const val = process.env[v] || '';
      if (val && val.trim().length > 0) {
        detected.add(providerId);
        break;
      }
    }
  }
  for (const [key, val] of Object.entries(process.env)) {
    if (!val || !val.trim()) continue;
    const upper = key.toUpperCase();
    for (const [pattern, extract] of API_KEY_ENV_PATTERNS) {
      if (pattern.test(upper)) {
        const provider = extract(key);
        if (['', 'api', 'secret', 'key', 'auth', 'token', 'bearer'].includes(provider)) continue;
        detected.add(provider);
        break;
      }
    }
  }
  return [...detected].sort();
}

export function modelHistoryPaths(): string[] {
  return [
    path.join(BASE_HOME, '.config', 'opencode', 'state', 'opencode', 'model.json'),
    path.join(BASE_HOME, '.local', 'state', 'opencode', 'model.json'),
  ];
}

export function get_providers_from_model_history(): string[] {
  const providers = new Set<string>();
  for (const p of modelHistoryPaths()) {
    if (!fs.existsSync(p)) continue;
    try {
      const data = JSON.parse(fs.readFileSync(p, 'utf-8'));
      for (const entry of data.recent || []) {
        const pid = entry.providerID || '';
        if (pid) providers.add(pid);
      }
      for (const entry of data.favorite || []) {
        const pid = entry.providerID || '';
        if (pid) providers.add(pid);
      }
      for (const key of Object.keys(data.variant || {})) {
        if (key.includes('/')) {
          const pid = key.split('/')[0];
          if (pid) providers.add(pid);
        }
      }
    } catch {}
  }
  return [...providers].sort();
}

export function get_providers_from_auth(): string[] {
  const detected = new Set<string>();
  const paths = [
    path.join(BASE_HOME, '.local', 'share', 'opencode', 'auth.json'),
    path.join(BASE_HOME, '.config', 'opencode', 'auth.json'),
  ];
  for (const p of paths) {
    if (!fs.existsSync(p)) continue;
    try {
      const data = JSON.parse(fs.readFileSync(p, 'utf-8'));
      if (!data || typeof data !== 'object') continue;
      for (const [pid, entry] of Object.entries(data)) {
        const e = entry as Record<string, unknown>;
        if (!e || typeof e !== 'object') continue;
        if (e.type === 'api' && e.key) detected.add(pid);
        else if (['oauth', 'refresh'].includes(String(e.type)) && e.refresh) detected.add(pid);
      }
    } catch {}
  }
  return [...detected].sort();
}

export function get_current_model(): string {
  for (const p of modelHistoryPaths()) {
    if (!fs.existsSync(p)) continue;
    try {
      const data = JSON.parse(fs.readFileSync(p, 'utf-8'));
      const recent = data.recent || [];
      if (recent.length && typeof recent[0] === 'object') {
        const pid = recent[0].providerID || '';
        const mid = recent[0].modelID || '';
        if (pid && mid) return `${pid}/${mid}`;
      }
    } catch {}
  }
  const cfg = read_config() || {};
  return cfg.model || cfg.small_model || '';
}

export function strip_jsonc(text: string): string {
  const lines = text.split(/\r?\n/).map((line) => line.replace(/^\s*\/\/.*/, ''));
  const joined = lines.join('\n');
  return joined.replace(/\/\*[\s\S]*?\*\//g, '');
}

export function read_config(): Record<string, any> | null {
  if (!fs.existsSync(CONFIG_PATH)) return null;
  let raw: string;
  try {
    raw = fs.readFileSync(CONFIG_PATH, 'utf-8');
  } catch {
    return null;
  }
  if (raw.charCodeAt(0) === 0xfeff) raw = raw.slice(1);
  const clean = strip_jsonc(raw);
  try {
    return JSON.parse(clean) as Record<string, any>;
  } catch {
    return null;
  }
}

function _sync_model_state(modelId: string, smallId: string): void {
  const statePath = path.join(BASE_HOME, '.local', 'state', 'opencode', 'model.json');
  if (!fs.existsSync(statePath)) return;
  try {
    const data = JSON.parse(fs.readFileSync(statePath, 'utf-8'));
    const newEntry = modelId.includes('/')
      ? { providerID: modelId.split('/', 1)[0], modelID: modelId.split('/', 1)[1] }
      : { providerID: 'opencode', modelID: modelId };
    let recent = data.recent || [];
    recent = recent.filter(
      (e: any) => !(e.providerID === newEntry.providerID && e.modelID === newEntry.modelID)
    );
    recent.unshift(newEntry);
    data.recent = recent.slice(0, 20);
    fs.writeFileSync(statePath, JSON.stringify(data, null, 2), 'utf-8');
  } catch {}
}

export function rotate_backup(): void {
  if (!fs.existsSync(CONFIG_PATH)) return;
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  const ts = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const backup = path.join(BACKUP_DIR, `opencode.jsonc.${ts}.backup`);
  fs.copyFileSync(CONFIG_PATH, backup);
  const old = fs
    .readdirSync(BACKUP_DIR)
    .filter((n) => /^opencode\.jsonc\..*\.backup$/.test(n))
    .sort()
    .reverse();
  for (const f of old.slice(MAX_BACKUPS)) {
    try {
      fs.unlinkSync(path.join(BACKUP_DIR, f));
    } catch {}
  }
}

export function write_config(modelId: string, smallId: string): void {
  const existing = read_config() || {};
  const con: Record<string, any> = {
    model: modelId,
    small_model: smallId,
    compaction: { auto: true, prune: true, reserved: 10000 },
  };
  con.provider = existing.provider || {};
  for (const pid of Object.keys(con.provider)) {
    if (typeof con.provider[pid] === 'object' && con.provider[pid] !== null) {
      const opts = con.provider[pid].options || {};
      if (opts.timeout === undefined) opts.timeout = 300000;
      if (opts.chunkTimeout === undefined) opts.chunkTimeout = 60000;
      con.provider[pid].options = opts;
    }
  }
  fs.mkdirSync(path.dirname(CONFIG_PATH), { recursive: true });
  if (fs.existsSync(CONFIG_PATH)) rotate_backup();
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(con, null, 2) + '\n', 'utf-8');
  _sync_model_state(modelId, smallId);
}

export function list_backups(): [string, string][] {
  const result: [string, string][] = [];
  const files = fs
    .readdirSync(BACKUP_DIR)
    .filter((n) => /^opencode\.jsonc\..*\.backup$/.test(n))
    .sort()
    .reverse();
  for (const name of files) {
    const parts = name.split('.');
    if (parts.length >= 3) {
      const ts = parts[2];
      let label = ts;
      try {
        const m = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(ts);
        if (m) {
          const d = new Date(
            Number(m[1]),
            Number(m[2]) - 1,
            Number(m[3]),
            Number(m[4]),
            Number(m[5]),
            Number(m[6])
          );
          label = d.toLocaleString('en-US', { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
        }
      } catch {}
      result.push([label, path.join(BACKUP_DIR, name)]);
    }
  }
  return result;
}

export function get_configured_providers(): string[] {
  const configured = new Set<string>();
  const cfg = read_config();
  if (cfg && cfg.provider) {
    Object.keys(cfg.provider).forEach((k) => configured.add(k));
  }
  get_providers_from_env().forEach((k) => configured.add(k));
  get_providers_from_model_history().forEach((k) => configured.add(k));
  get_providers_from_catalog_crossref().forEach((k) => configured.add(k));
  return [...configured].sort();
}

export function get_working_providers(): string[] {
  const working = new Set<string>();
  const cfg = read_config();
  if (cfg && typeof cfg.provider === 'object') {
    for (const [pid, pdata] of Object.entries(cfg.provider)) {
      if (typeof pdata === 'object' && pdata !== null) {
        const opts = (pdata as Record<string, any>).options || {};
        if (opts.baseURL) working.add(pid);
      }
    }
  }
  get_providers_from_env().forEach((k) => working.add(k));
  return [...working].sort();
}

export function get_config_provider_base_url(pid: string): string {
  const cfg = read_config();
  const p = cfg && cfg.provider ? cfg.provider[pid] : undefined;
  if (typeof p === 'object' && p !== null) {
    const opts = (p as Record<string, any>).options || {};
    return String(opts.baseURL || '').replace(/\/+$/, '');
  }
  return '';
}

export function set_provider_base_urls(proxyUrl: string, providers: string[]): string[] {
  const cfg = read_config();
  if (!cfg) return [];
  const changed: string[] = [];
  for (const pid of providers) {
    if (!cfg.provider || typeof cfg.provider[pid] !== 'object' || cfg.provider[pid] === null) continue;
    const cur = get_config_provider_base_url(pid);
    if (cur && /127\.0\.0\.1:\d+|localhost:\d+/.test(cur)) continue;
    const opts = cfg.provider[pid].options || {};
    opts.baseURL = proxyUrl;
    cfg.provider[pid].options = opts;
    changed.push(pid);
  }
  if (!changed.length) return changed;
  try {
    if (fs.existsSync(CONFIG_PATH)) rotate_backup();
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2) + '\n', 'utf-8');
  } catch {
    return [];
  }
  return changed;
}

export function get_providers_from_catalog_crossref(): string[] {
  const detected = new Set<string>();
  let catalog: Record<string, any> | null = null;
  if (fs.existsSync(CACHE_PATH)) {
    try {
      catalog = JSON.parse(fs.readFileSync(CACHE_PATH, 'utf-8'));
    } catch {}
  }
  if (!catalog) return [];
  const catalogProviderIds = Object.keys(catalog);
  const envApikeys: Record<string, string> = {};
  for (const [key, val] of Object.entries(process.env)) {
    if (!val || !val.trim()) continue;
    const upper = key.toUpperCase();
    for (const suffix of ['_API_KEY', '_AUTH_TOKEN', '_API_TOKEN', '_TOKEN', '_API_SECRET', '_SECRET_KEY', '_ACCESS_KEY', '_API', '_BASE_URL', '_ENDPOINT', '_KEY']) {
      if (upper.endsWith(suffix)) {
        envApikeys[key] = key.replace(suffix, '').toLowerCase().replace(/-/g, '_').replace(/ /g, '_');
        break;
      }
    }
    if (upper.includes('API') && (upper.includes('KEY') || upper.includes('TOKEN') || upper.includes('SECRET'))) {
      const generic = new Set(['api', 'key', 'token', 'secret', 'auth', 'bearer', 'access', 'endpoint', 'base', 'url', 'org', 'id', 'application', 'credentials', 'service', 'account']);
      const meaningful = key.toLowerCase().split('_').filter((p) => !generic.has(p) && p.length > 1);
      for (const potential of meaningful) envApikeys[`${key}::${potential}`] = potential;
    }
  }
  for (const [varName, extractedName] of Object.entries(envApikeys)) {
    void varName;
    if (catalogProviderIds.includes(extractedName)) detected.add(extractedName);
    const clean = extractedName.replace(/_/g, '');
    for (const cpid of catalogProviderIds) {
      if (clean === cpid.replace(/_/g, '').replace(/-/g, '')) {
        detected.add(cpid);
        break;
      }
    }
    for (const [cpid, pdata] of Object.entries(catalog)) {
      if (!pdata || typeof pdata !== 'object') continue;
      const pname = ((pdata.name || '') + '').toLowerCase().replace(/ /g, '_').replace(/-/g, '_');
      if (extractedName.includes(pname) || pname.includes(extractedName)) {
        detected.add(cpid);
        break;
      }
    }
  }
  const historyPath = path.join(BASE_HOME, '.config', 'opencode', 'state', 'opencode', 'prompt-history.jsonl');
  const altHist = path.join(BASE_HOME, '.local', 'state', 'opencode', 'prompt-history.jsonl');
  for (const hpath of [historyPath, altHist]) {
    if (fs.existsSync(hpath)) {
      try {
        const text = fs.readFileSync(hpath, 'utf-8');
        for (const cpid of catalogProviderIds) {
          if (text.toLowerCase().includes(cpid.toLowerCase())) detected.add(cpid);
        }
      } catch {}
    }
  }
  return [...detected].sort();
}

export { sha256Hex, md5Hex, nowIso, readJson, writeJson };
