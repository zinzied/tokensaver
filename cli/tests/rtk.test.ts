import { test } from 'node:test';
import assert from 'node:assert';
import {
  git_diff,
  git_status,
  git_log,
  grep,
  ls,
  dedup_log,
  search_list,
  build_output,
  auto_detect_filter,
  compress_text,
  format_rtk_log,
} from '../src/core/filters/rtk.js';

const DIFF = `diff --git a/src/main.rs b/src/main.rs
index 1234567..89abcde 100644
--- a/src/main.rs
+++ b/src/main.rs
@@ -10,7 +10,7 @@ fn main() {
-    let old = 1;
+    let new = 2;
     println!("hi");
 }
diff --git a/README.md b/README.md
new file mode 100644
--- /dev/null
+++ b/README.md
@@ -0,0 +1,5 @@
+# Hello
+line1
+line2
+line3
+line4
+
`;

test('git_diff compacts files, hunks, and change counts', () => {
  const out = git_diff(DIFF);
  assert.ok(out.includes('\nsrc/main.rs\n'));
  assert.ok(out.includes('  @@ -10,7 +10,7 @@ fn main() {'));
  assert.ok(out.includes('  -    let old = 1;'));
  assert.ok(out.includes('  +    let new = 2;'));
  assert.ok(out.includes('  +1 -1'));
  assert.ok(out.includes('\nREADME.md\n'));
  assert.ok(out.includes('  +6 -0'));
});

test('git_diff appends full-diff hint when truncated', () => {
  const manyFiles = [];
  for (let i = 0; i < 600; i++) {
    manyFiles.push(`diff --git a/f${i}.js b/f${i}.js\n--- a/f${i}.js\n+++ b/f${i}.js\n@@ -1 +1 @@\n-old\n+new`);
  }
  const out = git_diff(manyFiles.join('\n'));
  assert.ok(out.endsWith('[full diff: rtk git diff --no-compact]'));
});

const STATUS_SHORT = `## main...origin/main
 M src/core/utils.js
 M src/core/prompts.js
 M src/api.js
 M src/index.js
 M src/parser.js
 M src/lexer.js
 M src/compiler.js
 M src/optimizer.js
 M src/codegen.js
 M src/linker.js
 M src/runtime.js
 M src/gc.js
?? newfile.js
?? scratch/notes.md
`;

test('git_status groups short-format and truncates file lists', () => {
  const out = git_status(STATUS_SHORT);
  assert.ok(out.startsWith('* main...origin/main\n'));
  assert.ok(out.includes('~ Modified: 12 files\n'));
  assert.ok(out.includes('   src/linker.js\n'));
  assert.ok(out.includes('   ... +2 more\n'));
  assert.ok(out.includes('? Untracked: 2 files\n'));
  assert.ok(out.includes('   newfile.js\n'));
  assert.ok(out.endsWith('   scratch/notes.md'));
});

test('git_status handles long format and clean tree', () => {
  const long = `On branch feature/cool
Changes to be committed:
\tmodified:   package.json
Changes not staged for commit:
\tmodified:   src/bar.js
Untracked files:
\tnotes.txt
`;
  const out = git_status(long);
  assert.ok(out.startsWith('* feature/cool\n'));
  assert.ok(out.includes('~ Modified: 2 files\n'));
  assert.ok(out.includes('   package.json\n'));
  assert.ok(out.endsWith('   src/bar.js'));
  assert.ok(!out.includes('Untracked'));
  assert.strictEqual(git_status(''), 'Clean working tree');
  assert.ok(git_status('  \n').includes('clean \u2014 nothing to commit'));
});

const LOG = `commit 3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4
Author: Alice <alice@example.com>
Date:   Mon Jan 5 10:00:00 2026 +0000

    subject line one

    detailed explanation body
    that spans multiple lines
    and keeps going here
    more and more text
    until it finally ends

commit 9f8e7d6c5b4a39281726354a5b4c3d2e1f0a9b8c
Author: Bob <bob@example.com>
Date:   Sun Jan 4 09:30:00 2026 +0000

    second subject

    another body paragraph
    that is also long
    and continues on
    with extra filler text
`;

