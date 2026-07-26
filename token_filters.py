import re
import math

RAW_CAP = 10 * 1024 * 1024
MIN_COMPRESS_SIZE = 500
DETECT_WINDOW = 1024
GIT_DIFF_HUNK_MAX_LINES = 100
GIT_LOG_MAX_LINES = 200
DEDUP_LINE_MAX = 2000
GREP_PER_FILE_MAX = 10
FIND_PER_DIR_MAX = 10
FIND_TOTAL_DIR_MAX = 20
STATUS_MAX_FILES = 10
STATUS_MAX_UNTRACKED = 10
LS_EXT_SUMMARY_TOP = 5
LS_NOISE_DIRS = {
    "node_modules", ".git", "target", "__pycache__",
    ".next", "dist", "build", ".cache", ".turbo",
    ".vercel", ".pytest_cache", ".mypy_cache", ".tox",
    ".venv", "venv", "env",
    "coverage", ".nyc_output", ".DS_Store", "Thumbs.db",
    ".idea", ".vscode", ".vs", "*.egg-info", ".eggs"
}
TREE_MAX_LINES = 200
SEARCH_LIST_PER_DIR_MAX = 10
SEARCH_LIST_TOTAL_DIR_MAX = 20
SMART_TRUNCATE_HEAD = 120
SMART_TRUNCATE_TAIL = 60
SMART_TRUNCATE_MIN_LINES = 250
READ_NUMBERED_MIN_HIT_RATIO = 0.7

RE_GIT_DIFF = re.compile(r'^diff --git ', re.MULTILINE)
RE_GIT_DIFF_HUNK = re.compile(r'^@@ ', re.MULTILINE)
RE_GIT_STATUS = re.compile(r'^On branch |^nothing to commit|^Changes (not |to be )|^Untracked files:', re.MULTILINE)
RE_GIT_LOG = re.compile(r'^[*|/\\ ]*commit [0-9a-f]{7,40}$', re.MULTILINE)
RE_PORCELAIN = re.compile(r'^[ MADRCU?!][ MADRCU?!] \S', re.MULTILINE)
RE_BUILD_OUTPUT = re.compile(
    r'^(npm (warn|error|ERR!)|yarn (warn|error)|\s*Compiling\s+\S+|\s*Downloading\s+\S+|'
    r'added \d+ package|\[ERROR\]|BUILD (SUCCESS|FAILED)|\s*Finished\s+|'
    r'Successfully (installed|built)|ERROR:)',
    re.IGNORECASE | re.MULTILINE
)
RE_TREE_GLYPH = re.compile(r'[├└]──|│  ')
RE_LS_ROW = re.compile(r'^[-dlbcps][rwx-]{9}', re.MULTILINE)
RE_LS_TOTAL = re.compile(r'^total \d+$', re.MULTILINE)
RE_SEARCH_LIST_HEADER = re.compile(r"^Result of search in '[^']*' \(total (\d+) files?\):")
RE_READ_NUMBERED_LINE = re.compile(r'^\s*\d+\|')


def git_diff(diff, max_lines=500):
    result = []
    current_file = ""
    added = 0
    removed = 0
    in_hunk = False
    hunk_shown = 0
    hunk_skipped = 0
    was_truncated = False
    max_hunk_lines = GIT_DIFF_HUNK_MAX_LINES
    lines = diff.split("\n")

    for line in lines:
        if line.startswith("diff --git"):
            if hunk_skipped > 0:
                result.append(f"  ... ({hunk_skipped} lines truncated)")
                was_truncated = True
                hunk_skipped = 0
            if current_file and (added > 0 or removed > 0):
                result.append(f"  +{added} -{removed}")
            parts = line.split(" b/")
            current_file = parts[1] if len(parts) > 1 else "unknown"
            result.append(f"\n{current_file}")
            added = 0
            removed = 0
            in_hunk = False
            hunk_shown = 0
        elif line.startswith("@@"):
            if hunk_skipped > 0:
                result.append(f"  ... ({hunk_skipped} lines truncated)")
                was_truncated = True
                hunk_skipped = 0
            in_hunk = True
            hunk_shown = 0
            result.append(f"  {line}")
        elif in_hunk:
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
                if hunk_shown < max_hunk_lines:
                    result.append(f"  {line}")
                    hunk_shown += 1
                else:
                    hunk_skipped += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
                if hunk_shown < max_hunk_lines:
                    result.append(f"  {line}")
                    hunk_shown += 1
                else:
                    hunk_skipped += 1
            elif hunk_shown < max_hunk_lines and not line.startswith("\\"):
                if hunk_shown > 0:
                    result.append(f"  {line}")
                    hunk_shown += 1

        if len(result) >= max_lines:
            result.append("\n... (more changes truncated)")
            was_truncated = True
            break

    if hunk_skipped > 0:
        result.append(f"  ... ({hunk_skipped} lines truncated)")
        was_truncated = True

    if current_file and (added > 0 or removed > 0):
        result.append(f"  +{added} -{removed}")

    if was_truncated:
        result.append("[full diff: rtk git diff --no-compact]")

    return "\n".join(result)


