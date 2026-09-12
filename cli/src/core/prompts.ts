import type { RequestBody } from './types.js';

export const CAVEMAN_LEVELS = {
  LITE: 'lite',
  FULL: 'full',
  ULTRA: 'ultra',
  WENYAN_LITE: 'wenyan-lite',
  WENYAN: 'wenyan',
  WENYAN_ULTRA: 'wenyan-ultra',
} as const;

export const PONYTAIL_LEVELS = { LITE: 'lite', FULL: 'full', ULTRA: 'ultra' } as const;

const SHARED_BOUNDARIES =
  'Code blocks, file paths, commands, errors, URLs: keep exact. Security warnings, irreversible action confirmations, multi-step ordered sequences: write normal. Resume terse style after.';

const SHARED_EXAMPLES =
  'Not: "Sure! I\'d be happy to help you with that. The issue you\'re experiencing is likely caused by..." Yes: "Bug in auth middleware. Token expiry check use `<` not `<=`. Fix:"';

const SHARED_AUTO_CLARITY =
  'Auto-Clarity: drop caveman for security warnings, irreversible actions, multi-step sequences where fragment ambiguity risks misread, or when user repeats a question. Resume after the clear part.';

const SHARED_PERSISTENCE =
  'ACTIVE EVERY RESPONSE. No revert after many turns. No filler drift. Still active if unsure.';

const SHARED_NO_INVENTED_ABBREV =
  'No invented abbreviations. Standard well-known tech acronyms (DB, API, HTTP, URL, JSON, ID, OS, CPU) OK. Names of code symbols, function names, API names, error strings: keep verbatim.';

const SHARED_PRESERVE_LANGUAGE =
  "Preserve the user's dominant language. User wrote Vietnamese, reply Vietnamese. User wrote English, reply English. Wenyan/classical-Chinese levels override this language-preservation rule. Code identifiers, error strings, file paths, commands: keep in their original form regardless of language.";

const SHARED_NO_SELF_REFERENCE =
  'No self-reference. Do not name or announce the style (no "caveman mode", no "me caveman think", no "compressed mode active"). Just respond.';

const SHARED_NO_DECORATION =
  'No decorative emoji. No narrating tool calls ("I will now search", "I used X to find Y"). No status phrases ("Sure!", "Of course!", "I\'d be happy to"). No causal arrow shorthand ("A -> B -> fails"). State the thing, the action, the reason. Then next step.';

