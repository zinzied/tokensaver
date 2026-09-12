import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-newfeatures-'));
process.env.TOKENSAVER_HOME = TMP;

const rtk = await import('../src/core/filters/rtk.js');
const tokens = await import('../src/core/tokens.js');
const todo = await import('../src/core/todo.js');
const goals = await import('../src/core/goals.js');
const reminders = await import('../src/core/reminders.js');
const retry = await import('../src/core/retry.js');
const spill = await import('../src/core/spill.js');
const guard = await import('../src/core/guard.js');

test('tool_result_prune prunes large text via auto_detect', () => {
  const largeText = 'x'.repeat(10000);
  const fn = rtk.auto_detect_filter(largeText);
  assert.ok(fn !== null);
  const result = fn!(largeText);
  assert.ok(result.length < largeText.length);
  assert.ok(result.includes('[... tool result middle pruned ...]'));
  assert.ok(result.startsWith('x'.repeat(4096)));
  assert.ok(result.endsWith('x'.repeat(1024)));
});

test('tool_result_prune does not prune small text', () => {
  const smallText = 'hello world';
  const fn = rtk.auto_detect_filter(smallText);
  assert.strictEqual(fn, null);
});

test('auto_detect_filter returns tool_result_prune for large unclassified text', () => {
  const largeText = 'x'.repeat(10000);
  const fn = rtk.auto_detect_filter(largeText);
  assert.ok(fn !== null);
  assert.strictEqual(fn!.name, 'tool_result_prune');
});

test('estimate_text_tokens calculates tokens', () => {
  assert.strictEqual(tokens.estimate_text_tokens('hello'), 2);
  assert.strictEqual(tokens.estimate_text_tokens(''.padEnd(100, 'a')), 25);
});

test('estimate_message_tokens includes role overhead', () => {
  const result = tokens.estimate_message_tokens({ role: 'user', content: 'hello' });
  assert.ok(result > tokens.estimate_text_tokens('hello'));
});

test('estimate_request_tokens sums messages and system', () => {
  const result = tokens.estimate_request_tokens({
    system: 'You are helpful',
    messages: [{ role: 'user', content: 'hi' }],
  });
  assert.ok(result > 0);
});

test('todo add and list', () => {
  const item = todo.addTodo('test task');
  assert.strictEqual(item.text, 'test task');
  assert.strictEqual(item.status, 'pending');
  const store = todo.loadTodo();
  assert.ok(store.items.some((i) => i.id === item.id));
  todo.removeTodo(item.id);
});

test('todo done and cancel', () => {
  const item = todo.addTodo('done task');
  const done = todo.completeTodo(item.id);
  assert.strictEqual(done?.status, 'done');
  const item2 = todo.addTodo('cancel task');
  const cancelled = todo.cancelTodo(item2.id);
  assert.strictEqual(cancelled?.status, 'cancelled');
  todo.removeTodo(item.id);
  todo.removeTodo(item2.id);
});

test('goal add and list', () => {
  const g = goals.addGoal('test goal');
  assert.strictEqual(g.text, 'test goal');
  assert.strictEqual(g.status, 'active');
  const store = goals.loadGoals();
  assert.ok(store.goals.some((x) => x.id === g.id));
  goals.removeGoal(g.id);
});

test('goal done and abandon', () => {
  const g = goals.addGoal('done goal');
  const done = goals.completeGoal(g.id);
  assert.strictEqual(done?.status, 'completed');
  const g2 = goals.addGoal('abandon goal');
  const abandoned = goals.abandonGoal(g2.id);
  assert.strictEqual(abandoned?.status, 'abandoned');
  goals.removeGoal(g.id);
  goals.removeGoal(g2.id);
});

test('reminder add and due', () => {
  const r = reminders.addReminder('test reminder', new Date(Date.now() - 1000));
  assert.strictEqual(r.text, 'test reminder');
  const due = reminders.getDueReminders();
  assert.ok(due.some((x) => x.id === r.id));
  reminders.removeReminder(r.id);
});

test('retry resolveRetryDelay increases with attempts', () => {
  const policy = { ...retry.DEFAULT_RETRY_POLICY, jitterRatio: 0 };
  const d1 = retry.resolveRetryDelay(policy, 1);
  const d2 = retry.resolveRetryDelay(policy, 2);
  const d3 = retry.resolveRetryDelay(policy, 3);
  assert.ok(d2 > d1);
  assert.ok(d3 > d2);
});

test('retry withRetry succeeds on first try', async () => {
  const result = await retry.withRetry(async () => 42);
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.value, 42);
  assert.strictEqual(result.attempts, 1);
});

test('retry withRetry retries on retryable error', async () => {
  let attempts = 0;
  const result = await retry.withRetry(
    async () => {
      attempts++;
      if (attempts < 3) throw { status: 429 };
      return 'ok';
    },
    { maxRetries: 3, initialDelayMs: 10, jitterRatio: 0 },
  );
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.value, 'ok');
});

test('spill does not spill small text', () => {
  const result = spill.spillIfNeeded('small text');
  assert.strictEqual(result.spilled, false);
});

test('spill spills large text to disk', () => {
  const largeText = 'x'.repeat(20000);
  const result = spill.spillIfNeeded(largeText, {
    thresholdChars: 16384,
    previewHeadChars: 100,
    previewTailChars: 100,
    spillDir: TMP,
  });
  assert.strictEqual(result.spilled, true);
  assert.ok(result.spillPath);
  assert.ok(result.previewSize < largeText.length);
  assert.ok(fs.existsSync(result.spillPath!));
  const readBack = spill.readSpill(result.spillPath!);
  assert.strictEqual(readBack, largeText);
  fs.unlinkSync(result.spillPath!);
});

test('guard blocks repeated calls', () => {
  const g = guard.createGuard({ repeatThreshold: 3, windowMs: 60000, maxCallsPerWindow: 100 });
  assert.strictEqual(g.check('read').allowed, true);
  assert.strictEqual(g.check('read').allowed, true);
  assert.strictEqual(g.check('read').allowed, false);
  g.reset();
  assert.strictEqual(g.check('read').allowed, true);
});

test('guard blocks too many calls in window', () => {
  const g = guard.createGuard({ repeatThreshold: 100, windowMs: 60000, maxCallsPerWindow: 3 });
  assert.strictEqual(g.check('a').allowed, true);
  assert.strictEqual(g.check('b').allowed, true);
  assert.strictEqual(g.check('c').allowed, true);
  assert.strictEqual(g.check('d').allowed, false);
  g.reset();
});

test('format_compaction_checkpoint produces structured output', async () => {
  const prompts = await import('../src/core/prompts.js');
  const output = prompts.format_compaction_checkpoint({
    primaryRequest: 'Fix the auth bug',
    concepts: ['TypeScript', 'JWT'],
    files: ['src/auth.ts'],
    errors: ['Token expired'],
    pendingJobs: ['Add tests'],
    currentWork: 'Fixing token refresh',
    nextStep: 'Run tests',
    criticalContext: ['Port 3000'],
  });
  assert.ok(output.includes('## Primary Request'));
  assert.ok(output.includes('Fix the auth bug'));
  assert.ok(output.includes('- TypeScript'));
  assert.ok(output.includes('- src/auth.ts'));
});