def git_status(input_text):
    lines = input_text.split("\n")
    if not lines or (len(lines) == 1 and not lines[0].strip()):
        return "Clean working tree"

    branch = ""
    staged_files = []
    modified_files = []
    untracked_files = []
    staged = 0
    modified = 0
    untracked = 0
    conflicts = 0

    for raw in lines:
        if not raw.strip():
            continue

        long_branch = re.match(r'^On branch (\S+)', raw)
        if long_branch:
            branch = long_branch.group(1)
            continue

        if raw.startswith("##"):
            branch = raw[2:].strip()
            continue

        if len(raw) >= 3 and re.match(r'^[ MADRCU?!][ MADRCU?!] ', raw):
            x, y = raw[0], raw[1]
            file_path = raw[3:]

            if raw[:2] == "??":
                untracked += 1
                untracked_files.append(file_path)
                continue

            if x in "MADRC":
                staged += 1
                staged_files.append(file_path)
            elif x == "U":
                conflicts += 1

            if y in "MD":
                modified += 1
                modified_files.append(file_path)
            continue

        long_match = re.match(r'^\s*(modified|new file|deleted|renamed|both modified):\s+(.+)$', raw)
        if long_match:
            kind = long_match.group(1)
            path = long_match.group(2).strip()
            if kind == "both modified":
                conflicts += 1
            elif kind in ("modified", "deleted"):
                modified += 1
                modified_files.append(path)
            elif kind in ("new file", "renamed"):
                staged += 1
                staged_files.append(path)
            continue

    out = ""
    if branch:
        out += f"* {branch}\n"

    if staged > 0:
        out += f"+ Staged: {staged} files\n"
        for f in staged_files[:STATUS_MAX_FILES]:
            out += f"   {f}\n"
        if len(staged_files) > STATUS_MAX_FILES:
            out += f"   ... +{len(staged_files) - STATUS_MAX_FILES} more\n"

    if modified > 0:
        out += f"~ Modified: {modified} files\n"
        for f in modified_files[:STATUS_MAX_FILES]:
            out += f"   {f}\n"
        if len(modified_files) > STATUS_MAX_FILES:
            out += f"   ... +{len(modified_files) - STATUS_MAX_FILES} more\n"

    if untracked > 0:
        out += f"? Untracked: {untracked} files\n"
        for f in untracked_files[:STATUS_MAX_UNTRACKED]:
            out += f"   {f}\n"
        if len(untracked_files) > STATUS_MAX_UNTRACKED:
            out += f"   ... +{len(untracked_files) - STATUS_MAX_UNTRACKED} more\n"

    if conflicts > 0:
        out += f"conflicts: {conflicts} files\n"

    if staged == 0 and modified == 0 and untracked == 0 and conflicts == 0:
        out += "clean \u2014 nothing to commit\n"

    return out.rstrip("\n")


