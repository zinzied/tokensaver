import type { RequestBody } from './types.js';

export const FORMATS = {
  OPENAI: 'openai',
  OPENAI_RESPONSES: 'openai-responses',
  CLAUDE: 'claude',
  GEMINI: 'gemini',
  GEMINI_CLI: 'gemini-cli',
  VERTEX: 'vertex',
  CODEX: 'codex',
  ANTIGRAVITY: 'antigravity',
  KIRO: 'kiro',
  CURSOR: 'cursor',
  OLLAMA: 'ollama',
  COMMANDCODE: 'commandcode',
} as const;

export type FormatKey = (typeof FORMATS)[keyof typeof FORMATS];

type RequestTranslator = (body: RequestBody) => RequestBody;
type ResponseTranslator = (chunk: RequestBody, state?: unknown) => RequestBody | RequestBody[] | null;

const _requestRegistry: Record<string, RequestTranslator> = {};
const _responseRegistry: Record<string, ResponseTranslator> = {};

export function register(
  fromFmt: string,
  toFmt: string,
  requestFn?: RequestTranslator | null,
  responseFn?: ResponseTranslator | null
): string {
  const key = `${fromFmt}:${toFmt}`;
  if (requestFn) _requestRegistry[key] = requestFn;
  if (responseFn) _responseRegistry[key] = responseFn;
  return key;
}

export function detect_format(body: RequestBody | null | undefined): string {
  if (!body) return FORMATS.OPENAI;
  if (body.system !== undefined && body.system !== null) return FORMATS.CLAUDE;
  if (body.anthropic_version) return FORMATS.CLAUDE;
  if (Array.isArray(body.contents)) return FORMATS.GEMINI;
  if (typeof body.request === 'object' && body.request !== null && Array.isArray(body.request.contents)) {
    return FORMATS.ANTIGRAVITY;
  }
  if (typeof body.input === 'string' || Array.isArray(body.input)) return FORMATS.OPENAI_RESPONSES;
  return FORMATS.OPENAI;
}

export function translate_request(source_format: string, target_format: string, body: RequestBody): RequestBody {
  if (source_format === target_format) return body;
  let result = body;

  const directKey = `${source_format}:${target_format}`;
  if (_requestRegistry[directKey]) return _requestRegistry[directKey](result);

  if (source_format !== FORMATS.OPENAI) {
    const toOpenai = _requestRegistry[`${source_format}:${FORMATS.OPENAI}`];
    if (toOpenai) result = toOpenai(result);
  }

  if (target_format !== FORMATS.OPENAI) {
    const fromOpenai = _requestRegistry[`${FORMATS.OPENAI}:${target_format}`];
    if (fromOpenai) result = fromOpenai(result);
  }

  return result;
}

export function translate_response(target_format: string, source_format: string, chunk: RequestBody, state?: unknown): RequestBody[] {
  if (source_format === target_format) return [chunk];

  let results: RequestBody[] = [chunk];

  const directKey = `${target_format}:${source_format}`;
  if (_responseRegistry[directKey]) {
    const converted = _responseRegistry[directKey](chunk, state);
    if (Array.isArray(converted)) return converted;
    return converted ? [converted] : [];
  }

  if (target_format !== FORMATS.OPENAI) {
    const toOpenai = _responseRegistry[`${target_format}:${FORMATS.OPENAI}`];
    if (toOpenai) {
      const converted = toOpenai(chunk, state);
      if (converted) results = Array.isArray(converted) ? converted : [converted];
    }
  }

  if (source_format !== FORMATS.OPENAI) {
    const fromOpenai = _responseRegistry[`${FORMATS.OPENAI}:${source_format}`];
    if (fromOpenai) {
      const final: RequestBody[] = [];
      for (const r of results) {
        const converted = fromOpenai(r, state);
        if (converted) {
          if (Array.isArray(converted)) final.push(...converted);
          else final.push(converted);
        }
      }
      results = final;
    }
  }

  return results;
}

