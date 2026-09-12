import fs from 'node:fs';
import path from 'node:path';

export interface Goal {
  id: string;
  text: string;
  status: 'active' | 'completed' | 'abandoned';
  created: string;
  updated: string;
}

export interface GoalStore {
  goals: Goal[];
  modified: string;
}

function goalPath(): string {
  const home = process.env.TOKENSAVER_HOME || path.join(
    process.env.HOME || process.env.USERPROFILE || '.',
    '.config', 'opencode',
  );
  return path.join(home, 'goals.json');
}

export function loadGoals(): GoalStore {
  try {
    const raw = fs.readFileSync(goalPath(), 'utf8');
    return JSON.parse(raw) as GoalStore;
  } catch {
    return { goals: [], modified: new Date().toISOString() };
  }
}

export function saveGoals(store: GoalStore): void {
  const p = goalPath();
  const dir = path.dirname(p);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  store.modified = new Date().toISOString();
  fs.writeFileSync(p, JSON.stringify(store, null, 2));
}

export function addGoal(text: string): Goal {
  const store = loadGoals();
  const goal: Goal = {
    id: Date.now().toString(36),
    text,
    status: 'active',
    created: new Date().toISOString(),
    updated: new Date().toISOString(),
  };
  store.goals.push(goal);
  saveGoals(store);
  return goal;
}

export function completeGoal(id: string): Goal | null {
  const store = loadGoals();
  const goal = store.goals.find((g) => g.id === id);
  if (!goal) return null;
  goal.status = 'completed';
  goal.updated = new Date().toISOString();
  saveGoals(store);
  return goal;
}

export function abandonGoal(id: string): Goal | null {
  const store = loadGoals();
  const goal = store.goals.find((g) => g.id === id);
  if (!goal) return null;
  goal.status = 'abandoned';
  goal.updated = new Date().toISOString();
  saveGoals(store);
  return goal;
}

export function removeGoal(id: string): boolean {
  const store = loadGoals();
  const idx = store.goals.findIndex((g) => g.id === id);
  if (idx === -1) return false;
  store.goals.splice(idx, 1);
  saveGoals(store);
  return true;
}

export function clearCompletedGoals(): number {
  const store = loadGoals();
  const before = store.goals.length;
  store.goals = store.goals.filter((g) => g.status !== 'completed');
  saveGoals(store);
  return before - store.goals.length;
}