def git_log(text, max_lines=GIT_LOG_MAX_LINES):
    if not text:
        return ""
    input_text = str(text)
    lines = input_text.split("\n")
    out = []
    skipped = 0
    in_commit = False
    subject_seen = False

    def push_line(l):
        nonlocal skipped
        if len(out) < max_lines:
            out.append(l)
            return True
        skipped += 1
        return False

    for raw in lines:
        line = raw.rstrip()
        trimmed = line.strip()

        if re.match(r'^commit [0-9a-f]{7,40}$', trimmed, re.IGNORECASE) or \
           re.match(r'^[*|/\\ ]+commit [0-9a-f]{7,40}', trimmed, re.IGNORECASE):
            in_commit = True
            subject_seen = False
            push_line(line)
            continue

        if in_commit:
            if re.match(r'^[*|/\\ ]*(Author|Date):', trimmed, re.IGNORECASE):
                push_line(trimmed)
                continue
            if not trimmed:
                continue
            if not subject_seen and re.match(r'^[*|/\\ ]*    \S', line):
                push_line("  Subject: " + trimmed)
                subject_seen = True
                continue
            if re.match(r'^\d+ file\w* changed', trimmed):
                push_line("  " + trimmed)
                continue
            if re.match(r'^diff --git ', trimmed):
                push_line("  ... diff body omitted")
                continue
            continue

        graph_match = re.match(r'^[*|/\\ ]+([0-9a-f]{7,40}\s+.+)', trimmed, re.IGNORECASE)
        if graph_match:
            push_line(graph_match.group(1))
            continue

        if re.match(r'^[0-9a-f]{7,40}\s+', trimmed):
            push_line(trimmed)
            continue

        if re.match(r'^[*|/\\ ]+$', trimmed) and re.search(r'[*|/\\]', trimmed):
            continue

        push_line(trimmed)

    if skipped > 0:
        out.append(f"... ({skipped} more lines)")

    result = "\n".join(out)
    if not result and input_text:
        return input_text
    if len(result) > len(input_text):
        return input_text
    return result


def grep(input_text):
    by_file = {}
    total = 0

    for line in input_text.split("\n"):
        first = line.find(":")
        if first == -1:
            continue
        second = line.find(":", first + 1)
        if second == -1:
            continue
        filepath = line[:first]
        line_num_str = line[first + 1:second]
        content = line[second + 1:]
        if not re.match(r'^\d+$', line_num_str):
            continue
        total += 1
        by_file.setdefault(filepath, []).append((line_num_str, content))

    if total == 0:
        return input_text

    files = sorted(by_file.keys())
    out = f"{total} matches in {len(files)}F:\n\n"

    for filepath in files:
        matches = by_file[filepath]
        out += f"[file] {filepath} ({len(matches)}):\n"
        show = matches[:GREP_PER_FILE_MAX]
        for line_num, content in show:
            out += f"  {line_num.rjust(4)}: {content.strip()}\n"
        if len(matches) > GREP_PER_FILE_MAX:
            out += f"  +{len(matches) - GREP_PER_FILE_MAX}\n"
        out += "\n"

    return out


def find(input_text):
    lines = [l for l in input_text.split("\n") if l.strip()]
    if not lines:
        return input_text

    by_dir = {}

    for path in lines:
        last_sep = max(path.rfind("/"), path.rfind("\\"))
        if last_sep == -1:
            dirname = "."
            basename = path
        else:
            dirname = path[:last_sep] or "/"
            basename = path[last_sep + 1:]
        by_dir.setdefault(dirname, []).append(basename)

    dirs = sorted(by_dir.keys())
    out = f"{len(lines)} files in {len(dirs)} dirs:\n\n"

    show_dirs = dirs[:FIND_TOTAL_DIR_MAX]
    for dirname in show_dirs:
        files = by_dir[dirname]
        dir_label = dirname.replace("\\", "/")
        out += f"{dir_label}/  ({len(files)})\n"
        for f in files[:FIND_PER_DIR_MAX]:
            out += f"  {f}\n"
        if len(files) > FIND_PER_DIR_MAX:
            out += f"  +{len(files) - FIND_PER_DIR_MAX}\n"

    if len(dirs) > FIND_TOTAL_DIR_MAX:
        out += f"\n+{len(dirs) - FIND_TOTAL_DIR_MAX} more dirs\n"

    return out


def human_size(bytes_val):
    if bytes_val >= 1_048_576:
        return f"{bytes_val / 1_048_576:.1f}M"
    if bytes_val >= 1024:
        return f"{bytes_val / 1024:.1f}K"
    return f"{bytes_val}B"