test('git_log collapses commit bodies to subjects', () => {
  const out = git_log(LOG);
  assert.ok(out.includes('commit 3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4\n'));
  assert.ok(out.includes('  Subject: subject line one'));
  assert.ok(out.includes('  Subject: second subject'));
  assert.ok(!out.includes('detailed explanation body'));
  assert.ok(out.length < LOG.length);
});

const GREP = `src/main.rs:12:    let old = 1;
src/main.rs:42:        old_value
src/main.rs:87:fn old_helper() {}
src/core/rtk.js:5:const OLD = 1;
src/core/rtk.js:88:OLD_THRESHOLD
src/core/rtk.js:199:  // old path
src/core/rtk.js:210:  oldPath
src/core/rtk.js:300:oldCase
src/core/rtk.js:311:OLD_MODE
src/core/rtk.js:405:oldFlag
src/core/rtk.js:500:OLD_LIST
src/core/rtk.js:600:oldest
src/lib/util.ts:3:old util
src/lib/util.ts:44:oldUtil()
`;

test('grep groups by file, sorts, and right-justifies line numbers', () => {
  const out = grep(GREP);
  assert.ok(out.startsWith('14 matches in 3F:\n\n'));
  assert.ok(out.includes('[file] src/core/rtk.js (9):\n'));
  assert.ok(out.includes('     5: const OLD = 1;\n'));
  assert.ok(out.includes('   600: oldest\n'));
  assert.ok(out.includes('[file] src/main.rs (3):\n'));
});

const LS = `total 120
drwxr-xr-x   5 alice  staff   160 Feb  3 10:22 src
-rw-r--r--   1 alice  staff  2048 Feb  3 10:20 main.js
-rw-r--r--   1 alice  staff   512 Feb  3 09:00 util.ts
lrwxr-xr-x   1 alice  staff    11 Feb  2 08:00 link -> main.js
drwxr-xr-x   3 alice  staff    96 Feb  1 12:00 node_modules
-rw-r--r--   1 alice  staff  1048576 Jan 30 2025 big.bin
-rw-r--r--   1 alice  staff    3072 Jan 30 2025 big.bin
drwxr-xr-x   2 alice  staff    64 Jan 20 2025 test
-rw-r--r--   1 alice  staff     120 Jan 10 2025 notes.md
-rw-r--r--   1 alice  staff      40 Jan 10 2025 a.txt
-rw-r--r--   1 alice  staff      41 Jan 10 2025 b.txt
-rw-r--r--   1 alice  staff      42 Jan 10 2025 c.txt
-rw-r--r--   1 alice  staff      43 Jan 10 2025 d.txt
-rw-r--r--   1 alice  staff      44 Jan 10 2025 e.txt
-rw-r--r--   1 alice  staff      45 Jan 10 2025 f.txt
`;

test('ls skips noise dirs and summarizes extensions', () => {
  const out = ls(LS);
  assert.ok(out.startsWith('src/\ntest/\n'));
  assert.ok(!out.includes('node_modules'));
  assert.ok(out.includes('main.js  2.0K\n'));
  assert.ok(out.includes('util.ts  512B\n'));
  assert.ok(out.includes('big.bin  1.0M\n'));
  assert.ok(out.includes('\nSummary: 12 files, 2 dirs (6 .txt, 2 .js, 2 .bin, 1 .ts, 1 .md)'));
});

const DEDUP = `[12:00:00] build started
[12:00:01] compile step 1
[12:00:02] compile step 1
[12:00:03] compile step 1
[12:00:04] linking
[12:00:05] linking
[12:00:06] done
[12:00:07] watching for changes
[12:00:08] watching for changes
[12:00:09] watching for changes
[12:00:10] watching for changes
[12:00:11] watching for changes
[12:00:12] idle

[12:01:00] build started
[12:01:01] compile step 1
[12:01:02] compile step 1
`;

