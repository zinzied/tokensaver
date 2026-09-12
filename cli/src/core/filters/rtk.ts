import type { CompressStats, FilterFn, RequestBody } from '../types.js';

export const RAW_CAP = 10 * 1024 * 1024;
export const MIN_COMPRESS_SIZE = 500;
export const DETECT_WINDOW = 1024;
export const GIT_DIFF_HUNK_MAX_LINES = 100;
export const GIT_LOG_MAX_LINES = 200;
export const DEDUP_LINE_MAX = 2000;
export const GREP_PER_FILE_MAX = 10;
export const FIND_PER_DIR_MAX = 10;
export const FIND_TOTAL_DIR_MAX = 20;
export const STATUS_MAX_FILES = 10;
export const STATUS_MAX_UNTRACKED = 10;
export const LS_EXT_SUMMARY_TOP = 5;
export const LS_NOISE_DIRS = new Set([
  'node_modules', '.git', 'target', '__pycache__',
  '.next', 'dist', 'build', '.cache', '.turbo',
  '.vercel', '.pytest_cache', '.mypy_cache', '.tox',
  '.venv', 'venv', 'env',
  'coverage', '.nyc_output', '.DS_Store', 'Thumbs.db',
  '.idea', '.vscode', '.vs', '*.egg-info', '.eggs',
]);
export const TREE_MAX_LINES = 200;
export const SEARCH_LIST_PER_DIR_MAX = 10;
export const SEARCH_LIST_TOTAL_DIR_MAX = 20;
export const SMART_TRUNCATE_HEAD = 120;
export const SMART_TRUNCATE_TAIL = 60;
export const SMART_TRUNCATE_MIN_LINES = 250;
export const READ_NUMBERED_MIN_HIT_RATIO = 0.7;

export const TOOL_RESULT_PRUNE_THRESHOLD = 8192;
export const TOOL_RESULT_PRUNE_HEAD = 4096;
export const TOOL_RESULT_PRUNE_TAIL = 1024;
export const TOOL_RESULT_PRUNE_MARKER = '\n\n[... tool result middle pruned ...]\n\n';

const RE_GIT_DIFF = /^diff --git /m;
const RE_GIT_DIFF_HUNK = /^@@ /m;
const RE_GIT_STATUS = /^On branch |^nothing to commit|^Changes (not |to be )|^Untracked files:/m;
const RE_GIT_LOG = /^[*|\/\\ ]*commit [0-9a-f]{7,40}$/m;
const RE_PORCELAIN = /^[ MADRCU?!][ MADRCU?!] \S/m;
const RE_BUILD_OUTPUT =
  /^(npm (warn|error|ERR!)|yarn (warn|error)|\s*Compiling\s+\S+|\s*Downloading\s+\S+|added \d+ package|\[ERROR\]|BUILD (SUCCESS|FAILED)|\s*Finished\s+|Successfully (installed|built)|ERROR:)/im;
const RE_TREE_GLYPH = /[├└]──|│  /;
const RE_LS_ROW = /^[-dlbcps][rwx-]{9}/gm;
const RE_LS_TOTAL = /^total \d+$/m;
const RE_SEARCH_LIST_HEADER = /^Result of search in '[^']*' \(total (\d+) files?\):/;
const RE_READ_NUMBERED_LINE = /^\s*\d+\|/;
const RE_CARGO_ERR_CONT = /^\s*(-->|\||\d+\s*\||=)/;

