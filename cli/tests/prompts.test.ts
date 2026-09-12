import { test } from 'node:test';
import assert from 'node:assert';
import {
  CAVEMAN_PROMPTS,
  PONYTAIL_PROMPTS,
  inject_caveman,
  inject_ponytail,
  inject_system_prompt,
} from '../src/core/prompts.js';

test('all caveman levels produce prompts', () => {
  for (const level of ['lite', 'full', 'ultra', 'wenyan-lite', 'wenyan', 'wenyan-ultra']) {
    assert.ok(CAVEMAN_PROMPTS[level], `missing ${level}`);
    assert.ok(CAVEMAN_PROMPTS[level].length > 50);
  }
});

test('all ponytail levels produce prompts', () => {
  for (const level of ['lite', 'full', 'ultra']) {
    assert.ok(PONYTAIL_PROMPTS[level]);
    assert.ok(PONYTAIL_PROMPTS[level].includes('lazy senior developer'));
  }
});

test('inject_caveman appends to claude system string', () => {
  const body: any = { system: 'be concise', messages: [{ role: 'user', content: 'x' }] };
  inject_caveman(body, 'lite');
  assert.ok(body.system.includes('be concise'));
  assert.ok(body.system.includes('Respond tersely'));
});

test('inject_ponytail adds system message to openai format', () => {
  const body: any = { messages: [{ role: 'user', content: 'x' }] };
  inject_ponytail(body, 'lite');
  assert.strictEqual(body.messages[0].role, 'system');
  assert.ok(body.messages[0].content.includes('lazy senior developer'));
});

test('inject_caveman appends to existing openai system message', () => {
  const body: any = { messages: [{ role: 'system', content: 'be concise' }, { role: 'user', content: 'x' }] };
  inject_caveman(body, 'lite');
  assert.strictEqual(body.messages.length, 2);
  assert.ok(body.messages[0].content.includes('be concise'));
  assert.ok(body.messages[0].content.includes('Respond tersely'));
});

test('inject_system_prompt handles gemini system_instruction', () => {
  const body: any = { system_instruction: { parts: [{ text: 'orig' }] }, contents: [] };
  inject_system_prompt(body, 'extra');
  assert.strictEqual(body.system_instruction.parts.length, 2);
  assert.strictEqual(body.system_instruction.parts[1].text, 'extra');
});

test('inject_system_prompt handles claude system list with cache_control ordering', () => {
  const body: any = {
    system: [
      { type: 'text', text: 'first', cache_control: { type: 'ephemeral' } },
      { type: 'text', text: 'second' },
    ],
    messages: [],
  };
  inject_system_prompt(body, 'injected');
  // single cache_control block at index 0 -> inserted before it (Python behavior)
  assert.strictEqual(body.system[0].text, 'injected');
  assert.strictEqual(body.system[0].type, 'text');
  assert.strictEqual(body.system[1].text, 'first');
  assert.strictEqual(body.system[2].text, 'second');
});

test('inject_system_prompt handles responses API instructions', () => {
  const body: any = { instructions: 'orig', input: [] };
  inject_system_prompt(body, 'extra');
  assert.ok(body.instructions.includes('orig'));
  assert.ok(body.instructions.includes('extra'));
});
