import { ACCOUNTS_PATH } from './config.js';
import { readJson, writeJson } from './utils.js';

export const BACKOFF_CONFIG = { base_ms: 2000, max_ms: 300000, max_level: 15 };
export const TRANSIENT_COOLDOWN_MS = 30000;
export const COOLDOWN_LONG_MS = 120000;
export const COOLDOWN_SHORT_MS = 5000;

interface ErrorRule {
  text?: string;
  status?: number;
  cooldown_ms?: number;
  backoff?: boolean;
}

export const ERROR_RULES: ErrorRule[] = [
  { text: 'no credentials', cooldown_ms: COOLDOWN_LONG_MS },
  { text: 'request not allowed', cooldown_ms: COOLDOWN_SHORT_MS },
  { text: 'improperly formed request', cooldown_ms: COOLDOWN_LONG_MS },
  { text: 'rate limit', backoff: true },
  { text: 'too many requests', backoff: true },
  { text: 'quota exceeded', backoff: true },
  { text: 'capacity', backoff: true },
  { text: 'overloaded', backoff: true },
  { status: 401, cooldown_ms: COOLDOWN_LONG_MS },
  { status: 402, cooldown_ms: COOLDOWN_LONG_MS },
  { status: 403, cooldown_ms: COOLDOWN_LONG_MS },
  { status: 404, cooldown_ms: COOLDOWN_LONG_MS },
  { status: 429, backoff: true },
];

export const PROVIDER_TIERS: Record<string, string[]> = {
  subscription: ['claude-code', 'codex', 'github-copilot', 'cursor', 'gemini-cli'],
  cheap: ['glm', 'minimax', 'kimi'],
  free: ['kiro', 'opencode-free', 'vertex', 'iflow', 'qwen'],
};

export const TIER_PRIORITY = ['subscription', 'cheap', 'free'];
export const FALLBACK_ORDER = TIER_PRIORITY;

export interface TierProviderInfo {
  name: string;
  cost: string;
  priority: number;
}

export const TIER_CATALOG: Record<string, Record<string, TierProviderInfo>> = {
  subscription: {
    'claude-code': { name: 'Claude Code', cost: '$20-200/mo', priority: 0 },
    codex: { name: 'Codex CLI', cost: '$20-200/mo', priority: 1 },
    'github-copilot': { name: 'GitHub Copilot', cost: '$10-19/mo', priority: 2 },
    cursor: { name: 'Cursor IDE', cost: '$20/mo', priority: 3 },
    'gemini-cli': { name: 'Gemini CLI', cost: '$20/mo', priority: 4 },
  },
  cheap: {
    glm: { name: 'GLM-5.1', cost: '$0.6/1M', priority: 0 },
    minimax: { name: 'MiniMax M2.7', cost: '$0.2/1M', priority: 1 },
    kimi: { name: 'Kimi K2.5', cost: '$9/mo flat', priority: 2 },
  },
  free: {
    kiro: { name: 'Kiro AI', cost: 'Free', priority: 0 },
    'opencode-free': { name: 'OpenCode Free', cost: 'Free', priority: 1 },
    vertex: { name: 'Vertex AI ($300 credits)', cost: 'Free credits', priority: 2 },
    iflow: { name: 'iFlow', cost: 'Free', priority: 3 },
    qwen: { name: 'Qwen', cost: 'Free', priority: 4 },
  },
};

export const PROVIDER_ENDPOINTS: Record<string, { base_url: string; format: string }> = {
  'claude-code': { base_url: 'https://api.anthropic.com', format: 'claude' },
  codex: { base_url: 'https://api.openai.com', format: 'openai' },
  'github-copilot': { base_url: 'https://api.githubcopilot.com', format: 'openai' },
  cursor: { base_url: 'https://api.cursor.com', format: 'openai' },
  'gemini-cli': { base_url: 'https://generativelanguage.googleapis.com', format: 'gemini' },
  glm: { base_url: 'https://open.bigmodel.cn/api/paas/v4', format: 'openai' },
  minimax: { base_url: 'https://api.minimax.chat/v1', format: 'openai' },
  kimi: { base_url: 'https://api.moonshot.cn/v1', format: 'openai' },
  kiro: { base_url: 'https://api.kiro.ai/v1', format: 'openai' },
  'opencode-free': { base_url: 'https://api.opencode.ai/v1', format: 'openai' },
  vertex: { base_url: 'https://us-central1-aiplatform.googleapis.com/v1', format: 'vertex' },
  iflow: { base_url: 'https://api.iflow.ai/v1', format: 'openai' },
  qwen: { base_url: 'https://dashscope.aliyuncs.com/api/v1', format: 'openai' },
};

export const PROVIDER_MODEL_MAP: Record<string, string[]> = {
  subscription: ['claude-sonnet-4-5', 'claude-sonnet-4', 'gpt-4o', 'gemini-2.5-pro', 'claude-haiku-3-5'],
  cheap: ['glm-5.1', 'minimax-m2.7', 'kimi-k2.5'],
  free: ['kiro-claude-sonnet', 'opencode-gpt-4o', 'gemini-2.0-flash', 'iflow-default', 'qwen-max'],
};

