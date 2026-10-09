import { readFile, writeFile, rename, unlink } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const root = new URL('../', import.meta.url);
const target = new URL('data/material-subject-catalogue.json', root);
const publicFields = [
  'id', 'title', 'price', 'free', 'school', 'college', 'major', 'courseCategory',
  'generalEducation', 'gradeValue', 'tags', 'ratingAvg', 'ratingCount', 'likeCount', 'commentCount',
  'viewCount', 'downloadCount', 'createdAt', 'uploaderId', 'uploaderNickname',
];

// Run the existing classification rules offline, without maintaining a second set of aliases.
async function loadRules() {
  const compile = async (path, dependencies = {}) => {
    const source = await readFile(new URL(path, root), 'utf8');
    const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
    const module = { exports: {} };
    new Function('module', 'exports', 'require', code)(module, module.exports, (name) => {
      if (!(name in dependencies)) throw new Error(`Unexpected rule dependency: ${name}`);
      return dependencies[name];
    });
    return module.exports;
  };
  const constants = await compile('constants/materialSubjects.ts');
  return compile('lib/materialSubjects.ts', { '../constants/materialSubjects': constants });
}

async function buildCatalogue(base) {
  const items = [];
  let total;
  let pages = 1;
  for (let page = 1; page <= pages; page += 1) {
    const url = new URL(base);
    url.search = new URLSearchParams({ page: String(page), size: '100', sort: 'newest' }).toString();
    const response = await fetch(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error(`Public catalogue returned HTTP ${response.status}`);
    const envelope = await response.json();
    const data = envelope.data;
    if (!envelope.ok || !Array.isArray(data?.items) || !Number.isInteger(data.meta?.total) || data.meta.total < 0
      || !Number.isInteger(data.meta.size) || data.meta.size < 1 || data.meta.page !== page) {
      throw new Error('Invalid public catalogue response');
    }
    total ??= data.meta.total;
    if (total !== data.meta.total) throw new Error('Catalogue changed during refresh; retry without replacing the old snapshot');
    pages = Math.ceil(total / data.meta.size);
    if (pages > 100) throw new Error('Catalogue exceeded the offline refresh limit');
    for (const item of data.items) {
      if (!Number.isInteger(item.id) || item.id < 1 || typeof item.title !== 'string'
        || typeof item.price !== 'number' || typeof item.free !== 'boolean') throw new Error('Invalid public material');
      items.push(Object.fromEntries(publicFields.filter((field) => item[field] !== undefined).map((field) => [field, item[field]])));
    }
  }
  if (items.length !== total || new Set(items.map((item) => item.id)).size !== total) {
    throw new Error('Incomplete or duplicate catalogue; the previous snapshot has not been changed');
  }
  if (!total) throw new Error('Refusing to replace the catalogue with an empty snapshot');
  const { groupMaterialSubjects } = await loadRules();
  const folders = groupMaterialSubjects(items).map(({ id, name, materials }) => ({ id, name, materials }));
  return { version: 1, updatedAt: new Date().toISOString(), total, folders };
}

const args = process.argv.slice(2);
if (args.some((arg) => arg !== '--write')) throw new Error('Usage: node scripts/update-material-subjects.mjs [--write]');
const catalogue = await buildCatalogue('https://study-hub.cn/api/materials');
if (args.includes('--write')) {
  const temporary = new URL(`${fileURLToPath(target)}.${process.pid}.tmp`, 'file:');
  try {
    await writeFile(temporary, `${JSON.stringify(catalogue, null, 2)}\n`, { flag: 'wx' });
    await rename(temporary, target);
  } finally {
    await unlink(temporary).catch(() => {});
  }
}
console.log(`${args.includes('--write') ? 'Updated' : 'Dry run:'} ${catalogue.total} public materials in ${catalogue.folders.length} folders`);
