import fs from 'node:fs';
import path from 'node:path';

export interface Reminder {
  id: string;
  text: string;
  dueAt: string;
  created: string;
  fired: boolean;
}

export interface ReminderStore {
  reminders: Reminder[];
  modified: string;
}

function reminderPath(): string {
  const home = process.env.TOKENSAVER_HOME || path.join(
    process.env.HOME || process.env.USERPROFILE || '.',
    '.config', 'opencode',
  );
  return path.join(home, 'reminders.json');
}

export function loadReminders(): ReminderStore {
  try {
    const raw = fs.readFileSync(reminderPath(), 'utf8');
    return JSON.parse(raw) as ReminderStore;
  } catch {
    return { reminders: [], modified: new Date().toISOString() };
  }
}

export function saveReminders(store: ReminderStore): void {
  const p = reminderPath();
  const dir = path.dirname(p);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  store.modified = new Date().toISOString();
  fs.writeFileSync(p, JSON.stringify(store, null, 2));
}

export function addReminder(text: string, dueAt: Date): Reminder {
  const store = loadReminders();
  const reminder: Reminder = {
    id: Date.now().toString(36),
    text,
    dueAt: dueAt.toISOString(),
    created: new Date().toISOString(),
    fired: false,
  };
  store.reminders.push(reminder);
  saveReminders(store);
  return reminder;
}

export function getDueReminders(): Reminder[] {
  const store = loadReminders();
  const now = Date.now();
  return store.reminders.filter((r) => !r.fired && new Date(r.dueAt).getTime() <= now);
}

export function markFired(id: string): Reminder | null {
  const store = loadReminders();
  const r = store.reminders.find((r) => r.id === id);
  if (!r) return null;
  r.fired = true;
  saveReminders(store);
  return r;
}

export function removeReminder(id: string): boolean {
  const store = loadReminders();
  const idx = store.reminders.findIndex((r) => r.id === id);
  if (idx === -1) return false;
  store.reminders.splice(idx, 1);
  saveReminders(store);
  return true;
}

export function clearFiredReminders(): number {
  const store = loadReminders();
  const before = store.reminders.length;
  store.reminders = store.reminders.filter((r) => !r.fired);
  saveReminders(store);
  return before - store.reminders.length;
}