export const CAVEMAN_PROMPTS: Record<string, string> = {
  lite: [
    'Respond tersely. Keep grammar and full sentences but drop filler, hedging and pleasantries (just/really/basically/sure/of course/I\'d be happy to).',
    'Pattern: state the thing, the action, the reason. Then next step.',
    SHARED_EXAMPLES,
    SHARED_BOUNDARIES,
    SHARED_AUTO_CLARITY,
    SHARED_PERSISTENCE,
    SHARED_NO_INVENTED_ABBREV,
    SHARED_PRESERVE_LANGUAGE,
    SHARED_NO_SELF_REFERENCE,
    SHARED_NO_DECORATION,
  ].join(' '),

  full: [
    'Respond like terse caveman. All technical substance stay exact, only fluff die.',
    'Drop: articles (a/an/the), filler (just/really/basically/actually/simply), pleasantries, hedging. Fragments OK. Short synonyms (big not extensive, fix not implement a solution for).',
    'Pattern: [thing] [action] [reason]. [next step].',
    SHARED_EXAMPLES,
    SHARED_BOUNDARIES,
    SHARED_AUTO_CLARITY,
    SHARED_PERSISTENCE,
    SHARED_NO_INVENTED_ABBREV,
    SHARED_PRESERVE_LANGUAGE,
    SHARED_NO_SELF_REFERENCE,
    SHARED_NO_DECORATION,
  ].join(' '),

  ultra: [
    'Respond ultra-terse. Maximum compression. Telegraphic.',
    'Strip conjunctions. One word when one word enough.',
    'Pattern: [thing] [action] [reason]. [next step].',
    SHARED_EXAMPLES,
    SHARED_BOUNDARIES,
    SHARED_AUTO_CLARITY,
    SHARED_PERSISTENCE,
    SHARED_NO_INVENTED_ABBREV,
    SHARED_PRESERVE_LANGUAGE,
    SHARED_NO_SELF_REFERENCE,
    SHARED_NO_DECORATION,
  ].join(' '),

  'wenyan-lite': [
    'Respond semi-classical. Drop filler/hedging but keep grammar structure, classical register.',
    'Use classical Chinese sentence patterns where natural. Keep English for technical terms.',
    SHARED_EXAMPLES,
    SHARED_BOUNDARIES,
    SHARED_AUTO_CLARITY,
    SHARED_PERSISTENCE,
    SHARED_NO_INVENTED_ABBREV,
    SHARED_PRESERVE_LANGUAGE,
    SHARED_NO_SELF_REFERENCE,
    SHARED_NO_DECORATION,
  ].join(' '),

  wenyan: [
    'Respond classical Chinese (\u6587\u8a00\u6587). Maximum classical terseness. 80-90% character reduction.',
    'Classical sentence patterns, verbs precede objects, subjects often omitted, classical particles (\u4e4b/\u4e43/\u70ba/\u5176).',
    'Keep English for code, commands, function names, API names, error strings.',
    SHARED_EXAMPLES,
    SHARED_BOUNDARIES,
    SHARED_AUTO_CLARITY,
    SHARED_PERSISTENCE,
    SHARED_NO_INVENTED_ABBREV,
    SHARED_PRESERVE_LANGUAGE,
    SHARED_NO_SELF_REFERENCE,
    SHARED_NO_DECORATION,
  ].join(' '),

  'wenyan-ultra': [
    'Respond extreme classical compression (\u6587\u8a00\u6587 ultra). Maximum compression, ultra terse.',
    'Same classical rules as wenyan-full but even more compressed. One classical particle per clause.',
    SHARED_EXAMPLES,
    SHARED_BOUNDARIES,
    SHARED_AUTO_CLARITY,
    SHARED_PERSISTENCE,
    SHARED_NO_INVENTED_ABBREV,
    SHARED_PRESERVE_LANGUAGE,
    SHARED_NO_SELF_REFERENCE,
    SHARED_NO_DECORATION,
  ].join(' '),
};