def _parse_ls_line(line):
    m = re.search(r'\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+(\d{4}|\d{2}:\d{2})\s+', line)
    if not m:
        return None
    name = line[m.end():]
    before_date = line[:m.start()]
    before_parts = [p for p in re.split(r'\s+', before_date) if p]
    if len(before_parts) < 4:
        return None

    perms = before_parts[0]
    file_type = perms[0]

    size = 0
    for i in range(len(before_parts) - 1, -1, -1):
        try:
            n = int(before_parts[i])
            if str(n) == before_parts[i]:
                size = n
                break
        except ValueError:
            continue

    return {"fileType": file_type, "size": size, "name": name}


def ls(input_text):
    dirs = []
    files = []
    by_ext = {}

    for line in input_text.split("\n"):
        if line.startswith("total ") or not line:
            continue
        parsed = _parse_ls_line(line)
        if not parsed:
            continue
        if parsed["name"] in (".", ".."):
            continue
        if parsed["name"] in LS_NOISE_DIRS:
            continue

        if parsed["fileType"] == "d":
            dirs.append(parsed["name"])
        elif parsed["fileType"] in ("-", "l"):
            dot = parsed["name"].rfind(".")
            ext = parsed["name"][dot:] if dot > 0 else "no ext"
            by_ext[ext] = by_ext.get(ext, 0) + 1
            files.append((parsed["name"], human_size(parsed["size"])))

    if not dirs and not files:
        return input_text

    out = ""
    for d in dirs:
        out += f"{d}/\n"
    for name, size in files:
        out += f"{name}  {size}\n"

    summary = f"\nSummary: {len(files)} files, {len(dirs)} dirs"
    if by_ext:
        ext_sorted = sorted(by_ext.items(), key=lambda x: -x[1])
        parts = [f"{c} {e}" for e, c in ext_sorted[:LS_EXT_SUMMARY_TOP]]
        summary += " (" + ", ".join(parts)
        if len(ext_sorted) > LS_EXT_SUMMARY_TOP:
            summary += f", +{len(ext_sorted) - LS_EXT_SUMMARY_TOP} more"
        summary += ")"

    return out + summary


def tree(input_text):
    lines = input_text.split("\n")
    if not lines:
        return input_text

    filtered = []
    for line in lines:
        if "director" in line and "file" in line:
            continue
        if line.strip() == "" and not filtered:
            continue
        filtered.append(line)

    while filtered and filtered[-1].strip() == "":
        filtered.pop()

    if len(filtered) > TREE_MAX_LINES:
        cut = len(filtered) - TREE_MAX_LINES
        return "\n".join(filtered[:TREE_MAX_LINES]) + f"\n... +{cut} more lines"

    return "\n".join(filtered)


def dedup_log(input_text):
    lines = input_text.split("\n")
    out = []
    prev = None
    run_count = 0
    blank_streak = 0

    def flush_run():
        nonlocal run_count
        if prev is not None and run_count > 1:
            out.append(f"  ... ({run_count - 1} duplicate lines)")

    for line in lines:
        if line.strip() == "":
            if blank_streak < 1:
                out.append(line)
            blank_streak += 1
            flush_run()
            prev = None
            run_count = 0
            continue
        blank_streak = 0
        if line == prev:
            run_count += 1
            continue
        flush_run()
        out.append(line)
        prev = line
        run_count = 1
        if len(out) >= DEDUP_LINE_MAX:
            out.append(f"... (truncated at {DEDUP_LINE_MAX} lines)")
            return "\n".join(out)

    flush_run()
    return "\n".join(out)


def smart_truncate(input_text):
    lines = input_text.split("\n")
    if len(lines) < SMART_TRUNCATE_MIN_LINES:
        return input_text

    head = lines[:SMART_TRUNCATE_HEAD]
    tail = lines[-SMART_TRUNCATE_TAIL:]
    cut = len(lines) - len(head) - len(tail)
    return "\n".join(head + [f"... +{cut} lines truncated"] + tail)


