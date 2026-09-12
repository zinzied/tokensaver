import fs from 'node:fs';
import path from 'node:path';
import * as config from './config.js';
import type {
  ProviderCatalog,
  ProviderGroup,
  ModelInfo,
  CatalogFetchResult,
  NewModelInfo,
  SaverPolicy,
  ChosenSaverModels,
} from './types.js';

interface CatalogProviderData {
  name?: string;
  models?: Record<string, any>;
}

export type CatalogData = Record<string, CatalogProviderData>;

export const TASK_TEMPLATES: Record<string, { tag: string; desc: string; weight: number }[]> = {
  coding: [
    { tag: 'strong', desc: 'Best quality, higher cost', weight: -1 },
    { tag: 'balanced', desc: 'Good quality, moderate cost', weight: 0 },
  ],
  review: [
    { tag: 'cheap', desc: 'Fast & cheap, good for diffs', weight: 0 },
    { tag: 'balanced', desc: 'Balanced quality/speed', weight: 1 },
  ],
  planning: [
    { tag: 'balanced', desc: 'Good reasoning, moderate cost', weight: 0 },
    { tag: 'strong', desc: 'Best reasoning, higher cost', weight: 1 },
  ],
};

function cacheAgeMs(filePath: string): number {
  try {
    return Date.now() - fs.statSync(filePath).mtimeMs;
  } catch {
    return Infinity;
  }
}

export async function fetchCatalog(): Promise<CatalogFetchResult> {
  if (fs.existsSync(config.CACHE_PATH)) {
    const ageMs = cacheAgeMs(config.CACHE_PATH);
    if (ageMs < config.CACHE_TTL * 1000) {
      try {
        return { catalog: JSON.parse(fs.readFileSync(config.CACHE_PATH, 'utf-8')), newModels: [], source: 'cache' };
      } catch {}
    }
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    const resp = await fetch('https://models.dev/api.json', { signal: controller.signal });
    clearTimeout(timer);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = (await resp.json()) as CatalogData;
    fs.writeFileSync(config.CACHE_PATH, JSON.stringify(data), 'utf-8');
    const oldSnap = loadSnapshot();
    const newModels = oldSnap ? diffNewModels(oldSnap, data) : [];
    saveSnapshot(data);
    return { catalog: data, newModels, source: 'network' };
  } catch (e) {
    if (fs.existsSync(config.CACHE_PATH)) {
      try {
        return { catalog: JSON.parse(fs.readFileSync(config.CACHE_PATH, 'utf-8')), newModels: [], source: 'cache' };
      } catch {}
    }
    return { catalog: null, newModels: [], source: 'error', error: String((e as Error).message || e) };
  }
}

export function buildSnapshot(catalog: CatalogData | null): Record<string, string[]> {
  const snap: Record<string, string[]> = {};
  if (!catalog || typeof catalog !== 'object') return snap;
  for (const [providerId, pdata] of Object.entries(catalog)) {
    if (!pdata || typeof pdata !== 'object' || !pdata.models) continue;
    const mids = Object.keys(pdata.models).sort();
    if (mids.length) snap[providerId] = mids;
  }
  return snap;
}

export function loadSnapshot(): Record<string, string[]> | null {
  if (!fs.existsSync(config.SNAPSHOT_PATH)) return null;
  try {
    return JSON.parse(fs.readFileSync(config.SNAPSHOT_PATH, 'utf-8'));
  } catch {
    return null;
  }
}

export function saveSnapshot(catalog: CatalogData | null): void {
  fs.writeFileSync(config.SNAPSHOT_PATH, JSON.stringify(buildSnapshot(catalog)), 'utf-8');
}

