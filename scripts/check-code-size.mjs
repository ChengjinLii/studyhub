#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { relative, resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);

const lineBudgets = [
  ['frontend/pages/upload.tsx', 1200],
  ['frontend/pages/admin/index.tsx', 1200],
  ['frontend/pages/me.tsx', 900],
  ['frontend/pages/index.tsx', 1100],
  ['frontend/pages/materials/[id].tsx', 900],
  ['backend/app/services/materials_service.py', 1500],
  ['backend/app/services/requests_service.py', 900],
];

const forbiddenDirs = [
  'frontend/.next',
  'frontend/test-results',
  'frontend/playwright-report',
  'backend/.pytest_cache',
];

const pageJsonBudget = 25;
const failures = [];

for (const [file, maxLines] of lineBudgets) {
  const absolute = resolve(root, file);
  if (!existsSync(absolute)) {
    failures.push(`${file}: missing`);
    continue;
  }
  const lines = readFileSync(absolute, 'utf8').split('\n').length;
  if (lines > maxLines) {
    failures.push(`${file}: ${lines} lines exceeds ${maxLines}`);
  }
}

const pageJsonMatches = execFileSync('rg', ['-n', String.raw`\.json\(`, 'frontend/pages', '-g', '*.tsx'], {
  cwd: root,
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'pipe'],
})
  .trim()
  .split('\n')
  .filter(Boolean);
if (pageJsonMatches.length > pageJsonBudget) {
  failures.push(`frontend/pages direct resp.json(): ${pageJsonMatches.length} exceeds ${pageJsonBudget}`);
}

for (const dir of forbiddenDirs) {
  if (existsSync(resolve(root, dir))) {
    failures.push(`${dir}: generated directory should be cleaned`);
  }
}

const pycache = execFileSync('find', ['backend', 'ai_platform', '-type', 'd', '-name', '__pycache__', '-print'], {
  cwd: root,
  encoding: 'utf8',
}).trim();
if (pycache) {
  failures.push(`__pycache__ directories present:\n${pycache}`);
}

if (failures.length) {
  console.error(`Code size check failed:\n- ${failures.join('\n- ')}`);
  process.exit(1);
}

console.log(`Code size check passed (${lineBudgets.length} file budgets, ${pageJsonMatches.length} page json calls).`);
