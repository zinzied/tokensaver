export const CHARS_PER_TOKEN = 4;
export const BLOCK_OVERHEAD = 4;
export const ROLE_OVERHEAD = 4;

export function estimate_text_tokens(text: string): number {
  return Math.ceil(text.length / CHARS_PER_TOKEN);
}

export function estimate_json_tokens(json: string): number {
  return Math.ceil(json.length / CHARS_PER_TOKEN) + BLOCK_OVERHEAD;
}

export function estimate_message_tokens(message: {
  role?: string;
  content?: string | Array<{ type?: string; text?: string }>;
}): number {
  let tokens = ROLE_OVERHEAD;
  const content = message.content;
  if (typeof content === 'string') {
    tokens += estimate_text_tokens(content);
  } else if (Array.isArray(content)) {
    for (const block of content) {
      if (block?.type === 'text' && typeof block.text === 'string') {
        tokens += estimate_text_tokens(block.text) + BLOCK_OVERHEAD;
      }
    }
  }
  return tokens;
}

export function estimate_request_tokens(body: {
  messages?: Array<{
    role?: string;
    content?: string | Array<{ type?: string; text?: string }>;
  }>;
  system?: string;
  tools?: unknown[];
}): number {
  let tokens = 0;
  if (typeof body.system === 'string') {
    tokens += estimate_text_tokens(body.system) + ROLE_OVERHEAD;
  }
  if (Array.isArray(body.tools) && body.tools.length > 0) {
    tokens += estimate_json_tokens(JSON.stringify(body.tools));
  }
  if (Array.isArray(body.messages)) {
    for (const msg of body.messages) {
      tokens += estimate_message_tokens(msg);
    }
  }
  return tokens;
}
