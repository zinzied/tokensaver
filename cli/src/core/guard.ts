export interface ToolCall {
  name: string;
  args?: string;
  timestamp: number;
}

export interface GuardConfig {
  repeatThreshold: number;
  windowMs: number;
  maxCallsPerWindow: number;
}

export const DEFAULT_GUARD_CONFIG: GuardConfig = {
  repeatThreshold: 3,
  windowMs: 60_000,
  maxCallsPerWindow: 20,
};

export interface GuardResult {
  allowed: boolean;
  reason?: string;
  repeatCount?: number;
  totalInWindow?: number;
}

export class LoopHygieneGuard {
  private calls: ToolCall[] = [];
  private config: GuardConfig;

  constructor(config: Partial<GuardConfig> = {}) {
    this.config = { ...DEFAULT_GUARD_CONFIG, ...config };
  }

  check(name: string, args?: string): GuardResult {
    const now = Date.now();
    this.calls = this.calls.filter((c) => now - c.timestamp < this.config.windowMs);

    const totalInWindow = this.calls.length;
    if (totalInWindow >= this.config.maxCallsPerWindow) {
      return {
        allowed: false,
        reason: `Too many tool calls (${totalInWindow}) in ${this.config.windowMs / 1000}s window`,
        totalInWindow,
      };
    }

    const recentSame = this.calls.filter(
      (c) => c.name === name && c.args === args,
    );
    const repeatCount = recentSame.length + 1;

    if (repeatCount >= this.config.repeatThreshold) {
      return {
        allowed: false,
        reason: `Repeated call to ${name} (${repeatCount}x). Consider a different approach.`,
        repeatCount,
        totalInWindow,
      };
    }

    this.calls.push({ name, args, timestamp: now });
    return { allowed: true, repeatCount, totalInWindow: totalInWindow + 1 };
  }

  reset(): void {
    this.calls = [];
  }

  getCallHistory(): ToolCall[] {
    return [...this.calls];
  }
}

export function createGuard(config?: Partial<GuardConfig>): LoopHygieneGuard {
  return new LoopHygieneGuard(config);
}
