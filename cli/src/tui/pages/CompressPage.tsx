import React, { useState } from 'react';
import { Page, Row, Stat, Hint, ErrorLine, TextField, fmt } from '../components.js';
import { useScreenInput } from '../input.js';
import { compressTest } from '../../core/insights.js';

export function CompressPage() {
  const [text, setText] = useState('');
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);

  useScreenInput((k) => {
    if (k.q || k.up || k.down || k.esc) return false;
    if (k.input === 'e') {
      setEditing(true);
      return true;
    }
    if (k.input === 'c' && result) {
      setResult(null);
      setText('');
      return true;
    }
    return false;
  });

  function run() {
    setError('');
    try {
      setResult(compressTest(text));
    } catch (e) {
      setError(String((e as Error).message || e));
    }
    setEditing(false);
  }

  return (
    <Page title="Compress" sub="Paste raw tool output and see which RTK filter would compress it and how much it saves.">
      {error && <ErrorLine>{error}</ErrorLine>}
      {!editing && (
        <Hint>Press e to enter tool output (paste it, then Enter to test).</Hint>
      )}
      {editing && (
        <TextField
          label="Tool output"
          value={text}
          onChange={setText}
          onSubmit={() => run()}
          onCancel={() => setEditing(false)}
          placeholder="e.g. paste a git diff, git status, ls -la, npm build output, a long log…"
        />
      )}
      {result && (
        <>
          <Row>
            <Stat label="Detected filter" value={result.detected ?? 'none'} />
            <Stat label="Characters in" value={fmt(result.length)} />
            <Stat label="Characters out" value={fmt(result.compressed_length ?? result.length)} />
            <Stat label="Saved" value={fmt(result.saved ?? 0)} />
            <Stat label="Reduction" value={`${result.pct ?? 0}%`} />
          </Row>
          {result.tooSmall && (
            <Hint>
              Input is below the minimum size (MIN_COMPRESS_SIZE = {result.min} chars) — small inputs are passed
              through.
            </Hint>
          )}
          {!result.detected && !result.tooSmall && (
            <Hint>No filter matched. Long, dedupable logs get smart-truncated automatically.</Hint>
          )}
          {result.compressed && (
            <Hint>
              Preview (compressed): {result.compressed.length > 400 ? result.compressed.slice(0, 400) + '…' : result.compressed}
            </Hint>
          )}
        </>
      )}
    </Page>
  );
}
