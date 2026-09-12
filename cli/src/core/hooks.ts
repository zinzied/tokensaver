import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';

export interface HookCommand {
  command: string;
  timeoutSec?: number;
}

export interface HookMatcher {
  matcher?: string;
  hooks: HookCommand[];
}

export interface HooksConfig {
  PreToolUse?: HookMatcher[];
  PostToolUse?: HookMatcher[];
  Stop?: HookMatcher[];
  Notification?: HookMatcher[];
}

export type HookDialect = 'claude-code' | 'codex';

export interface HookResult {
  hook: HookCommand;
  exitCode: number;
  stdout: string;
  stderr: string;
  durationMs: number;
}

function findHooksFile(projectDir: string): { path: string; dialect: HookDialect } | null {
  const claudePath = path.join(projectDir, '.claude', 'hooks.json');
  if (fs.existsSync(claudePath)) return { path: claudePath, dialect: 'claude-code' };
  const codexPath = path.join(projectDir, 'hooks.json');
  if (fs.existsSync(codexPath)) {
    try {
      const content = JSON.parse(fs.readFileSync(codexPath, 'utf8'));
      if (content.version === 'v1' || content.events) return { path: codexPath, dialect: 'codex' };
    } catch { /* not a codex hooks file */ }
  }
  return null;
}

export function loadHooks(projectDir: string): { config: HooksConfig; dialect: HookDialect } | null {
  const found = findHooksFile(projectDir);
  if (!found) return null;
  try {
    const raw = fs.readFileSync(found.path, 'utf8');
    const config = JSON.parse(raw) as HooksConfig;
    return { config, dialect: found.dialect };
  } catch {
    return null;
  }
}

function matchesMatcher(toolName: string, matcher?: string): boolean {
  if (!matcher || matcher === '*' || matcher === '') return true;
  if (matcher.includes('|')) {
    return matcher.split('|').some((m) => m.trim() === toolName);
  }
  return toolName === matcher;
}

export function getHooksForPoint(
  config: HooksConfig,
  point: keyof HooksConfig,
  toolName?: string,
): HookCommand[] {
  const matchers = config[point];
  if (!matchers || !Array.isArray(matchers)) return [];
  const results: HookCommand[] = [];
  for (const m of matchers) {
    if (toolName && !matchesMatcher(toolName, m.matcher)) continue;
    results.push(...m.hooks);
  }
  return results;
}

export function runHook(hook: HookCommand, env?: Record<string, string>): HookResult {
  const start = Date.now();
  const timeoutMs = (hook.timeoutSec || 30) * 1000;
  try {
    const output = execSync(hook.command, {
      timeout: timeoutMs,
      encoding: 'utf8',
      env: { ...process.env, ...env },
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return {
      hook,
      exitCode: 0,
      stdout: output,
      stderr: '',
      durationMs: Date.now() - start,
    };
  } catch (e: any) {
    return {
      hook,
      exitCode: e.status || 1,
      stdout: e.stdout || '',
      stderr: (e.stderr || '').slice(0, 1000),
      durationMs: Date.now() - start,
    };
  }
}

export function runHooksForPoint(
  config: HooksConfig,
  point: keyof HooksConfig,
  toolName?: string,
  env?: Record<string, string>,
): HookResult[] {
  const hooks = getHooksForPoint(config, point, toolName);
  return hooks.map((h) => runHook(h, env));
}
