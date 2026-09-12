export interface RetryPolicy {
  maxRetries: number;
  initialDelayMs: number;
  maxDelayMs: number;
  jitterRatio: number;
  retryableCodes: Set<number>;
}

export const DEFAULT_RETRY_POLICY: RetryPolicy = {
  maxRetries: 3,
  initialDelayMs: 1000,
  maxDelayMs: 30000,
  jitterRatio: 0.5,
  retryableCodes: new Set([429, 500, 502, 503, 504]),
};

export function resolveRetryDelay(
  policy: RetryPolicy,
  retry: number,
  random?: () => number,
): number {
  const rand = random ?? Math.random;
  const exponent = Math.min(retry - 1, 1024);
  const exponential = Math.min(policy.initialDelayMs * 2 ** exponent, policy.maxDelayMs);
  const jitter = 1 - policy.jitterRatio + 2 * policy.jitterRatio * rand();
  return Math.min(exponential * jitter, policy.maxDelayMs);
}

export function isRetryable(statusCode: number, policy: RetryPolicy = DEFAULT_RETRY_POLICY): boolean {
  return policy.retryableCodes.has(statusCode);
}

export async function sleep(ms: number, signal?: AbortSignal): Promise<boolean> {
  if (signal?.aborted) return false;
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(true), ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      resolve(false);
    }, { once: true });
  });
}

export interface RetryResult<T> {
  ok: boolean;
  value?: T;
  error?: unknown;
  attempts: number;
  totalDelayMs: number;
}

export async function withRetry<T>(
  fn: () => Promise<T>,
  policy: Partial<RetryPolicy> = {},
  signal?: AbortSignal,
): Promise<RetryResult<T>> {
  const p = { ...DEFAULT_RETRY_POLICY, ...policy };
  let lastError: unknown;
  let totalDelayMs = 0;
  for (let attempt = 1; attempt <= p.maxRetries + 1; attempt++) {
    if (signal?.aborted) return { ok: false, error: new Error('aborted'), attempts: attempt - 1, totalDelayMs };
    try {
      const value = await fn();
      return { ok: true, value, attempts: attempt, totalDelayMs };
    } catch (e: unknown) {
      lastError = e;
      if (attempt > p.maxRetries) break;
      const status = extractStatus(e);
      if (status !== null && !isRetryable(status, p)) break;
      const delay = resolveRetryDelay(p, attempt);
      totalDelayMs += delay;
      await sleep(delay, signal);
    }
  }
  return { ok: false, error: lastError, attempts: p.maxRetries + 1, totalDelayMs };
}

function extractStatus(e: unknown): number | null {
  if (e && typeof e === 'object') {
    const obj = e as Record<string, unknown>;
    if (typeof obj.status === 'number') return obj.status;
    if (typeof obj.statusCode === 'number') return obj.statusCode;
    if (obj.response && typeof obj.response === 'object') {
      const resp = obj.response as Record<string, unknown>;
      if (typeof resp.status === 'number') return resp.status;
    }
  }
  return null;
}
