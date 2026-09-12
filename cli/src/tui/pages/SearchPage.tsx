import React, { useState } from 'react';
import { Page, Hint, ErrorLine, TextField, Table, fmt, T, type Cell } from '../components.js';
import { useScreenInput } from '../input.js';
import { searchQuery } from '../../core/insights.js';

export function SearchPage() {
  const [q, setQ] = useState('');
  const [results, setResults] = useState<any[] | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);

  useScreenInput((k) => {
    if (k.q || k.up || k.down || k.esc) return false;
    if (k.input === 'e' && !editing) {
      setEditing(true);
      return true;
    }
    if (k.input === 'c' && results) {
      setResults(null);
      setQ('');
      return true;
    }
    return false;
  });

  function run() {
    setError('');
    try {
      setResults(searchQuery(q));
    } catch (e) {
      setError(String((e as Error).message || e));
    }
    setEditing(false);
  }

  const rows: Cell[][] = (results || []).map((r) => [
    T(r.source, 'green'),
    T(r.kind || '—'),
    T(r.description || r.path || '—'),
    T(`${fmt(r.saved_tokens)} tok`),
    T(
      r.timestamp
        ? new Date(Number.isFinite(Number(r.timestamp)) ? Number(r.timestamp) * 1000 : r.timestamp).toLocaleString()
        : '—'
    ),
  ]);

  return (
    <Page title="Search" sub="Search the compression index (events, files and proxy requests).">
      {error && <ErrorLine>{error}</ErrorLine>}
      <Hint>Press e to type a query, Enter to search, c to clear.</Hint>
      {editing && (
        <TextField
          label="Query"
          value={q}
          onChange={setQ}
          onSubmit={() => run()}
          onCancel={() => setEditing(false)}
          placeholder="Search descriptions, kinds, file paths, models…"
        />
      )}
      {results !== null && !results.length && <Hint>No matches for “{q}”.</Hint>}
      {results && results.length > 0 && <Table head={['Source', 'Kind', 'Description', 'Saved', 'Time']} rows={rows} />}
    </Page>
  );
}