export function git_diff(diff: string, maxLines = 500): string {
  const result: string[] = [];
  let currentFile = '';
  let added = 0;
  let removed = 0;
  let inHunk = false;
  let hunkShown = 0;
  let hunkSkipped = 0;
  let wasTruncated = false;
  const maxHunkLines = GIT_DIFF_HUNK_MAX_LINES;
  const lines = String(diff).split('\n');

  for (const line of lines) {
    if (line.startsWith('diff --git')) {
      if (hunkSkipped > 0) {
        result.push(`  ... (${hunkSkipped} lines truncated)`);
        wasTruncated = true;
        hunkSkipped = 0;
      }
      if (currentFile && (added > 0 || removed > 0)) {
        result.push(`  +${added} -${removed}`);
      }
      const parts = line.split(' b/');
      currentFile = parts.length > 1 ? parts[1] : 'unknown';
      result.push(`\n${currentFile}`);
      added = 0;
      removed = 0;
      inHunk = false;
      hunkShown = 0;
    } else if (line.startsWith('@@')) {
      if (hunkSkipped > 0) {
        result.push(`  ... (${hunkSkipped} lines truncated)`);
        wasTruncated = true;
        hunkSkipped = 0;
      }
      inHunk = true;
      hunkShown = 0;
      result.push(`  ${line}`);
    } else if (inHunk) {
      if (line.startsWith('+') && !line.startsWith('+++')) {
        added += 1;
        if (hunkShown < maxHunkLines) {
          result.push(`  ${line}`);
          hunkShown += 1;
        } else {
          hunkSkipped += 1;
        }
      } else if (line.startsWith('-') && !line.startsWith('---')) {
        removed += 1;
        if (hunkShown < maxHunkLines) {
          result.push(`  ${line}`);
          hunkShown += 1;
        } else {
          hunkSkipped += 1;
        }
      } else if (hunkShown < maxHunkLines && !line.startsWith('\\')) {
        if (hunkShown > 0) {
          result.push(`  ${line}`);
          hunkShown += 1;
        }
      }
    }

    if (result.length >= maxLines) {
      result.push('\n... (more changes truncated)');
      wasTruncated = true;
      break;
    }
  }

  if (hunkSkipped > 0) {
    result.push(`  ... (${hunkSkipped} lines truncated)`);
    wasTruncated = true;
  }

  if (currentFile && (added > 0 || removed > 0)) {
    result.push(`  +${added} -${removed}`);
  }

  if (wasTruncated) {
    result.push('[full diff: rtk git diff --no-compact]');
  }

  return result.join('\n');
}

export function git_status(inputText: string): string {
  const lines = inputText.split('\n');
  if (!lines.length || (lines.length === 1 && !lines[0].trim())) {
    return 'Clean working tree';
  }

  let branch = '';
  const stagedFiles: string[] = [];
  const modifiedFiles: string[] = [];
  const untrackedFiles: string[] = [];
  let staged = 0;
  let modified = 0;
  let untracked = 0;
  let conflicts = 0;

  for (const raw of lines) {
    if (!raw.trim()) continue;

    const longBranch = /^On branch (\S+)/.exec(raw);
    if (longBranch) {
      branch = longBranch[1];
      continue;
    }

    if (raw.startsWith('##')) {
      branch = raw.slice(2).trim();
      continue;
    }

    if (raw.length >= 3 && /^[ MADRCU?!][ MADRCU?!] /.test(raw)) {
      const x = raw[0];
      const y = raw[1];
      const filePath = raw.slice(3);

      if (raw.slice(0, 2) === '??') {
        untracked += 1;
        untrackedFiles.push(filePath);
        continue;
      }

      if ('MADRC'.includes(x)) {
        staged += 1;
        stagedFiles.push(filePath);
      } else if (x === 'U') {
        conflicts += 1;
      }

      if ('MD'.includes(y)) {
        modified += 1;
        modifiedFiles.push(filePath);
      }
      continue;
    }

    const longMatch = /^\s*(modified|new file|deleted|renamed|both modified):\s+(.+)$/.exec(raw);
    if (longMatch) {
      const kind = longMatch[1];
      const p = longMatch[2].trim();
      if (kind === 'both modified') {
        conflicts += 1;
      } else if (kind === 'modified' || kind === 'deleted') {
        modified += 1;
        modifiedFiles.push(p);
      } else if (kind === 'new file' || kind === 'renamed') {
        staged += 1;
        stagedFiles.push(p);
      }
      continue;
    }
  }

  let out = '';
  if (branch) out += `* ${branch}\n`;

  if (staged > 0) {
    out += `+ Staged: ${staged} files\n`;
    for (const f of stagedFiles.slice(0, STATUS_MAX_FILES)) out += `   ${f}\n`;
    if (stagedFiles.length > STATUS_MAX_FILES) out += `   ... +${stagedFiles.length - STATUS_MAX_FILES} more\n`;
  }

  if (modified > 0) {
    out += `~ Modified: ${modified} files\n`;
    for (const f of modifiedFiles.slice(0, STATUS_MAX_FILES)) out += `   ${f}\n`;
    if (modifiedFiles.length > STATUS_MAX_FILES) out += `   ... +${modifiedFiles.length - STATUS_MAX_FILES} more\n`;
  }

  if (untracked > 0) {
    out += `? Untracked: ${untracked} files\n`;
    for (const f of untrackedFiles.slice(0, STATUS_MAX_UNTRACKED)) out += `   ${f}\n`;
    if (untrackedFiles.length > STATUS_MAX_UNTRACKED) out += `   ... +${untrackedFiles.length - STATUS_MAX_UNTRACKED} more\n`;
  }

  if (conflicts > 0) out += `conflicts: ${conflicts} files\n`;

  if (staged === 0 && modified === 0 && untracked === 0 && conflicts === 0) {
    out += 'clean — nothing to commit\n';
  }

  return out.replace(/\n+$/, '');
}