export function get_quota_cooldown(backoffLevel = 0): number {
  const level = Math.max(0, backoffLevel - 1);
  const cooldown = BACKOFF_CONFIG.base_ms * 2 ** level;
  return Math.min(cooldown, BACKOFF_CONFIG.max_ms);
}

export interface FallbackErrorResult {
  should_fallback: boolean;
  cooldown_ms: number;
  new_backoff_level?: number;
}

export function check_fallback_error(status: number, errorText: string, backoffLevel = 0): FallbackErrorResult {
  const lower = String(errorText || '').toLowerCase();

  for (const rule of ERROR_RULES) {
    if (rule.text && lower.includes(rule.text)) {
      if (rule.backoff) {
        const newLevel = Math.min(backoffLevel + 1, BACKOFF_CONFIG.max_level);
        return {
          should_fallback: true,
          cooldown_ms: get_quota_cooldown(newLevel),
          new_backoff_level: newLevel,
        };
      }
      return { should_fallback: true, cooldown_ms: rule.cooldown_ms! };
    }

    if (rule.status && rule.status === status) {
      if (rule.backoff) {
        const newLevel = Math.min(backoffLevel + 1, BACKOFF_CONFIG.max_level);
        return {
          should_fallback: true,
          cooldown_ms: get_quota_cooldown(newLevel),
          new_backoff_level: newLevel,
        };
      }
      return { should_fallback: true, cooldown_ms: rule.cooldown_ms! };
    }
  }

  return { should_fallback: true, cooldown_ms: TRANSIENT_COOLDOWN_MS };
}

export function get_tier_for_provider(providerId: string): string {
  for (const [tier, providers] of Object.entries(PROVIDER_TIERS)) {
    if (providers.includes(providerId)) return tier;
  }
  return 'free';
}

export function get_providers_in_tier(tier: string): Record<string, TierProviderInfo> {
  return { ...(TIER_CATALOG[tier] || {}) };
}

export function get_all_providers(): Record<string, TierProviderInfo> {
  const result: Record<string, TierProviderInfo> = {};
  for (const tier of FALLBACK_ORDER) {
    Object.assign(result, TIER_CATALOG[tier] || {});
  }
  return result;
}

export function get_provider_endpoint(providerId: string): { base_url?: string; format?: string } {
  return { ...(PROVIDER_ENDPOINTS[providerId] || {}) };
}

export function resolve_fallback_chain(providerId: string): string[] {
  const tier = get_tier_for_provider(providerId);
  const chain: string[] = [];
  const idx = FALLBACK_ORDER.indexOf(tier);
  for (const t of FALLBACK_ORDER.slice(idx + 1)) {
    chain.push(...(PROVIDER_TIERS[t] || []));
  }
  return chain;
}

function _toMs(value: string | number | undefined | null): number {
  if (!value) return 0;
  if (typeof value === 'number') return value < 1e12 ? value * 1000 : value;
  const n = Date.parse(value);
  return Number.isNaN(n) ? 0 : n;
}

export interface Account {
  id: string;
  provider: string;
  api_key: string | null;
  base_url: string | null;
  priority: number;
  is_active: boolean;
  consecutive_use: number;
  rate_limited_until: string | null;
  backoff_level: number;
  last_error: { status: number; message: string; timestamp: number } | null;
  model_locks: Record<string, string>;
}

export class AccountManager {
  dataFile: string;
  _accounts: { accounts: Account[] };
  _rotationState: Record<string, { index: number; use_count: number }>;

  constructor() {
    this.dataFile = ACCOUNTS_PATH;
    this._accounts = this._load();
    this._rotationState = {};
  }

  _load(): { accounts: Account[] } {
    const data = readJson<{ accounts?: Account[] }>(this.dataFile, null);
    if (data && Array.isArray(data.accounts)) return { accounts: data.accounts };
    return { accounts: [] };
  }

  _save(): void {
    writeJson(this.dataFile, this._accounts);
  }

  add_account(provider: string, apiKey: string | null = null, baseUrl: string | null = null, priority = 0): string {
    const account: Account = {
      id: `${provider}_${this._accounts.accounts.length}`,
      provider,
      api_key: apiKey,
      base_url: baseUrl,
      priority,
      is_active: true,
      consecutive_use: 0,
      rate_limited_until: null,
      backoff_level: 0,
      last_error: null,
      model_locks: {},
    };
    this._accounts.accounts.push(account);
    this._save();
    return account.id;
  }

