import React, { useEffect, useState } from 'react';
import { Page, Section, Row, Stat, Table, Hint, ErrorLine, SuccessLine, TextField, fmt, T } from '../components.js';
import { useScreenInput } from '../input.js';
import { useData } from '../useData.js';
import { settingsGet, settingsSave } from '../../core/insights.js';

type SettingsData = Awaited<ReturnType<typeof settingsGet>>;

export function SettingsPage() {
  const { data, error, reload } = useData(() => settingsGet());
  const [model, setModel] = useState('');
  const [smallModel, setSmallModel] = useState('');
  const [step, setStep] = useState<0 | 1 | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState('');

  useEffect(() => {
    if (data) {
      setModel(data.model);
      setSmallModel(data.small_model);
    }
  }, [data]);

  useScreenInput((k) => {
    if (k.q || k.up || k.down || k.esc) return false;
    if (step !== null) return false;
    if (k.input === 'e') {
      setStep(0);
      return true;
    }
    if (k.input === 'm') {
      setStep(1);
      return true;
    }
    return false;
  });

  function save(nextModel: string, nextSmall: string) {
    setBusy(true);
    setSaved(false);
    setSaveError('');
    try {
      settingsSave({ model: nextModel, small_model: nextSmall });
      setSaved(true);
      reload();
    } catch (e) {
      setSaveError(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page title="Settings" sub={data ? `Writes to ${data.path}` : undefined}>
      {error && <ErrorLine>{error}</ErrorLine>}
      {saveError && <ErrorLine>{saveError}</ErrorLine>}
      {saved && <SuccessLine>Saved.</SuccessLine>}
      {!data && !error && <Hint>Loading…</Hint>}
      {data && (
        <>
          <Row>
            <Stat label="Current model" value={data.current || '—'} />
            <Stat label="Configured providers" value={fmt(data.providerCount)} />
          </Row>
          <Hint>Press e to edit model, m to edit small model (Enter submits, Esc cancels).</Hint>
          {step === 0 && (
            <TextField
              label="Model"
              value={model}
              onChange={setModel}
              onSubmit={(v) => {
                save(v, smallModel);
                setStep(null);
              }}
              onCancel={() => setStep(null)}
            />
          )}
          {step === 1 && (
            <TextField
              label="Small model"
              value={smallModel}
              onChange={setSmallModel}
              onSubmit={(v) => {
                save(model, v);
                setStep(null);
              }}
              onCancel={() => setStep(null)}
            />
          )}
          {data.compaction && (
            <Section title="Compaction">
              <Row>
                {Object.entries(data.compaction).map(([k, v]) => (
                  <Stat key={k} label={k} value={String(v)} />
                ))}
              </Row>
            </Section>
          )}
          <Section title="Backups">
            {data.backups.length ? (
              <Table
                head={['Backup', 'Path']}
                rows={data.backups.map(([label, p]) => [T(label), T(p)])}
              />
            ) : (
              <Hint>No backups yet — they are created automatically when settings are saved.</Hint>
            )}
          </Section>
        </>
      )}
    </Page>
  );
}