export function git_log(text: string, maxLines = GIT_LOG_MAX_LINES): string {
  if (!text) return '';
  const inputText = String(text);
  const lines = inputText.split('\n');
  const out: string[] = [];
  let skipped = 0;
  let inCommit = false;
  let subjectSeen = false;

  function pushLine(l: string): boolean {
    if (out.length < maxLines) {
      out.push(l);
      return true;
    }
    skipped += 1;
    return false;
  }

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '');
    const trimmed = line.trim();

    if (/^commit [0-9a-f]{7,40}$/i.test(trimmed) ||
        /^[*|\/\\ ]+commit [0-9a-f]{7,40}/i.test(trimmed)) {
      inCommit = true;
      subjectSeen = false;
      pushLine(line);
      continue;
    }

    if (inCommit) {
      if (/^[*|\/\\ ]*(Author|Date):/i.test(trimmed)) {
        pushLine(trimmed);
        continue;
      }
      if (!trimmed) continue;
      if (!subjectSeen && /^[*|\/\\ ]*    \S/.test(line)) {
        pushLine('  Subject: ' + trimmed);
        subjectSeen = true;
        continue;
      }
      if (/^\d+ file\w* changed/.test(trimmed)) {
        pushLine('  ' + trimmed);
        continue;
      }
      if (/^diff --git /.test(trimmed)) {
        pushLine('  ... diff body omitted');
        continue;
      }
      continue;
    }

    const graphMatch = /^[*|\/\\ ]+([0-9a-f]{7,40}\s+.+)/i.exec(trimmed);
    if (graphMatch) {
      pushLine(graphMatch[1]);
      continue;
    }

    if (/^[0-9a-f]{7,40}\s+/.test(trimmed)) {
      pushLine(trimmed);
      continue;
    }

    if (/^[*|\/\\ ]+$/.test(trimmed) && /[*|\/\\]/.test(trimmed)) {
      continue;
    }

    pushLine(trimmed);
  }

  if (skipped > 0) out.push(`... (${skipped} more lines)`);

  const result = out.join('\n');
  if (!result && inputText) return inputText;
  if (result.length > inputText.length) return inputText;
  return result;
}

export function grep(inputText: string): string {
  const byFile: Record<string, [string, string][]> = {};
  let total = 0;

  for (const line of inputText.split('\n')) {
    const first = line.indexOf(':');
    if (first === -1) continue;
    const second = line.indexOf(':', first + 1);
    if (second === -1) continue;
    const filepath = line.slice(0, first);
    const lineNumStr = line.slice(first + 1, second);
    const content = line.slice(second + 1);
    if (!/^\d+$/.test(lineNumStr)) continue;
    total += 1;
    if (!byFile[filepath]) byFile[filepath] = [];
    byFile[filepath].push([lineNumStr, content]);
  }

  if (total === 0) return inputText;

  const files = Object.keys(byFile).sort();
  let out = `${total} matches in ${files.length}F:\n\n`;

  for (const filepath of files) {
    const matches = byFile[filepath];
    out += `[file] ${filepath} (${matches.length}):\n`;
    for (const [lineNum, content] of matches.slice(0, GREP_PER_FILE_MAX)) {
      out += `  ${lineNum.padStart(4)}: ${content.trim()}\n`;
    }
    if (matches.length > GREP_PER_FILE_MAX) {
      out += `  +${matches.length - GREP_PER_FILE_MAX}\n`;
    }
    out += '\n';
  }

  return out;
}