def read_numbered(input_text):
    lines = input_text.split("\n")
    if len(lines) < SMART_TRUNCATE_MIN_LINES:
        return input_text

    head = lines[:SMART_TRUNCATE_HEAD]
    tail = lines[-SMART_TRUNCATE_TAIL:]
    cut = len(lines) - len(head) - len(tail)
    return "\n".join(head + [f"... +{cut} lines truncated (file continues)"] + tail)


def search_list(input_text):
    lines = input_text.split("\n")
    if not lines:
        return input_text

    header = lines[0] or ""
    rest = lines[1:]

    paths = []
    for raw in rest:
        t = raw.strip()
        if not t.startswith("- "):
            continue
        paths.append(t[2:])

    if not paths:
        return input_text

    by_dir = {}
    for p in paths:
        slash = p.rfind("/")
        if slash == -1:
            dirname = "."
            name = p
        else:
            dirname = p[:slash] or "/"
            name = p[slash + 1:]
        by_dir.setdefault(dirname, []).append(name)

    dirs = sorted(by_dir.keys())
    out = f"{header}\n{len(paths)} files in {len(dirs)} dirs:\n\n"

    for dirname in dirs[:SEARCH_LIST_TOTAL_DIR_MAX]:
        names = by_dir[dirname]
        out += f"{dirname}/ ({len(names)}):\n"
        for n in names[:SEARCH_LIST_PER_DIR_MAX]:
            out += f"  {n}\n"
        if len(names) > SEARCH_LIST_PER_DIR_MAX:
            out += f"  +{len(names) - SEARCH_LIST_PER_DIR_MAX}\n"
        out += "\n"

    if len(dirs) > SEARCH_LIST_TOTAL_DIR_MAX:
        out += f"+{len(dirs) - SEARCH_LIST_TOTAL_DIR_MAX} more dirs\n"

    return out.rstrip("\n")


def build_output(input_text):
    lines = input_text.split("\n")
    if not lines:
        return input_text

    errors = []
    warnings = []
    deprecations = []
    summary = None
    compiling_count = 0
    downloading_count = 0
    in_cargo_error = False
    RE_CARGO_ERR_CONT = re.compile(r'^\s*(-->|\||\d+\s*\||=)')
    DEPRECATION_KEEP = 3

    for line in lines:
        trimmed = line.strip()

        if in_cargo_error:
            if not trimmed:
                in_cargo_error = False
                continue
            if RE_CARGO_ERR_CONT.match(line):
                errors.append(line)
                continue
            in_cargo_error = False

        if not trimmed:
            continue

        if re.match(r'^npm (ERR!|error)', trimmed, re.IGNORECASE) or re.match(r'^yarn error', trimmed, re.IGNORECASE):
            errors.append(line)
            continue

        if re.match(r'^npm warn deprecated', trimmed, re.IGNORECASE):
            deprecations.append(line)
            continue
        if re.match(r'^npm warn', trimmed, re.IGNORECASE) or re.match(r'^yarn warn', trimmed, re.IGNORECASE):
            warnings.append(line)
            continue

        if re.match(r'^error(\[|:)', trimmed, re.IGNORECASE) or trimmed.startswith("error -->"):
            errors.append(line)
            in_cargo_error = True
            continue

        if re.match(r'^warning(\[|:)', trimmed, re.IGNORECASE) or trimmed.startswith("warning -->"):
            warnings.append(line)
            in_cargo_error = True
            continue

        if re.match(r'^ERROR:', trimmed, re.IGNORECASE):
            errors.append(line)
            continue

        if re.match(r'^\[ERROR\]', trimmed, re.IGNORECASE) or re.match(r'^BUILD FAILED', trimmed, re.IGNORECASE):
            errors.append(line)
            continue

        if re.match(r'^\[WARNING\]', trimmed, re.IGNORECASE):
            warnings.append(line)
            continue

        if re.match(r'^\s*Compiling\s+\S+', trimmed, re.IGNORECASE):
            compiling_count += 1
            continue
        if re.match(r'^\s*Downloading\s+\S+', trimmed, re.IGNORECASE) or re.match(r'^Fetching\s+', trimmed, re.IGNORECASE):
            downloading_count += 1
            continue

        if (re.match(r'^(added|removed|changed|audited|installed)\s+\d+\s+package', trimmed, re.IGNORECASE) or
            re.match(r'^\s*Finished\s+', trimmed, re.IGNORECASE) or
            re.match(r'^BUILD SUCCESS', trimmed, re.IGNORECASE) or
            re.match(r'^\d+\s+(vulnerabilities|packages?|warnings?|errors?)', trimmed, re.IGNORECASE) or
            re.match(r'^Successfully (installed|built)', trimmed, re.IGNORECASE) or
            re.match(r'^To address .* issues', trimmed, re.IGNORECASE) or
            re.match(r'^Run `npm (audit|fund)`', trimmed, re.IGNORECASE) or
            re.match(r'packages are looking for funding', trimmed, re.IGNORECASE)):
            summary = f"{summary}\n{line}" if summary else line
            continue

    out = ""

    keep_dep = deprecations[:DEPRECATION_KEEP]
    for d in keep_dep:
        out += f"{d}\n"
    if len(deprecations) > DEPRECATION_KEEP:
        out += f"... +{len(deprecations) - DEPRECATION_KEEP} more deprecated packages\n"

    if compiling_count > 0:
        out += f"Compiled {compiling_count} packages\n"
    if downloading_count > 0:
        out += f"Downloaded {downloading_count} packages\n"

    for e in errors:
        out += f"{e}\n"

    keep_warnings = warnings[:5]
    for w in keep_warnings:
        out += f"{w}\n"
    if len(warnings) > 5:
        out += f"... +{len(warnings) - 5} more warnings\n"

    if summary:
        out += f"{summary}\n"

    result = out.rstrip("\n")
    return result if result else input_text


