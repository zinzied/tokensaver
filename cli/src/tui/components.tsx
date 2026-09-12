import React, { type ReactNode } from 'react';
import { Box, Text } from 'ink';
import { useScreenInput, type KeyEvent } from './input.js';

export const fmt = (n: unknown): string => {
  const num = Number(n);
  if (Number.isFinite(num)) return num.toLocaleString();
  return n === null || n === undefined || n === '' ? '—' : String(n);
};

export const price = (m: { is_free?: boolean; input_price?: number; output_price?: number } | null | undefined): string => {
  if (!m) return '';
  if (m.is_free) return 'FREE';
  return `$${m.input_price}/${m.output_price} per M`;
};

export const countdown = (iso?: string | null): string => {
  if (!iso) return '';
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return '';
  const secs = Math.floor((ms - Date.now()) / 1000);
  if (secs <= 0) return 'resetting now';
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return `reset in ${h ? `${h}h ` : ''}${m ? `${m}m ` : ''}${s}s`;
};

export const uptime = (startedAt?: string | null): string => {
  if (!startedAt) return '—';
  const s = Math.max(0, Math.floor((Date.now() - Date.parse(startedAt)) / 1000));
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h) return `up ${h}h ${m % 60}m`;
  if (m) return `up ${m}m ${s % 60}s`;
  return `up ${s}s`;
};

export function Page({ title, sub, children }: { title: string; sub?: string; children?: ReactNode }) {
  return (
    <Box flexDirection="column" flexGrow={1} padding={1}>
      <Text bold color="cyan">
        {title}
      </Text>
      {sub ? <Text color="gray">{sub}</Text> : null}
      <Box flexDirection="column" marginTop={1}>
        {children}
      </Box>
    </Box>
  );
}

export function Section({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text bold color="yellow">
        {title}
      </Text>
      <Box flexDirection="column" marginTop={1}>
        {children}
      </Box>
    </Box>
  );
}

export function Row({ children }: { children?: ReactNode }) {
  return (
    <Box flexDirection="row" flexWrap="wrap">
      {children}
    </Box>
  );
}

export function Stat({ label, value, sub, width = 26, color }: { label: string; value?: ReactNode; sub?: string; width?: number; color?: string }) {
  return (
    <Box flexDirection="column" width={width} marginRight={2} marginBottom={1}>
      <Text color="gray">{label}</Text>
      <Text bold color={color}>{value === undefined || value === null ? '—' : value}</Text>
      {sub ? <Text color="gray">{sub}</Text> : null}
    </Box>
  );
}

export function Badge({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <Text backgroundColor={ok ? 'green' : 'red'} color="black">
      {' '}
      {children}{' '}
    </Text>
  );
}

export function Hint({ children }: { children?: ReactNode }) {
  return <Text color="gray">{children}</Text>;
}

export function ErrorLine({ children }: { children?: ReactNode }) {
  return <Text color="red">{children}</Text>;
}

export function SuccessLine({ children }: { children?: ReactNode }) {
  return <Text color="green">{children}</Text>;
}

export interface Cell {
  text: string;
  color?: string;
  bold?: boolean;
}

export const T = (text: unknown, color?: string, bold?: boolean): Cell => ({
  text: text === null || text === undefined ? '—' : String(text),
  color,
  bold,
});

function renderCell(cellValue: Cell, width: number, isHead: boolean): ReactNode {
  const text = isHead ? cellValue.text.toUpperCase() : cellValue.text;
  const padded = text.padEnd(Math.max(0, width + 2));
  if (isHead) {
    return (
      <Text key={`${cellValue.text}-${width}`} bold color="cyan">
        {padded}
      </Text>
    );
  }
  return (
    <Text key={`${cellValue.text}-${width}`} color={cellValue.color || undefined} bold={cellValue.bold}>
      {padded}
    </Text>
  );
}

export function Table({ head, rows }: { head: string[]; rows: Cell[][] }) {
  if (!rows.length) return <Hint>No data yet.</Hint>;
  const widths = head.map((h, i) =>
    Math.max(h.length, ...rows.map((r) => (r[i] ? r[i].text.length : 0)))
  );
  const heads = head.map((h) => ({ text: h })) as Cell[];
  return (
    <Box flexDirection="column">
      <Box flexDirection="row">{heads.map((c, i) => renderCell(c, widths[i], true))}</Box>
      {rows.map((r, i) => (
        <Box key={i} flexDirection="row">
          {r.map((c, j) => renderCell(c, widths[j], false))}
        </Box>
      ))}
    </Box>
  );
}

export function TextField({
  label,
  value,
  onChange,
  onSubmit,
  onCancel,
  placeholder,
  mask,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  onSubmit?: (v: string) => void;
  onCancel?: () => void;
  placeholder?: string;
  mask?: string;
}) {
  useScreenInput((k: KeyEvent) => {
    if (k.enter) {
      if (onSubmit) onSubmit(value);
      return true;
    }
    if (k.esc) {
      if (onCancel) onCancel();
      return true;
    }
    if (k.backspace) {
      onChange(value.slice(0, -1));
      return true;
    }
    if (k.left || k.right || k.up || k.down || k.tab || k.shiftTab) return false;
    if (k.ctrl) return true;
    if (k.input) {
      onChange(value + k.input);
      return true;
    }
    return true;
  });

  const shown = mask ? mask.repeat(value.length) : value;
  const display = shown || (placeholder ? placeholder : ' ');
  return (
    <Box>
      <Text color="cyan">{label}: </Text>
      <Text backgroundColor="black">{display}</Text>
      <Text> </Text>
    </Box>
  );
}

export function Form({
  title,
  fields,
  onDone,
  onCancel,
}: {
  title: string;
  fields: { label: string; get: () => string; set: (v: string) => void }[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const [step, setStep] = React.useState(0);
  const [values, setValues] = React.useState<string[]>(fields.map(() => ''));
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text bold color="yellow">
        {title}
      </Text>
      <Box flexDirection="column" marginTop={1}>
        <TextField
          label={fields[step].label}
          value={values[step]}
          onChange={(v) => {
            const next = [...values];
            next[step] = v;
            setValues(next);
            fields[step].set(v);
          }}
          onSubmit={() => {
            if (step < fields.length - 1) setStep(step + 1);
            else {
              fields.forEach((f, i) => f.set(values[i]));
              onDone();
            }
          }}
          onCancel={onCancel}
        />
      </Box>
      <Hint>Enter: next field / submit · Esc: cancel</Hint>
    </Box>
  );
}