export function find(inputText: string): string {
  const lines = inputText.split('\n').filter((l) => l.trim());
  if (!lines.length) return inputText;

  const byDir: Record<string, string[]> = {};

  for (const p of lines) {
    const lastSep = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'));
    let dirname: string;
    let basename: string;
    if (lastSep === -1) {
      dirname = '.';
      basename = p;
    } else {
      dirname = p.slice(0, lastSep) || '/';
      basename = p.slice(lastSep + 1);
    }
    if (!byDir[dirname]) byDir[dirname] = [];
    byDir[dirname].push(basename);
  }

  const dirs = Object.keys(byDir).sort();
  let out = `${lines.length} files in ${dirs.length} dirs:\n\n`;

  for (const dirname of dirs.slice(0, FIND_TOTAL_DIR_MAX)) {
    const files = byDir[dirname];
    const dirLabel = dirname.replace(/\\/g, '/');
    out += `${dirLabel}/  (${files.length})\n`;
    for (const f of files.slice(0, FIND_PER_DIR_MAX)) out += `  ${f}\n`;
    if (files.length > FIND_PER_DIR_MAX) out += `  +${files.length - FIND_PER_DIR_MAX}\n`;
  }

  if (dirs.length > FIND_TOTAL_DIR_MAX) {
    out += `\n+${dirs.length - FIND_TOTAL_DIR_MAX} more dirs\n`;
  }

  return out;
}

export function human_size(bytesVal: number): string {
  if (bytesVal >= 1048576) return `${(bytesVal / 1048576).toFixed(1)}M`;
  if (bytesVal >= 1024) return `${(bytesVal / 1024).toFixed(1)}K`;
  return `${bytesVal}B`;
}

interface LsParsed {
  fileType: string;
  size: number;
  name: string;
}

function _parse_ls_line(line: string): LsParsed | null {
  const m = /\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+(\d{4}|\d{2}:\d{2})\s+/.exec(line);
  if (!m) return null;
  const name = line.slice(m.index + m[0].length);
  const beforeDate = line.slice(0, m.index);
  const beforeParts = beforeDate.split(/\s+/).filter(Boolean);
  if (beforeParts.length < 4) return null;

  const perms = beforeParts[0];
  const fileType = perms[0];

  let size = 0;
  for (let i = beforeParts.length - 1; i >= 0; i--) {
    if (/^\d+$/.test(beforeParts[i])) {
      size = parseInt(beforeParts[i], 10);
      break;
    }
  }

  return { fileType, size, name };
}

export function ls(inputText: string): string {
  const dirs: string[] = [];
  const files: [string, string][] = [];
  const byExt: Record<string, number> = {};

  for (const line of inputText.split('\n')) {
    if (line.startsWith('total ') || !line) continue;
    const parsed = _parse_ls_line(line);
    if (!parsed) continue;
    if (parsed.name === '.' || parsed.name === '..') continue;
    if (LS_NOISE_DIRS.has(parsed.name)) continue;

    if (parsed.fileType === 'd') {
      dirs.push(parsed.name);
    } else if (parsed.fileType === '-' || parsed.fileType === 'l') {
      const dot = parsed.name.lastIndexOf('.');
      const ext = dot > 0 ? parsed.name.slice(dot) : 'no ext';
      byExt[ext] = (byExt[ext] || 0) + 1;
      files.push([parsed.name, human_size(parsed.size)]);
    }
  }

  if (!dirs.length && !files.length) return inputText;

  let out = '';
  for (const d of dirs) out += `${d}/\n`;
  for (const [name, size] of files) out += `${name}  ${size}\n`;

  let summary = `\nSummary: ${files.length} files, ${dirs.length} dirs`;
  if (Object.keys(byExt).length) {
    const extSorted = Object.entries(byExt).sort((a, b) => b[1] - a[1]);
    const parts = extSorted.slice(0, LS_EXT_SUMMARY_TOP).map(([e, c]) => `${c} ${e}`);
    summary += ' (' + parts.join(', ');
    if (extSorted.length > LS_EXT_SUMMARY_TOP) {
      summary += `, +${extSorted.length - LS_EXT_SUMMARY_TOP} more`;
    }
    summary += ')';
  }

  return out + summary;
}