FILTER_REGISTRY = {
    "git-diff": git_diff,
    "git-status": git_status,
    "git-log": git_log,
    "grep": grep,
    "find": find,
    "ls": ls,
    "tree": tree,
    "dedup-log": dedup_log,
    "smart-truncate": smart_truncate,
    "read-numbered": read_numbered,
    "search-list": search_list,
    "build-output": build_output,
}


def auto_detect_filter(text):
    head = text[:DETECT_WINDOW] if len(text) > DETECT_WINDOW else text

    if RE_GIT_LOG.search(head):
        return git_log
    if RE_GIT_DIFF.search(head) or RE_GIT_DIFF_HUNK.search(head):
        return git_diff
    if RE_GIT_STATUS.search(head):
        return git_status

    if RE_BUILD_OUTPUT.search(head):
        return build_output

    if _is_mostly_porcelain(head):
        return git_status

    lines = head.split("\n")
    non_empty = [l for l in lines if l.strip()]

    first5 = non_empty[:5]
    if any(_is_grep_line(l) for l in first5):
        return grep

    if len(non_empty) >= 3 and all(_is_path_like(l) for l in non_empty):
        return find

    if RE_TREE_GLYPH.search(head):
        return tree

    if RE_LS_TOTAL.search(head) or _count_matches(head, RE_LS_ROW) >= 3:
        return ls

    if RE_SEARCH_LIST_HEADER.search(head):
        return search_list

    if len(lines) >= SMART_TRUNCATE_MIN_LINES and _is_line_numbered(lines):
        return read_numbered

    if len(non_empty) >= 5:
        return dedup_log

    if len(text.split("\n")) >= SMART_TRUNCATE_MIN_LINES:
        return smart_truncate

    return None


def _is_grep_line(line):
    first = line.find(":")
    if first == -1:
        return False
    second = line.find(":", first + 1)
    if second == -1:
        return False
    lineno = line[first + 1:second]
    return bool(re.match(r'^\d+$', lineno))


def _is_path_like(line):
    t = line.strip()
    if not t:
        return False
    if re.match(r'^[A-Za-z]:[\\/]', t):
        return True
    if ":" in t:
        return False
    return t.startswith(".") or t.startswith("/") or "/" in t


def _is_mostly_porcelain(head):
    lines = [l for l in head.split("\n") if l.strip()]
    if len(lines) < 3:
        return False
    hits = sum(1 for l in lines if RE_PORCELAIN.search(l))
    return hits / len(lines) >= 0.6


