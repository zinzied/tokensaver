export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  input_price: number;
  output_price: number;
  cache_price: number | null;
  context: number;
  output_limit: number;
  is_free: boolean;
  tool_call: boolean;
  reasoning: boolean;
  open_weights: boolean;
}

export interface ProviderGroup {
  id: string;
  configured: boolean;
  name: string;
  models: ModelInfo[];
}

export interface ProviderCatalog {
  [providerKey: string]: ProviderGroup;
}

export interface CatalogFetchResult {
  catalog: Record<string, unknown> | null;
  newModels: NewModelInfo[];
  source: 'cache' | 'network' | 'error';
  error?: string;
}

export interface NewModelInfo {
  provider: string;
  model_name: string;
  input_price: number;
  output_price: number;
  context: number;
  tool_call: boolean;
  is_free: boolean;
}

export interface SaverPolicy {
  mode: 'paid' | 'free';
  daily_budget_usd: number;
  free_daily_token_limit: number;
  max_paid_cost_per_million: number;
  last_applied: string | null;
}

export interface ChosenSaverModels {
  main: ModelInfo;
  small: ModelInfo;
  fallbacks: string[];
  configured_count: number;
  free_count: number;
  paid_allowed_count: number;
  error?: string;
}

export interface LedgerEntry {
  timestamp: string;
  kind?: string;
  description?: string;
  raw_tokens?: number;
  compressed_tokens?: number;
  saved_tokens?: number;
  compression_pct?: number;
  metadata?: unknown;
}

export interface ProxyHistoryEntry {
  path?: string;
  model?: string;
  saved_tokens?: number;
  saved_bytes?: number;
  frost_saved?: number;
  upstream?: string;
  timestamp?: number;
  ts_iso?: string;
}

export interface ProxyConfig {
  enabled?: boolean;
  port?: number;
  history?: ProxyHistoryEntry[];
  total_saved_bytes?: number;
  total_saved_tokens?: number;
  total_frost_saved?: number;
  frost_total_saved_tokens?: number;
  proxied_providers?: string[];
  upstreams?: Record<string, string>;
  saved_base_urls?: Record<string, string>;
  account_strategy?: string;
}

export interface RtkHit {
  shape: string;
  filter: string;
  saved: number;
}

export interface CompressStats {
  bytesBefore: number;
  bytesAfter: number;
  hits: RtkHit[];
}

export interface ProxyStatus {
  running: boolean;
  port: number;
  enabled: boolean;
  requestsServed: number;
  totalSavedBytes: number;
  compressionHits: number;
  lastModel: string;
  lastAccount: string;
  startedAt: string | null;
  proxiedProviders: string[];
  upstreams: Record<string, string>;
}

export interface SqliteRow {
  [key: string]: unknown;
}

export interface SqliteDb {
  exec(sql: string): void;
  prepare(sql: string): {
    run(...params: unknown[]): { changes: number; lastInsertRowid: number | bigint };
    get(...params: unknown[]): SqliteRow | undefined;
    all(...params: unknown[]): SqliteRow[];
  };
  close(): void;
}

export type FilterFn = (text: string) => string;

export type RequestBody = Record<string, any>;