test('dedup_log collapses consecutive duplicate lines', () => {
  const out = dedup_log(DEDUP);
  assert.ok(out.includes('[12:00:01] compile step 1\n'));
  assert.ok(out.includes('[12:00:04] linking\n'));
  assert.ok(out.includes('[12:00:12] idle\n\n'));
  assert.ok(out.includes('[12:01:02] compile step 1\n'));
  const count = (out.match(/\[12:00:0[1-9]\] compile step 1/g) || []).length;
  assert.strictEqual(count, 3);
});

test('search_list groups searched files by directory', () => {
  const input = `Result of search in 'src' (total 8 files):
- src/a.js
- src/b.js
- src/c/d.js
- src/c/e.js
- src/c/f/g.js
- src/c/f/h.js
- tests/x.test.js
- tests/y.test.js
`;
  const out = search_list(input);
  assert.ok(out.startsWith("Result of search in 'src' (total 8 files):\n8 files in 4 dirs:\n\n"));
  assert.ok(out.includes('src/ (2):\n  a.js\n  b.js\n'));
  assert.ok(out.includes('src/c/f/ (2):\n  g.js\n  h.js\n'));
  assert.ok(out.endsWith('tests/ (2):\n  x.test.js\n  y.test.js'));
});

test('build_output keeps errors, drops noise, and counts compiles', () => {
  const input = `error[E0308]: mismatched types
 --> src/main.rs:12:5
  |
12 |   let x: u8 = "hi";
  |       ^ expected u8, found &str
  |
warning[W0101]: unused variable
 --> src/main.rs:20:1
  |
20 |   let unused = 1;
  |   ^^^^^^^^^^^^^^^ help: if this is intentional
  |
   Compiling tokensaver v0.1.0
   Compiling serde v1.0.0
    Finished dev [unoptimized + debuginfo] target(s) in 0.5s
`;
  const out = build_output(input);
  assert.ok(out.startsWith('Compiled 2 packages\n'));
  assert.ok(out.includes('error[E0308]: mismatched types\n --> src/main.rs:12:5\n  |\n'));
  assert.ok(
    out.includes(' --> src/main.rs:20:1\n  |\n20 |   let unused = 1;\n  |   ^^^^^^^^^^^^^^^ help: if this is intentional\n  |\nwarning[W0101]: unused variable\n')
  );
  assert.ok(out.endsWith('    Finished dev [unoptimized + debuginfo] target(s) in 0.5s'));
});

test('auto_detect_filter maps common tool outputs', () => {
  assert.strictEqual(auto_detect_filter(DIFF), git_diff);
  assert.strictEqual(auto_detect_filter(STATUS_SHORT), git_status);
  assert.strictEqual(auto_detect_filter(LOG), git_log);
  assert.strictEqual(auto_detect_filter(GREP), grep);
  assert.strictEqual(auto_detect_filter(LS), ls);
  assert.strictEqual(auto_detect_filter('just a normal sentence'), null);
});

test('compress_text and format_rtk_log report savings', () => {
  const big = DIFF.repeat(3);
  const stats: any = { bytesBefore: 0, bytesAfter: 0, hits: [] };
  const out = compress_text(big, stats);
  assert.ok(out.length < big.length);
  assert.ok(stats.hits.length === 1);
  assert.strictEqual(stats.hits[0].filter, 'git_diff');
  assert.strictEqual(stats.hits[0].saved, big.length - out.length);
  assert.ok(format_rtk_log(stats)!.startsWith('[RTK] saved '));
  assert.strictEqual(format_rtk_log({ bytesBefore: 0, bytesAfter: 0, hits: [] }), null);
});

test('compress_text passes through when output would not shrink', () => {
  const stats: any = { bytesBefore: 0, bytesAfter: 0, hits: [] };
  const text = 'x'.repeat(600);
  assert.strictEqual(compress_text(text, stats), text);
  assert.strictEqual(stats.hits.length, 0);
});
