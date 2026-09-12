import { test } from 'node:test';
import assert from 'node:assert';
import {
  FORMATS,
  detect_format,
  translate_request,
  translate_openai_to_claude,
  translate_claude_to_openai,
} from '../src/core/translate.js';

test('detect_format identifies claude via system or anthropic_version', () => {
  assert.strictEqual(detect_format({ system: 'x' }), FORMATS.CLAUDE);
  assert.strictEqual(detect_format({ anthropic_version: '2023-06-01' }), FORMATS.CLAUDE);
});

test('detect_format identifies gemini via contents', () => {
  assert.strictEqual(detect_format({ contents: [{ parts: [] }] }), FORMATS.GEMINI);
});

test('detect_format identifies openai-responses via input', () => {
  assert.strictEqual(detect_format({ input: 'hi' }), FORMATS.OPENAI_RESPONSES);
  assert.strictEqual(detect_format({ input: [{ role: 'user' }] }), FORMATS.OPENAI_RESPONSES);
});

test('detect_format defaults to openai', () => {
  assert.strictEqual(detect_format({}), FORMATS.OPENAI);
  assert.strictEqual(detect_format(null), FORMATS.OPENAI);
});

test('openai -> claude translation', () => {
  const out = translate_openai_to_claude({
    system: 'sys',
    messages: [
      { role: 'system', content: 'first system' },
      { role: 'user', content: 'hello' },
      { role: 'assistant', content: 'hi' },
    ],
    temperature: 0.5,
  });
  // top-level `system` string wins over first system message (Python behavior)
  assert.strictEqual(out.system, 'sys');
  assert.strictEqual(out.messages.length, 2);
  assert.deepStrictEqual(out.messages[0], { role: 'user', content: [{ type: 'text', text: 'hello' }] });
  assert.deepStrictEqual(out.messages[1], { role: 'assistant', content: [{ type: 'text', text: 'hi' }] });
  assert.strictEqual(out.temperature, 0.5);
});

test('openai -> claude: tool_calls and tool role', () => {
  const out = translate_openai_to_claude({
    messages: [
      {
        role: 'assistant',
        content: '',
        tool_calls: [{ id: 'c1', function: { name: 'read', arguments: '{}' } }],
      },
      { role: 'tool', tool_call_id: 'c1', content: 'file contents' },
    ],
  });
  // empty string content becomes a text block, tool_use is appended (Python behavior)
  assert.deepStrictEqual(out.messages[0].content[1], {
    type: 'tool_use',
    id: 'c1',
    name: 'read',
    input: '{}',
  });
  assert.deepStrictEqual(out.messages[1], {
    role: 'user',
    content: [{ type: 'tool_result', tool_use_id: 'c1', content: 'file contents' }],
  });
});

test('claude -> openai translation', () => {
  const out = translate_claude_to_openai({
    system: 'sys',
    messages: [{ role: 'user', content: [{ type: 'text', text: 'hello' }] }],
  });
  assert.deepStrictEqual(out.messages[0], { role: 'system', content: 'sys' });
  assert.deepStrictEqual(out.messages[1], { role: 'user', content: 'hello' });
});

test('claude -> openai: tool_use becomes tool_calls, tool_result becomes tool message', () => {
  const out = translate_claude_to_openai({
    messages: [
      {
        role: 'assistant',
        content: [{ type: 'tool_use', id: 'tu1', name: 'read', input: { file: 'a.txt' } }],
      },
      {
        role: 'user',
        content: [{ type: 'tool_result', tool_use_id: 'tu1', content: 'data' }],
      },
    ],
  });
  assert.strictEqual(out.messages[0].role, 'assistant');
  assert.strictEqual(out.messages[0].tool_calls[0].function.name, 'read');
  assert.strictEqual(out.messages[0].tool_calls[0].function.arguments, '{"file":"a.txt"}');
  assert.deepStrictEqual(out.messages[1], { role: 'tool', tool_call_id: 'tu1', content: 'data' });
});

test('translate_request roundtrip through registry', () => {
  const body = {
    messages: [{ role: 'user', content: 'hi' }],
  };
  const claude = translate_request(FORMATS.OPENAI, FORMATS.CLAUDE, body);
  assert.ok(claude.messages);
  assert.deepStrictEqual(claude.messages[0].content, [{ type: 'text', text: 'hi' }]);
  const back = translate_request(FORMATS.CLAUDE, FORMATS.OPENAI, claude);
  assert.deepStrictEqual(back.messages[0], { role: 'user', content: 'hi' });
});

test('translate_request passthrough when same format', () => {
  const body = { messages: [] };
  assert.strictEqual(translate_request(FORMATS.OPENAI, FORMATS.OPENAI, body), body);
});