export function diffNewModels(oldSnap: Record<string, string[]>, catalog: CatalogData | null): NewModelInfo[] {
  const newModels: NewModelInfo[] = [];
  if (!catalog || typeof catalog !== 'object') return newModels;
  for (const [providerId, pdata] of Object.entries(catalog)) {
    if (!pdata || typeof pdata !== 'object' || !pdata.models) continue;
    const cur = new Set(Object.keys(pdata.models));
    const prev = new Set(oldSnap[providerId] || []);
    for (const mid of [...cur].filter((m) => !prev.has(m)).sort()) {
      const m = pdata.models[mid];
      if (!m || typeof m !== 'object') continue;
      const cost = m.cost && typeof m.cost === 'object' ? m.cost : {};
      const inp = cost.input || 0;
      const outp = cost.output || 0;
      newModels.push({
        provider: pdata.name || providerId,
        model_name: m.name || mid,
        input_price: inp,
        output_price: outp,
        context: (m.limit && m.limit.context) || 0,
        tool_call: !!m.tool_call,
        is_free: inp === 0 && outp === 0,
      });
    }
  }
  return newModels;
}

export function get_user_models_sync(): ProviderCatalog {
  const result: ProviderCatalog = {};
  const configured = config.get_working_providers();
  const catalog = readCatalogCache();
  if (!catalog) return result;
  for (const [providerId, pdata] of Object.entries(catalog)) {
    if (!pdata || typeof pdata !== 'object' || !pdata.models) continue;
    const models = pdata.models || {};
    if (!Object.keys(models).length) continue;
    const providerName = pdata.name || providerId;
    const providerKey = providerName !== providerId ? `${providerId} (${providerName})` : providerId;
    const isConfigured = configured.includes(providerId);
    const modelList: ModelInfo[] = [];
    for (const [modelId, mdata] of Object.entries(models)) {
      if (!mdata || typeof mdata !== 'object') continue;
      const cost = mdata.cost && typeof mdata.cost === 'object' ? mdata.cost : {};
      const inp = cost.input || 0;
      const outp = cost.output || 0;
      const cacheRead = cost.cache_read !== undefined ? cost.cache_read : null;
      const isFree = inp === 0 && outp === 0;
      modelList.push({
        id: `${providerId}/${modelId}`,
        name: mdata.name || modelId,
        provider: providerId,
        input_price: inp,
        output_price: outp,
        cache_price: cacheRead,
        context: (mdata.limit && mdata.limit.context) || 0,
        output_limit: (mdata.limit && mdata.limit.output) || 0,
        is_free: isFree,
        tool_call: !!mdata.tool_call,
        reasoning: !!mdata.reasoning,
        open_weights: !!mdata.open_weights,
      });
    }
    if (modelList.length) {
      modelList.sort((a, b) => a.input_price + a.output_price - (b.input_price + b.output_price));
      const group: ProviderGroup = {
        id: providerId,
        configured: isConfigured,
        name: providerName,
        models: modelList,
      };
      result[providerKey] = group;
    }
  }
  return result;
}

export function readCatalogCache(): CatalogData | null {
  if (!fs.existsSync(config.CACHE_PATH)) return null;
  try {
    return JSON.parse(fs.readFileSync(config.CACHE_PATH, 'utf-8')) as CatalogData;
  } catch {
    return null;
  }
}

export function find_model_in_catalog(catalog: ProviderCatalog, modelId: string): ModelInfo | null {
  if (!catalog || !modelId) return null;
  for (const pd of Object.values(catalog)) {
    for (const m of pd.models || []) {
      if (m.id === modelId) return m;
    }
  }
  return null;
}

export function model_total_cost(model: ModelInfo | null | undefined): number {
  return Number(model && model.input_price) + Number(model && model.output_price);
}

export function read_saver_policy(): SaverPolicy {
  const defaults: SaverPolicy = {
    mode: 'paid',
    daily_budget_usd: 1.0,
    free_daily_token_limit: 100000,
    max_paid_cost_per_million: 5.0,
    last_applied: null,
  };
  if (fs.existsSync(config.SAVER_POLICY_PATH)) {
    try {
      const saved = JSON.parse(fs.readFileSync(config.SAVER_POLICY_PATH, 'utf-8'));
      return { ...defaults, ...saved };
    } catch {}
  }
  return defaults;
}

export function write_saver_policy(policy: SaverPolicy): void {
  const dir = path.dirname(config.SAVER_POLICY_PATH);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(config.SAVER_POLICY_PATH, JSON.stringify(policy, null, 2), 'utf-8');
}