  get_active_accounts(provider: string, excludeIds?: string[]): Account[] {
    const exclude = new Set(excludeIds || []);
    const accounts = this._accounts.accounts.filter(
      (a) =>
        a.provider === provider &&
        a.is_active !== false &&
        !exclude.has(a.id)
    );
    const now = Date.now();
    const available: Account[] = [];
    for (const a of accounts) {
      const untilMs = _toMs(a.rate_limited_until);
      if (untilMs > now) continue;
      const locks = a.model_locks || {};
      let locked = false;
      for (const lockTs of Object.values(locks)) {
        if (lockTs && _toMs(lockTs) > now) {
          locked = true;
          break;
        }
      }
      if (locked) continue;
      available.push(a);
    }
    return available.sort((a, b) => (a.priority || 0) - (b.priority || 0));
  }

  select_account(provider: string, strategy = 'fill-first', stickyLimit = 1, model: string | null = null): Account | null {
    const accounts = this.get_active_accounts(provider);
    if (!accounts.length) return null;

    if (strategy === 'round-robin') {
      const rotationKey = `${provider}:${model || '__all__'}`;
      const state = this._rotationState[rotationKey] || { index: 0, use_count: 0 };
      const idx = state.index % accounts.length;
      const account = accounts[idx];
      state.use_count += 1;
      if (state.use_count >= stickyLimit) {
        state.index = (idx + 1) % accounts.length;
        state.use_count = 0;
      }
      this._rotationState[rotationKey] = state;
      return account;
    }

    return accounts[0];
  }

  mark_success(accountId: string): void {
    for (const a of this._accounts.accounts) {
      if (a.id === accountId) {
        a.rate_limited_until = null;
        a.backoff_level = 0;
        a.last_error = null;
        a.consecutive_use = (a.consecutive_use || 0) + 1;
        break;
      }
    }
    this._save();
  }

  mark_error(accountId: string, status: number, errorText: string): void {
    for (const a of this._accounts.accounts) {
      if (a.id === accountId) {
        const result = check_fallback_error(status, errorText, a.backoff_level || 0);
        a.backoff_level = result.new_backoff_level || a.backoff_level || 0;
        const cooldown = result.cooldown_ms;
        if (cooldown > 0) {
          a.rate_limited_until = new Date(Date.now() + cooldown).toISOString();
        }
        a.last_error = {
          status,
          message: String(errorText || '').slice(0, 200),
          timestamp: Date.now() / 1000,
        };
        break;
      }
    }
    this._save();
  }

  lock_model(accountId: string, model: string, cooldownMs: number): void {
    for (const a of this._accounts.accounts) {
      if (a.id === accountId) {
        const locks = a.model_locks || (a.model_locks = {});
        locks[model] = new Date(Date.now() + cooldownMs).toISOString();
        break;
      }
    }
    this._save();
  }

  get_summary(): { id: string; provider: string; status: string; priority: number }[] {
    return this._accounts.accounts.map((a) => ({
      id: a.id,
      provider: a.provider,
      status: a.rate_limited_until ? 'rate_limited' : 'active',
      priority: a.priority || 0,
    }));
  }
}

export class TieredRouter {
  account_manager: AccountManager;
  _rotationStateCache: Record<string, { index: number; use_count: number }>;

  constructor(accountManager: AccountManager | null = null) {
    this.account_manager = accountManager || new AccountManager();
    this._rotationStateCache = {};
  }

  get_tier_for_provider(providerId: string): string {
    return get_tier_for_provider(providerId);
  }

  build_fallback_chain(providerId: string): string[] {
    const tier = this.get_tier_for_provider(providerId);
    const chain: string[] = [];
    let started = false;
    for (const t of TIER_PRIORITY) {
      if (t === tier) started = true;
      if (started) {
        for (const p of PROVIDER_TIERS[t] || []) {
          if (p !== providerId) chain.push(p);
        }
      }
    }
    return chain;
  }

  resolve_model_chain(primaryProvider: string, model: string | null = null, extraFallbacks: string[] | null = null): string[] {
    const chain = [primaryProvider];
    chain.push(...this.build_fallback_chain(primaryProvider));
    if (extraFallbacks) {
      for (const f of extraFallbacks) {
        if (!chain.includes(f)) chain.push(f);
      }
    }
    return chain;
  }

  try_account(provider: string, strategy = 'fill-first', model: string | null = null, excludeIds: string[] | null = null): [string | null, Account | null] {
    const accounts = this.account_manager.get_active_accounts(provider, excludeIds || undefined);
    if (!accounts.length) return [null, null];

    if (strategy === 'round-robin') {
      const rotationKey = `${provider}:${model || '__all__'}`;
      const state = this._rotationStateCache[rotationKey] || { index: 0, use_count: 0 };
      const stickyLimit = 1;
      const idx = state.index % accounts.length;
      const account = accounts[idx];
      state.use_count += 1;
      if (state.use_count >= stickyLimit) {
        state.index = (idx + 1) % accounts.length;
        state.use_count = 0;
      }
      this._rotationStateCache[rotationKey] = state;
      return [account.id, account];
    }

    return [accounts[0].id, accounts[0]];
  }
}