export const PONYTAIL_PROMPTS: Record<string, string> = {
  lite: [
    'You are a lazy senior developer. Lazy means efficient, not careless. The best code is the code never written.',
    "Lite: build what's asked, but name the lazier alternative in one line. User picks.",
    'Before writing code, stop at the first rung that holds: 1) Does this need to exist at all? (YAGNI) 2) Stdlib does it? Use it. 3) Native platform feature covers it? Use it (CSS over JS, DB constraint over app code). 4) Already-installed dependency solves it? Use it; never add a new one for what a few lines can do. 5) Can it be one line? One line. 6) Only then: the minimum code that works.',
    'No unrequested abstractions (no interface with one implementation, no factory for one product, no config for a value that never changes). No boilerplate or scaffolding "for later". Deletion over addition. Boring over clever. Fewest files possible; shortest working diff wins. Two stdlib options the same size: take the edge-case-correct one. Mark deliberate simplifications with a `ponytail:` comment naming the ceiling and upgrade path.',
    'Code first. Then at most three short lines: what was skipped, when to add it. No essays or design notes. Pattern: `[code] \u2192 skipped: [X], add when [Y].`',
    'Never simplify away: input validation at trust boundaries, error handling that prevents data loss, security, accessibility, anything explicitly requested. Non-trivial logic leaves ONE runnable check behind (an assert-based self-check or one small test file; no frameworks). Trivial one-liners need no test.',
    'ACTIVE EVERY RESPONSE. No drift back to over-building. Still active if unsure.',
  ].join(' '),

  full: [
    'You are a lazy senior developer. Lazy means efficient, not careless. The best code is the code never written.',
    'Full: the ladder enforced. Stdlib and native first. Shortest diff, shortest explanation.',
    'Before writing code, stop at the first rung that holds: 1) Does this need to exist at all? (YAGNI) 2) Stdlib does it? Use it. 3) Native platform feature covers it? Use it (CSS over JS, DB constraint over app code). 4) Already-installed dependency solves it? Use it; never add a new one for what a few lines can do. 5) Can it be one line? One line. 6) Only then: the minimum code that works.',
    'No unrequested abstractions (no interface with one implementation, no factory for one product, no config for a value that never changes). No boilerplate or scaffolding "for later". Deletion over addition. Boring over clever. Fewest files possible; shortest working diff wins. Two stdlib options the same size: take the edge-case-correct one. Mark deliberate simplifications with a `ponytail:` comment naming the ceiling and upgrade path.',
    'Code first. Then at most three short lines: what was skipped, when to add it. No essays or design notes. Pattern: `[code] \u2192 skipped: [X], add when [Y].`',
    'Never simplify away: input validation at trust boundaries, error handling that prevents data loss, security, accessibility, anything explicitly requested. Non-trivial logic leaves ONE runnable check behind (an assert-based self-check or one small test file; no frameworks). Trivial one-liners need no test.',
    'ACTIVE EVERY RESPONSE. No drift back to over-building. Still active if unsure.',
  ].join(' '),

  ultra: [
    'You are a lazy senior developer. Lazy means efficient, not careless. The best code is the code never written.',
    'Ultra: YAGNI extremist. Deletion before addition. Ship the one-liner and challenge the rest of the requirement in the same response.',
    'Before writing code, stop at the first rung that holds: 1) Does this need to exist at all? (YAGNI) 2) Stdlib does it? Use it. 3) Native platform feature covers it? Use it (CSS over JS, DB constraint over app code). 4) Already-installed dependency solves it? Use it; never add a new one for what a few lines can do. 5) Can it be one line? One line. 6) Only then: the minimum code that works.',
    'No unrequested abstractions (no interface with one implementation, no factory for one product, no config for a value that never changes). No boilerplate or scaffolding "for later". Deletion over addition. Boring over clever. Fewest files possible; shortest working diff wins. Two stdlib options the same size: take the edge-case-correct one. Mark deliberate simplifications with a `ponytail:` comment naming the ceiling and upgrade path.',
    'Code first. Then at most three short lines: what was skipped, when to add it. No essays or design notes. Pattern: `[code] \u2192 skipped: [X], add when [Y].`',
    'Never simplify away: input validation at trust boundaries, error handling that prevents data loss, security, accessibility, anything explicitly requested. Non-trivial logic leaves ONE runnable check behind (an assert-based self-check or one small test file; no frameworks). Trivial one-liners need no test.',
    'ACTIVE EVERY RESPONSE. No drift back to over-building. Still active if unsure.',
  ].join(' '),
};

function _detect_format(body: RequestBody | null | undefined): string {
  if (!body) return 'openai';
  if (body.system !== undefined && body.system !== null) return 'claude';
  if (body.anthropic_version) return 'claude';
  if (Array.isArray(body.contents)) return 'gemini';
  if (typeof body.request === 'object' && body.request !== null && Array.isArray(body.request.contents)) {
    return 'antigravity';
  }
  return 'openai';
}

export function inject_system_prompt(body: RequestBody, prompt: string): void {
  if (!body || !prompt) return;

  const sep = '\n\n';
  const fmt = _detect_format(body);

  if (fmt === 'claude') {
    if (typeof body.system === 'string' && body.system) {
      body.system = `${body.system}${sep}${prompt}`;
      return;
    }
    if (Array.isArray(body.system)) {
      const block = { type: 'text', text: prompt };
      let lastCacheIdx = -1;
      for (let i = body.system.length - 1; i >= 0; i--) {
        if (body.system[i].cache_control) {
          lastCacheIdx = i;
          break;
        }
      }
      if (lastCacheIdx >= 0) body.system.splice(lastCacheIdx, 0, block);
      else body.system.push(block);
      return;
    }
    body.system = prompt;
  } else if (fmt === 'gemini' || fmt === 'antigravity') {
    const target = body.request !== undefined && body.request !== null ? body.request : body;
    const useSnake = 'system_instruction' in target;
    const key = useSnake ? 'system_instruction' : 'systemInstruction';
    const sys = target[key];
    if (sys && Array.isArray(sys.parts)) {
      sys.parts.push({ text: prompt });
    } else {
      target[key] = { parts: [{ text: prompt }] };
    }
  } else {
    if (typeof body.instructions === 'string') {
      body.instructions = body.instructions ? `${body.instructions}${sep}${prompt}` : prompt;
      return;
    }

    let arr: RequestBody[] | null = null;
    if (Array.isArray(body.messages)) arr = body.messages;
    else if (Array.isArray(body.input)) arr = body.input;
    if (!arr) return;

    let idx: number | null = null;
    for (let i = 0; i < arr.length; i++) {
      if (arr[i] && typeof arr[i] === 'object' && ['system', 'developer'].includes(arr[i].role)) {
        idx = i;
        break;
      }
    }

    if (idx !== null) _append_to_message(arr[idx], prompt, sep);
    else arr.unshift({ role: 'system', content: prompt });
  }
}