export function normalize_provider_filter(provider: string | null | undefined): string | null {
  if (provider === undefined || provider === null) return null;
  provider = String(provider).trim().toLowerCase();
  if (['', 'any', 'all', '*', 'none', 'no'].includes(provider)) return null;
  return provider;
}

export function configured_model_list(catalog: ProviderCatalog, strict = false): ModelInfo[] {
  const explicit = strict ? get_explicit_provider_ids() : new Set<string>();
  const out: ModelInfo[] = [];
  for (const pd of Object.values(catalog)) {
    if (strict ? !explicit.has(pd.id) : !pd.configured) continue;
    for (const m of pd.models || []) {
      const withStatus = m as ModelInfo & { status?: string };
      if (withStatus.status !== 'deprecated') out.push(m);
    }
  }
  return out;
}

export function get_explicit_provider_ids(): Set<string> {
  const configured = new Set<string>();
  const cfg = config.read_config();
  if (cfg && cfg.provider) Object.keys(cfg.provider).forEach((k) => configured.add(k));
  config.get_providers_from_env().forEach((k) => configured.add(k));
  config.get_providers_from_model_history().forEach((k) => configured.add(k));
  return configured;
}

export function choose_saver_models(
  catalog: ProviderCatalog,
  mode: 'paid' | 'free',
  task: string,
  maxPaidCost: number,
  provider: string | null = null,
  strict = false
): ChosenSaverModels {
  const providerNorm = normalize_provider_filter(provider);
  let configured = configured_model_list(catalog, strict);
  if (providerNorm) {
    configured = configured.filter(
      (m) => m.provider === providerNorm || String(m.id).startsWith(providerNorm + '/')
    );
  }
  if (!configured.length) {
    let msg = 'No usable providers found. Add an API key/provider config first.';
    if (providerNorm) msg = `No usable models found for provider '${providerNorm}'. Add its API key/config first.`;
    return { error: msg } as unknown as ChosenSaverModels;
  }

  configured.sort((a, b) => model_total_cost(a) - model_total_cost(b));
  const freeModels = configured.filter((m) => m.is_free);
  const paidAllowed = configured.filter((m) => !m.is_free && model_total_cost(m) <= maxPaidCost);
  let cheapPool = [...freeModels, ...paidAllowed];
  let candidatePool: ModelInfo[];
  if (mode === 'free') {
    candidatePool = freeModels.length ? freeModels : paidAllowed.length ? paidAllowed : configured.slice(0, 3);
  } else {
    candidatePool = cheapPool.length ? cheapPool : configured.slice(0, 3);
  }

  if (['coding', 'review'].includes(task)) {
    const toolCandidates = candidatePool.filter((m) => m.tool_call);
    if (toolCandidates.length) candidatePool = toolCandidates;
  }
  if (['review', 'planning'].includes(task)) {
    const reasoningCandidates = candidatePool.filter((m) => m.reasoning);
    if (reasoningCandidates.length) candidatePool = reasoningCandidates;
  }

  candidatePool.sort((a, b) => {
    const freeFirst = mode === 'free';
    const ka = freeFirst && !a.is_free ? 1 : 0;
    const kb = freeFirst && !b.is_free ? 1 : 0;
    if (ka !== kb) return ka - kb;
    if (model_total_cost(a) !== model_total_cost(b)) return model_total_cost(a) - model_total_cost(b);
    return Number(b.context || 0) - Number(a.context || 0);
  });
  const mainModel = candidatePool[0];

  let smallPool = freeModels.length ? freeModels : configured;
  smallPool = smallPool.filter((m) => m.id !== mainModel.id).length ? smallPool.filter((m) => m.id !== mainModel.id) : smallPool;
  smallPool.sort((a, b) => {
    const freeFirst = mode === 'free';
    const ka = freeFirst && !a.is_free ? 1 : 0;
    const kb = freeFirst && !b.is_free ? 1 : 0;
    if (ka !== kb) return ka - kb;
    return model_total_cost(a) - model_total_cost(b);
  });
  const smallModel = smallPool[0];

  const fallbackPool = cheapPool.filter((m) => m.id !== mainModel.id && m.id !== smallModel.id);
  fallbackPool.sort((a, b) => {
    const freeFirst = mode === 'free';
    const ka = freeFirst && !a.is_free ? 1 : 0;
    const kb = freeFirst && !b.is_free ? 1 : 0;
    if (ka !== kb) return ka - kb;
    return model_total_cost(a) - model_total_cost(b);
  });
  const fallbacks = fallbackPool.slice(0, 3).map((m) => m.id);

  return {
    main: mainModel,
    small: smallModel,
    fallbacks,
    configured_count: configured.length,
    free_count: freeModels.length,
    paid_allowed_count: paidAllowed.length,
  };
}

