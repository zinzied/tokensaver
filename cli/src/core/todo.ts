import fs from 'node:fs';
import path from 'node:path';

export interface TodoItem {
  id: string;
  text: string;
  status: 'pending' | 'done' | 'cancelled';
  created: string;
  updated: string;
}

export interface TodoStore {
  items: TodoItem[];
  modified: string;
}

function todoPath(): string {
  const home = process.env.TOKENSAVER_HOME || path.join(
    process.env.HOME || process.env.USERPROFILE || '.',
    '.config', 'opencode',
  );
  return path.join(home, 'todo.json');
}

export function loadTodo(): TodoStore {
  try {
    const raw = fs.readFileSync(todoPath(), 'utf8');
    return JSON.parse(raw) as TodoStore;
  } catch {
    return { items: [], modified: new Date().toISOString() };
  }
}

export function saveTodo(store: TodoStore): void {
  const p = todoPath();
  const dir = path.dirname(p);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  store.modified = new Date().toISOString();
  fs.writeFileSync(p, JSON.stringify(store, null, 2));
}

export function addTodo(text: string): TodoItem {
  const store = loadTodo();
  const item: TodoItem = {
    id: Date.now().toString(36),
    text,
    status: 'pending',
    created: new Date().toISOString(),
    updated: new Date().toISOString(),
  };
  store.items.push(item);
  saveTodo(store);
  return item;
}

export function completeTodo(id: string): TodoItem | null {
  const store = loadTodo();
  const item = store.items.find((i) => i.id === id);
  if (!item) return null;
  item.status = 'done';
  item.updated = new Date().toISOString();
  saveTodo(store);
  return item;
}

export function cancelTodo(id: string): TodoItem | null {
  const store = loadTodo();
  const item = store.items.find((i) => i.id === id);
  if (!item) return null;
  item.status = 'cancelled';
  item.updated = new Date().toISOString();
  saveTodo(store);
  return item;
}

export function removeTodo(id: string): boolean {
  const store = loadTodo();
  const idx = store.items.findIndex((i) => i.id === id);
  if (idx === -1) return false;
  store.items.splice(idx, 1);
  saveTodo(store);
  return true;
}

export function clearDoneTodos(): number {
  const store = loadTodo();
  const before = store.items.length;
  store.items = store.items.filter((i) => i.status !== 'done');
  saveTodo(store);
  return before - store.items.length;
}
