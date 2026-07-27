#!/usr/bin/env node
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { relative, resolve } from 'node:path';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const allowFrontendBuild = ['1', 'true', 'yes'].includes(
  String(process.env.STUDYHUB_CODE_SIZE_ALLOW_FRONTEND_BUILD || '').toLowerCase()
);

const lineBudgets = [
  ['frontend/pages/upload.tsx', 1200],
  ['frontend/pages/admin/index.tsx', 1200],
  ['frontend/pages/me.tsx', 900],
  ['frontend/pages/index.tsx', 1100],
  ['frontend/pages/materials/[id].tsx', 900],
  ['backend/app/services/materials_service.py', 1500],
  ['backend/app/services/requests_service.py', 1000],
];

const forbiddenDirs = ['frontend/test-results', 'frontend/playwright-report', 'backend/.pytest_cache'];
if (!allowFrontendBuild) {
  forbiddenDirs.unshift('frontend/.next');
}

const pageJsonBudget = 10;
const failures = [];

function countLines(contents) {
  if (!contents) {
    return 0;
  }
  return contents.endsWith('\n') ? contents.split('\n').length - 1 : contents.split('\n').length;
}

function listFiles(dir, predicate) {
  const absoluteDir = resolve(root, dir);
  if (!existsSync(absoluteDir)) {
    return [];
  }

  const files = [];
  const stack = [absoluteDir];

  while (stack.length) {
    const current = stack.pop();
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const absolutePath = resolve(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(absolutePath);
      } else if (entry.isFile() && predicate(absolutePath)) {
        files.push(absolutePath);
      }
    }
  }

  return files.sort();
}

function listDirectories(dir, dirname) {
  const absoluteDir = resolve(root, dir);
  if (!existsSync(absoluteDir)) {
    return [];
  }

  const matches = [];
  const stack = [absoluteDir];

  while (stack.length) {
    const current = stack.pop();
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      if (!entry.isDirectory()) {
        continue;
      }

      const absolutePath = resolve(current, entry.name);
      if (entry.name === dirname) {
        matches.push(relative(root, absolutePath));
        continue;
      }
      stack.push(absolutePath);
    }
  }

  return matches.sort();
}

for (const [file, maxLines] of lineBudgets) {
  const absolute = resolve(root, file);
  if (!existsSync(absolute)) {
    failures.push(`${file}: missing`);
    continue;
  }
  const lines = countLines(readFileSync(absolute, 'utf8'));
  if (lines > maxLines) {
    failures.push(`${file}: ${lines} lines exceeds ${maxLines}`);
  }
}

const pageJsonMatches = listFiles('frontend/pages', (absolutePath) => absolutePath.endsWith('.tsx')).filter(
  (absolutePath) => readFileSync(absolutePath, 'utf8').includes('.json(')
);

let pageJsonCalls = 0;
for (const absolutePath of pageJsonMatches) {
  const contents = readFileSync(absolutePath, 'utf8');
  pageJsonCalls += contents.match(/\.json\(/g)?.length || 0;
}
if (pageJsonCalls > pageJsonBudget) {
  failures.push(`frontend/pages direct resp.json(): ${pageJsonCalls} exceeds ${pageJsonBudget}`);
}

for (const dir of forbiddenDirs) {
  if (existsSync(resolve(root, dir))) {
    failures.push(`${dir}: generated directory should be cleaned`);
  }
}

const pycache = ['backend'].flatMap((dir) => listDirectories(dir, '__pycache__'));
if (pycache.length) {
  failures.push(`__pycache__ directories present:\n${pycache.join('\n')}`);
}

if (failures.length) {
  console.error(
    `Code size check failed:\n- ${failures.join('\n- ')}\n\n` +
      'If this is a local or CI source check, run: bash scripts/clean-generated.sh --all\n' +
      'If this is a production machine that must keep the active Next.js build, run: ' +
      'bash scripts/clean-generated.sh --source && STUDYHUB_CODE_SIZE_ALLOW_FRONTEND_BUILD=1 node scripts/check-code-size.mjs'
  );
  process.exit(1);
}

console.log(`Code size check passed (${lineBudgets.length} file budgets, ${pageJsonCalls} page json calls).`);