export function recommend_models(catalog: ProviderCatalog, task: string) {
  const configured: ModelInfo[] = [];
  for (const pd of Object.values(catalog)) {
    if (pd.configured) configured.push(...(pd.models || []));
  }
  if (!configured.length) return { configured: false, items: [] };
  const templates = TASK_TEMPLATES[task] || TASK_TEMPLATES.coding;
  const items: { tag: string; desc: string; model: ModelInfo }[] = [];
  const seen = new Set<string>();
  for (const tpl of templates) {
    let candidates: ModelInfo[];
    if (tpl.weight === -1) {
      candidates = [...configured].sort((a, b) => -(model_total_cost(a) - model_total_cost(b)));
    } else if (tpl.weight === 1) {
      const mid = Math.floor(configured.length / 2);
      candidates = configured.slice(mid);
    } else {
      candidates = [...configured].sort((a, b) => model_total_cost(a) - model_total_cost(b));
    }
    for (const m of candidates) {
      if (!seen.has(m.id)) {
        seen.add(m.id);
        items.push({ tag: tpl.tag, desc: tpl.desc, model: m });
        break;
      }
    }
  }
  return { configured: true, items };
}

export function cost_projection(catalog: ProviderCatalog, modelId: string, smallId: string) {
  const m = find_model_in_catalog(catalog, modelId);
  const s = find_model_in_catalog(catalog, smallId);
  const scenarios = [
    { label: 'Light session', input: 100000, output: 20000 },
    { label: 'Medium session', input: 500000, output: 100000 },
    { label: 'Heavy session', input: 2000000, output: 500000 },
  ];
  const rows = scenarios.map(({ label, input, output }) => {
    const row: Record<string, any> = { label };
    if (m) {
      const c = (m.input_price * input + m.output_price * output) / 1e6;
      row.main = c;
    }
    if (s) {
      const c = (s.input_price * input + s.output_price * output) / 1e6;
      row.small = c;
      if (m && row.main > 0 && c > 0) {
        const saved = row.main - c;
        row.saved_pct = saved > 0 ? Math.round((saved / row.main) * 100) : 0;
      }
    }
    return row;
  });
  return { rows, main: m || null, small: s || null };
}

export function heatmap(catalog: ProviderCatalog) {
  const configured: ModelInfo[] = [];
  for (const pd of Object.values(catalog)) {
    if (pd.configured) configured.push(...(pd.models || []));
  }
  if (!configured.length) return [];
  const caps: { label: string; key: (m: ModelInfo) => number }[] = [
    { label: 'Cheapest overall', key: (m) => model_total_cost(m) },
    { label: 'Cheapest w/ tools', key: (m) => (m.tool_call ? model_total_cost(m) : Infinity) },
    { label: 'Cheapest 128k+ ctx', key: (m) => (Number(m.context) >= 128000 ? model_total_cost(m) : Infinity) },
    { label: 'Cheapest reasoning', key: (m) => (m.reasoning ? model_total_cost(m) : Infinity) },
    { label: 'Largest context', key: (m) => -Number(m.context || 0) },
  ];
  const out: { label: string; model: ModelInfo }[] = [];
  for (const { label, key } of caps) {
    let best: ModelInfo | null = null;
    let bestKey = Infinity;
    for (const m of configured) {
      const k = key(m);
      if (k < bestKey) {
        bestKey = k;
        best = m;
      }
    }
    if (best && bestKey !== Infinity) out.push({ label, model: best });
  }
  return out;
}