export function translate_openai_to_claude(body: RequestBody): RequestBody {
  const result: RequestBody = {};
  if (typeof body.system === 'string') {
    result.system = body.system;
  } else if (Array.isArray(body.messages)) {
    for (const m of body.messages) {
      if (m.role === 'system' && typeof m.content === 'string') {
        result.system = m.content;
        break;
      }
    }
  }

  const messages: RequestBody[] = [];
  for (const m of body.messages || []) {
    const role = m.role || '';
    if (role === 'system') continue;
    const claudeMsg: RequestBody = { role: role === 'assistant' ? 'assistant' : 'user' };
    const content = m.content === undefined ? '' : m.content;

    if (typeof content === 'string') {
      claudeMsg.content = [{ type: 'text', text: content }];
    } else if (Array.isArray(content)) {
      const parts: RequestBody[] = [];
      for (const c of content) {
        if (c.type === 'text') {
          parts.push({ type: 'text', text: c.text });
        } else if (c.type === 'image_url') {
          const url = c.image_url?.url || '';
          parts.push({
            type: 'image',
            source: {
              type: 'base64',
              media_type: 'image/jpeg',
              data: url.includes(',') ? url.split(',').pop() : url,
            },
          });
        }
      }
      claudeMsg.content = parts;
    }

    if (role === 'assistant' && m.tool_calls) {
      for (const tc of m.tool_calls) {
        claudeMsg.content.push({
          type: 'tool_use',
          id: tc.id || '',
          name: tc.function?.name || '',
          input: tc.function?.arguments || {},
        });
      }
    }

    if (role === 'tool') {
      claudeMsg.role = 'user';
      claudeMsg.content = [
        {
          type: 'tool_result',
          tool_use_id: m.tool_call_id || '',
          content: m.content === undefined ? '' : m.content,
        },
      ];
    }

    messages.push(claudeMsg);
  }

  result.messages = messages;
  result.max_tokens = body.max_tokens ?? 4096;
  if (body.temperature !== undefined && body.temperature !== null) {
    result.temperature = body.temperature;
  }

  return result;
}

export function translate_claude_to_openai(body: RequestBody): RequestBody {
  const messages: RequestBody[] = [];

  if (typeof body.system === 'string') {
    messages.push({ role: 'system', content: body.system });
  } else if (Array.isArray(body.system)) {
    const text = body.system
      .filter((b) => b && typeof b === 'object' && b.type === 'text')
      .map((b) => b.text || '')
      .join(' ');
    if (text) messages.push({ role: 'system', content: text });
  }

  for (const m of body.messages || []) {
    const role = m.role || '';
    const openaiRole = role === 'assistant' ? 'assistant' : 'user';

    let content = m.content === undefined ? '' : m.content;
    if (typeof content === 'string') {
      content = [{ type: 'text', text: content }];
    }

    const textParts: string[] = [];
    const toolCalls: RequestBody[] = [];
    for (const c of Array.isArray(content) ? content : []) {
      if (c.type === 'text') {
        textParts.push(c.text);
      } else if (c.type === 'tool_use') {
        toolCalls.push({
          id: c.id || '',
          type: 'function',
          function: {
            name: c.name || '',
            arguments: JSON.stringify(c.input ?? {}),
          },
        });
      } else if (c.type === 'tool_result') {
        messages.push({
          role: 'tool',
          tool_call_id: c.tool_use_id || '',
          content: c.content === undefined ? '' : c.content,
        });
        continue;
      }
    }

    const msg: RequestBody = {
      role: openaiRole,
      content: textParts.length ? textParts.join('\n') : '',
    };
    if (toolCalls.length) msg.tool_calls = toolCalls;
    messages.push(msg);
  }

  const result: RequestBody = { messages };
  if (body.max_tokens) result.max_tokens = body.max_tokens;
  if (body.temperature !== undefined && body.temperature !== null) {
    result.temperature = body.temperature;
  }

  return result;
}

register(FORMATS.OPENAI, FORMATS.CLAUDE, translate_openai_to_claude);
register(FORMATS.CLAUDE, FORMATS.OPENAI, translate_claude_to_openai, translate_claude_to_openai);