export function tree(inputText: string): string {
  const lines = inputText.split('\n');
  if (!lines.length) return inputText;

  const filtered: string[] = [];
  for (const line of lines) {
    if (line.includes('director') && line.includes('file')) continue;
    if (line.trim() === '' && !filtered.length) continue;
    filtered.push(line);
  }

  while (filtered.length && filtered[filtered.length - 1].trim() === '') filtered.pop();

  if (filtered.length > TREE_MAX_LINES) {
    const cut = filtered.length - TREE_MAX_LINES;
    return filtered.slice(0, TREE_MAX_LINES).join('\n') + `\n... +${cut} more lines`;
  }

  return filtered.join('\n');
}

export function dedup_log(inputText: string): string {
  const lines = inputText.split('\n');
  const out: string[] = [];
  let prev: string | null = null;
  let runCount = 0;
  let blankStreak = 0;

  function flushRun() {
    if (prev !== null && runCount > 1) {
      out.push(`  ... (${runCount - 1} duplicate lines)`);
    }
  }

  for (const line of lines) {
    if (line.trim() === '') {
      if (blankStreak < 1) out.push(line);
      blankStreak += 1;
      flushRun();
      prev = null;
      runCount = 0;
      continue;
    }
    blankStreak = 0;
    if (line === prev) {
      runCount += 1;
      continue;
    }
    flushRun();
    out.push(line);
    prev = line;
    runCount = 1;
    if (out.length >= DEDUP_LINE_MAX) {
      out.push(`... (truncated at ${DEDUP_LINE_MAX} lines)`);
      return out.join('\n');
    }
  }

  flushRun();
  return out.join('\n');
}

export function smart_truncate(inputText: string): string {
  const lines = inputText.split('\n');
  if (lines.length < SMART_TRUNCATE_MIN_LINES) return inputText;

  const head = lines.slice(0, SMART_TRUNCATE_HEAD);
  const tail = lines.slice(-SMART_TRUNCATE_TAIL);
  const cut = lines.length - head.length - tail.length;
  return head.concat([`... +${cut} lines truncated`], tail).join('\n');
}

export function read_numbered(inputText: string): string {
  const lines = inputText.split('\n');
  if (lines.length < SMART_TRUNCATE_MIN_LINES) return inputText;

  const head = lines.slice(0, SMART_TRUNCATE_HEAD);
  const tail = lines.slice(-SMART_TRUNCATE_TAIL);
  const cut = lines.length - head.length - tail.length;
  return head.concat([`... +${cut} lines truncated (file continues)`], tail).join('\n');
}

export function search_list(inputText: string): string {
  const lines = inputText.split('\n');
  if (!lines.length) return inputText;

  const header = lines[0] || '';
  const rest = lines.slice(1);

  const paths: string[] = [];
  for (const raw of rest) {
    const t = raw.trim();
    if (!t.startsWith('- ')) continue;
    paths.push(t.slice(2));
  }

  if (!paths.length) return inputText;

  const byDir: Record<string, string[]> = {};
  for (const p of paths) {
    const slash = p.lastIndexOf('/');
    let dirname: string;
    let name: string;
    if (slash === -1) {
      dirname = '.';
      name = p;
    } else {
      dirname = p.slice(0, slash) || '/';
      name = p.slice(slash + 1);
    }
    if (!byDir[dirname]) byDir[dirname] = [];
    byDir[dirname].push(name);
  }

  const dirs = Object.keys(byDir).sort();
  let out = `${header}\n${paths.length} files in ${dirs.length} dirs:\n\n`;

  for (const dirname of dirs.slice(0, SEARCH_LIST_TOTAL_DIR_MAX)) {
    const names = byDir[dirname];
    out += `${dirname}/ (${names.length}):\n`;
    for (const n of names.slice(0, SEARCH_LIST_PER_DIR_MAX)) out += `  ${n}\n`;
    if (names.length > SEARCH_LIST_PER_DIR_MAX) out += `  +${names.length - SEARCH_LIST_PER_DIR_MAX}\n`;
    out += '\n';
  }

  if (dirs.length > SEARCH_LIST_TOTAL_DIR_MAX) {
    out += `+${dirs.length - SEARCH_LIST_TOTAL_DIR_MAX} more dirs\n`;
  }

  return out.replace(/\n+$/, '');
}