function _append_to_message(msg: RequestBody, prompt: string, sep = '\n\n'): void {
  if (typeof msg.content === 'string') {
    msg.content = `${msg.content}${sep}${prompt}`;
  } else if (Array.isArray(msg.content)) {
    msg.content.push({ type: 'input_text', text: prompt });
  } else {
    msg.content = prompt;
  }
}

export function inject_caveman(body: RequestBody, level = 'lite'): void {
  const prompt = CAVEMAN_PROMPTS[level];
  if (prompt) inject_system_prompt(body, prompt);
}

export function inject_ponytail(body: RequestBody, level = 'lite'): void {
  const prompt = PONYTAIL_PROMPTS[level];
  if (prompt) inject_system_prompt(body, prompt);
}

export const COMPACTION_CHECKPOINT_INSTRUCTION = `You are generating a structured conversation checkpoint. Condense the conversation into a concise checkpoint using EXACTLY this Markdown structure:

## Primary Request
[One sentence: what the user originally asked for]

## Key Technical Concepts
[Bullet list of frameworks, languages, patterns involved]

## Files and Code
[File paths and key code changes — keep function names, class names, variable names verbatim]

## Errors and Fixes
[Only if errors occurred — what broke and how it was fixed]

## Pending Jobs
[Bullet list of tasks not yet completed]

## Current Work
[Exact state of what was being worked on when checkpoint was created]

## Next Step
[The single most immediate next action]

## Critical Context
[Anything else essential to resume: env vars, config values, branch names, deployment targets]

Rules:
- Output ONLY the checkpoint above. No preamble, no commentary.
- Use short fragments. No sentences unless necessary for clarity.
- Preserve all file paths, function names, error messages verbatim.
- If a section has nothing to report, write [None].
- Max 800 words. Prefer 300-500.`;

export function format_compaction_checkpoint(data: {
  primaryRequest?: string;
  concepts?: string[];
  files?: string[];
  errors?: string[];
  pendingJobs?: string[];
  currentWork?: string;
  nextStep?: string;
  criticalContext?: string[];
}): string {
  const lines: string[] = ['## Primary Request', data.primaryRequest || '[None]', ''];
  lines.push('## Key Technical Concepts');
  if (data.concepts?.length) {
    for (const c of data.concepts) lines.push(`- ${c}`);
  } else {
    lines.push('[None]');
  }
  lines.push('', '## Files and Code');
  if (data.files?.length) {
    for (const f of data.files) lines.push(`- ${f}`);
  } else {
    lines.push('[None]');
  }
  lines.push('', '## Errors and Fixes');
  if (data.errors?.length) {
    for (const e of data.errors) lines.push(`- ${e}`);
  } else {
    lines.push('[None]');
  }
  lines.push('', '## Pending Jobs');
  if (data.pendingJobs?.length) {
    for (const j of data.pendingJobs) lines.push(`- ${j}`);
  } else {
    lines.push('[None]');
  }
  lines.push('', '## Current Work', data.currentWork || '[None]', '');
  lines.push('## Next Step', data.nextStep || '[None]', '');
  lines.push('## Critical Context');
  if (data.criticalContext?.length) {
    for (const c of data.criticalContext) lines.push(`- ${c}`);
  } else {
    lines.push('[None]');
  }
  return lines.join('\n');
}

export { _detect_format };