def _is_line_numbered(lines):
    hits = 0
    non_empty = 0
    sample = lines[:100]
    for l in sample:
        if not l:
            continue
        non_empty += 1
        if RE_READ_NUMBERED_LINE.search(l):
            hits += 1
    if non_empty < 5:
        return False
    return hits / non_empty >= READ_NUMBERED_MIN_HIT_RATIO


def _count_matches(text, regex):
    return len(regex.findall(text))


def safe_apply(fn, text):
    if not callable(fn):
        return text
    try:
        out = fn(text)
        if not isinstance(out, str):
            return text
        return out
    except Exception as e:
        import sys
        name = getattr(fn, "__name__", "anonymous")
        print(f"[rtk] warning: filter '{name}' panicked \u2014 passing through raw output: {e}", file=sys.stderr)
        return text


def compress_text(text, stats):
    bytes_in = len(text)
    stats["bytesBefore"] += bytes_in

    if bytes_in < MIN_COMPRESS_SIZE or bytes_in > RAW_CAP:
        stats["bytesAfter"] += bytes_in
        return text

    fn = auto_detect_filter(text)
    if fn is None:
        stats["bytesAfter"] += bytes_in
        return text

    out = safe_apply(fn, text)

    if not out or len(out) == 0 or len(out) >= bytes_in:
        stats["bytesAfter"] += bytes_in
        return text

    stats["bytesAfter"] += len(out)
    stats["hits"].append({
        "shape": "auto-detected",
        "filter": fn.__name__,
        "saved": bytes_in - len(out)
    })
    return out


def compress_messages(body, enabled=True):
    if not enabled:
        return None
    if not body:
        return None

    if "conversationState" in body:
        return _compress_kiro(body)

    items = body.get("messages") if isinstance(body.get("messages"), list) else \
            body.get("input") if isinstance(body.get("input"), list) else \
            None
    if items is None:
        return None

    stats = {"bytesBefore": 0, "bytesAfter": 0, "hits": []}

    try:
        for msg in items:
            if not msg:
                continue

            if msg.get("type") == "function_call_output":
                if isinstance(msg.get("output"), str):
                    msg["output"] = compress_text(msg["output"], stats)
                elif isinstance(msg.get("output"), list):
                    for part in msg["output"]:
                        if isinstance(part, dict) and part.get("type") == "input_text" and isinstance(part.get("text"), str):
                            part["text"] = compress_text(part["text"], stats)
                continue

            if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                msg["content"] = compress_text(msg["content"], stats)
                continue

            content = msg.get("content")
            if not isinstance(content, list):
                continue

            if msg.get("role") == "tool":
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                        part["text"] = compress_text(part["text"], stats)
                continue

            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if block.get("is_error"):
                    continue

                if isinstance(block.get("content"), str):
                    block["content"] = compress_text(block["content"], stats)
                elif isinstance(block.get("content"), list):
                    for part in block["content"]:
                        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                            part["text"] = compress_text(part["text"], stats)

    except Exception as e:
        print(f"[RTK] compressMessages error: {e}")
        return None

    return stats


def _compress_kiro(body):
    stats = {"bytesBefore": 0, "bytesAfter": 0, "hits": []}
    try:
        state = body.get("conversationState", {})
        all_messages = list(state.get("history") or [])
        if state.get("currentMessage"):
            all_messages.append(state["currentMessage"])

        for msg in all_messages:
            if not isinstance(msg, dict):
                continue
            tool_results = msg.get("userInputMessage", {}).get("userInputMessageContext", {}).get("toolResults")
            if not isinstance(tool_results, list):
                continue

            for tr in tool_results:
                if tr.get("status") == "error":
                    continue
                content = tr.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        part["text"] = compress_text(part["text"], stats)
    except Exception as e:
        print(f"[RTK] compressKiroFormat error: {e}")
        return None
    return stats


def format_rtk_log(stats):
    if not stats or not stats.get("hits"):
        return None
    saved = stats["bytesBefore"] - stats["bytesAfter"]
    pct = f"{(saved / stats['bytesBefore']) * 100:.1f}" if stats["bytesBefore"] > 0 else "0"
    filters = ",".join(set(h["filter"] for h in stats["hits"]))
    return f"[RTK] saved {saved}B / {stats['bytesBefore']}B ({pct}%) via [{filters}] hits={len(stats['hits'])}"