export function build_output(inputText: string): string {
  const lines = inputText.split('\n');
  if (!lines.length) return inputText;

  const errors: string[] = [];
  const warnings: string[] = [];
  const deprecations: string[] = [];
  let summary: string | null = null;
  let compilingCount = 0;
  let downloadingCount = 0;
  let inCargoError = false;
  const DEPRECATION_KEEP = 3;

  for (const line of lines) {
    const trimmed = line.trim();

    if (inCargoError) {
      if (!trimmed) {
        inCargoError = false;
        continue;
      }
      if (RE_CARGO_ERR_CONT.test(line)) {
        errors.push(line);
        continue;
      }
      inCargoError = false;
    }

    if (!trimmed) continue;

    if (/^npm (ERR!|error)/i.test(trimmed) || /^yarn error/i.test(trimmed)) {
      errors.push(line);
      continue;
    }

    if (/^npm warn deprecated/i.test(trimmed)) {
      deprecations.push(line);
      continue;
    }
    if (/^npm warn/i.test(trimmed) || /^yarn warn/i.test(trimmed)) {
      warnings.push(line);
      continue;
    }

    if (/^error(\[|:)/i.test(trimmed) || trimmed.startsWith('error -->')) {
      errors.push(line);
      inCargoError = true;
      continue;
    }

    if (/^warning(\[|:)/i.test(trimmed) || trimmed.startsWith('warning -->')) {
      warnings.push(line);
      inCargoError = true;
      continue;
    }

    if (/^ERROR:/i.test(trimmed)) {
      errors.push(line);
      continue;
    }

    if (/^\[ERROR\]/i.test(trimmed) || /^BUILD FAILED/i.test(trimmed)) {
      errors.push(line);
      continue;
    }

    if (/^\[WARNING\]/i.test(trimmed)) {
      warnings.push(line);
      continue;
    }

    if (/^\s*Compiling\s+\S+/i.test(trimmed)) {
      compilingCount += 1;
      continue;
    }
    if (/^\s*Downloading\s+\S+/i.test(trimmed) || /^Fetching\s+/i.test(trimmed)) {
      downloadingCount += 1;
      continue;
    }

    if (
      /^(added|removed|changed|audited|installed)\s+\d+\s+package/i.test(trimmed) ||
      /^\s*Finished\s+/i.test(trimmed) ||
      /^BUILD SUCCESS/i.test(trimmed) ||
      /^\d+\s+(vulnerabilities|packages?|warnings?|errors?)/i.test(trimmed) ||
      /^Successfully (installed|built)/i.test(trimmed) ||
      /^To address .* issues/i.test(trimmed) ||
      /^Run `npm (audit|fund)`/i.test(trimmed) ||
      /packages are looking for funding/i.test(trimmed)
    ) {
      summary = summary ? `${summary}\n${line}` : line;
      continue;
    }
  }

  let out = '';

  for (const d of deprecations.slice(0, DEPRECATION_KEEP)) out += `${d}\n`;
  if (deprecations.length > DEPRECATION_KEEP) {
    out += `... +${deprecations.length - DEPRECATION_KEEP} more deprecated packages\n`;
  }

  if (compilingCount > 0) out += `Compiled ${compilingCount} packages\n`;
  if (downloadingCount > 0) out += `Downloaded ${downloadingCount} packages\n`;

  for (const e of errors) out += `${e}\n`;

  for (const w of warnings.slice(0, 5)) out += `${w}\n`;
  if (warnings.length > 5) out += `... +${warnings.length - 5} more warnings\n`;

  if (summary) out += `${summary}\n`;

  const result = out.replace(/\n$/, '');
  return result || inputText;
}

export const FILTER_REGISTRY: Record<string, FilterFn> = {
  'git-diff': git_diff,
  'git-status': git_status,
  'git-log': git_log,
  grep,
  find,
  ls,
  tree,
  'dedup-log': dedup_log,
  'smart-truncate': smart_truncate,
  'read-numbered': read_numbered,
  'search-list': search_list,
  'build-output': build_output,
  'tool-result-prune': tool_result_prune,
};

function tool_result_prune(text: string): string {
  if (text.length <= TOOL_RESULT_PRUNE_THRESHOLD) return text;
  const head = text.slice(0, TOOL_RESULT_PRUNE_HEAD);
  const tail = text.slice(-TOOL_RESULT_PRUNE_TAIL);
  return head + TOOL_RESULT_PRUNE_MARKER + tail;
}

export function auto_detect_filter(text: string): FilterFn | null {
  const head = text.length > DETECT_WINDOW ? text.slice(0, DETECT_WINDOW) : text;

  if (RE_GIT_LOG.test(head)) return git_log;
  if (RE_GIT_DIFF.test(head) || RE_GIT_DIFF_HUNK.test(head)) return git_diff;
  if (RE_GIT_STATUS.test(head)) return git_status;

  if (RE_BUILD_OUTPUT.test(head)) return build_output;

  if (_is_mostly_porcelain(head)) return git_status;

  const lines = head.split('\n');
  const nonEmpty = lines.filter((l) => l.trim());

  const first5 = nonEmpty.slice(0, 5);
  if (first5.some(_is_grep_line)) return grep;

  if (nonEmpty.length >= 3 && nonEmpty.every(_is_path_like)) return find;

  if (RE_TREE_GLYPH.test(head)) return tree;

  if (RE_LS_TOTAL.test(head) || _count_matches(head, RE_LS_ROW) >= 3) return ls;

  if (RE_SEARCH_LIST_HEADER.test(head)) return search_list;

  if (lines.length >= SMART_TRUNCATE_MIN_LINES && _is_line_numbered(lines)) return read_numbered;

  if (nonEmpty.length >= 5) return dedup_log;

  if (text.split('\n').length >= SMART_TRUNCATE_MIN_LINES) return smart_truncate;

  if (text.length > TOOL_RESULT_PRUNE_THRESHOLD) return tool_result_prune;

  return null;
}

function _is_grep_line(line: string): boolean {
  const first = line.indexOf(':');
  if (first === -1) return false;
  const second = line.indexOf(':', first + 1);
  if (second === -1) return false;
  const lineno = line.slice(first + 1, second);
  return /^\d+$/.test(lineno);
}

function _is_path_like(line: string): boolean {
  const t = line.trim();
  if (!t) return false;
  if (/^[A-Za-z]:[\\/]/.test(t)) return true;
  if (t.includes(':')) return false;
  return t.startsWith('.') || t.startsWith('/') || t.includes('/');
}

function _is_mostly_porcelain(head: string): boolean {
  const lines = head.split('\n').filter((l) => l.trim());
  if (lines.length < 3) return false;
  let hits = 0;
  for (const l of lines) {
    if (RE_PORCELAIN.test(l)) hits += 1;
  }
  return hits / lines.length >= 0.6;
}

function _is_line_numbered(lines: string[]): boolean {
  let hits = 0;
  let nonEmpty = 0;
  const sample = lines.slice(0, 100);
  for (const l of sample) {
    if (!l) continue;
    nonEmpty += 1;
    if (RE_READ_NUMBERED_LINE.test(l)) hits += 1;
  }
  if (nonEmpty < 5) return false;
  return hits / nonEmpty >= READ_NUMBERED_MIN_HIT_RATIO;
}

function _count_matches(text: string, regex: RegExp): number {
  const m = text.match(regex);
  return m ? m.length : 0;
}

export function safe_apply(fn: FilterFn | null, text: string): string {
  if (typeof fn !== 'function') return text;
  try {
    const out = fn(text);
    if (typeof out !== 'string' || !out || out.length >= text.length) {
      return text;
    }
    return out;
  } catch (e) {
    const name = fn.name || 'anonymous';
    console.error(`[rtk] warning: filter '${name}' panicked — passing through raw output: ${(e as Error).message || e}`);
    return text;
  }
}

export function compress_text(text: string, stats: CompressStats): string {
  const bytesIn = text.length;
  stats.bytesBefore += bytesIn;

  if (bytesIn < MIN_COMPRESS_SIZE || bytesIn > RAW_CAP) {
    stats.bytesAfter += bytesIn;
    return text;
  }

  const fn = auto_detect_filter(text);
  if (fn === null) {
    stats.bytesAfter += bytesIn;
    return text;
  }

  const out = safe_apply(fn, text);

  if (!out || out.length === 0 || out.length >= bytesIn) {
    stats.bytesAfter += bytesIn;
    return text;
  }

  stats.bytesAfter += out.length;
  stats.hits.push({
    shape: 'auto-detected',
    filter: fn.name,
    saved: bytesIn - out.length,
  });
  return out;
}

function _compress_kiro(body: RequestBody): CompressStats | null {
  const stats: CompressStats = { bytesBefore: 0, bytesAfter: 0, hits: [] };
  try {
    const state = body.conversationState || {};
    const allMessages = [...(state.history || [])];
    if (state.currentMessage) allMessages.push(state.currentMessage);

    for (const msg of allMessages) {
      if (!msg || typeof msg !== 'object') continue;
      const toolResults = msg.userInputMessage?.userInputMessageContext?.toolResults;
      if (!Array.isArray(toolResults)) continue;

      for (const tr of toolResults) {
        if (tr.status === 'error') continue;
        const content = tr.content;
        if (!Array.isArray(content)) continue;
        for (const part of content) {
          if (part && typeof part === 'object' && typeof part.text === 'string') {
            part.text = compress_text(part.text, stats);
          }
        }
      }
    }
  } catch (e) {
    console.error(`[RTK] compressKiroFormat error: ${(e as Error).message || e}`);
    return null;
  }
  return stats;
}

export function compress_messages(body: RequestBody, enabled = true): CompressStats | null {
  if (!enabled) return null;
  if (!body) return null;

  if ('conversationState' in body) return _compress_kiro(body);

  let items: any[] | null = null;
  if (Array.isArray(body.messages)) items = body.messages;
  else if (Array.isArray(body.input)) items = body.input;
  if (items === null) return null;

  const stats: CompressStats = { bytesBefore: 0, bytesAfter: 0, hits: [] };

  try {
    for (const msg of items) {
      if (!msg) continue;

      if (msg.type === 'function_call_output') {
        if (typeof msg.output === 'string') {
          msg.output = compress_text(msg.output, stats);
        } else if (Array.isArray(msg.output)) {
          for (const part of msg.output) {
            if (part && typeof part === 'object' && part.type === 'input_text' && typeof part.text === 'string') {
              part.text = compress_text(part.text, stats);
            }
          }
        }
        continue;
      }

      if (msg.role === 'tool' && typeof msg.content === 'string') {
        msg.content = compress_text(msg.content, stats);
        continue;
      }

      const content = msg.content;
      if (!Array.isArray(content)) continue;

      if (msg.role === 'tool') {
        for (const part of content) {
          if (part && typeof part === 'object' && part.type === 'text' && typeof part.text === 'string') {
            part.text = compress_text(part.text, stats);
          }
        }
        continue;
      }

      for (const block of content) {
        if (!block || typeof block !== 'object' || block.type !== 'tool_result') continue;
        if (block.is_error) continue;

        if (typeof block.content === 'string') {
          block.content = compress_text(block.content, stats);
        } else if (Array.isArray(block.content)) {
          for (const part of block.content) {
            if (part && typeof part === 'object' && part.type === 'text' && typeof part.text === 'string') {
              part.text = compress_text(part.text, stats);
            }
          }
        }
      }
    }
  } catch (e) {
    console.error(`[RTK] compressMessages error: ${(e as Error).message || e}`);
    return null;
  }

  return stats;
}

export function format_rtk_log(stats: CompressStats | null): string | null {
  if (!stats || !stats.hits || !stats.hits.length) return null;
  const saved = stats.bytesBefore - stats.bytesAfter;
  const pct = stats.bytesBefore > 0 ? ((saved / stats.bytesBefore) * 100).toFixed(1) : '0';
  const filters = [...new Set(stats.hits.map((h) => h.filter))].join(',');
  return `[RTK] saved ${saved}B / ${stats.bytesBefore}B (${pct}%) via [${filters}] hits=${stats.hits.length}`;
}
