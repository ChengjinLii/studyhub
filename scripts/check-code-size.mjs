#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { relative, resolve } from 'node:path';

const root = resolve(new URL('..', import.meta.url).pathname);
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
  ['backend/app/services/requests_service.py', 900],
];

const forbiddenDirs = ['frontend/test-results', 'frontend/playwright-report', 'backend/.pytest_cache'];
if (!allowFrontendBuild) {
  forbiddenDirs.unshift('frontend/.next');
}

const pageJsonBudget = 10;
const failures = [];

function execText(command, args, options = {}) {
  try {
    return execFileSync(command, args, {
      cwd: root,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (error) {
    // ripgrep exits with 1 when there are no matches; that is a passing state here.
    if (options.allowNoMatches && error && error.status === 1) {
      return '';
    }
    throw error;
  }
}

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

const pageJsonMatches = execText('rg', ['-n', String.raw`\.json\(`, 'frontend/pages', '-g', '*.tsx'], {
  allowNoMatches: true,
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

const pycache = execText('find', ['backend', 'ai_platform', '-type', 'd', '-name', '__pycache__', '-print']).trim();
if (pycache) {
  failures.push(`__pycache__ directories present:\n${pycache}`);
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

console.log(`Code size check passed (${lineBudgets.length} file budgets, ${pageJsonMatches.length} page json calls).`);
