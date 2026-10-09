import { readFileSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { MATERIAL_SUBJECTS } from '../../constants/materialSubjects';
import type { SubjectSearchAliases } from '../materialSubjects';

const normalize = (value: string) => value.normalize('NFKC').replace(/_/g, ' ').trim().toLowerCase();
let cache: { path: string; stamp: string; aliases: SubjectSearchAliases } | undefined;

// Only aliases for public subject names reach page props; never serialize the private glossary.
export function publicSubjectAliases(glossary: unknown): SubjectSearchAliases {
  if (!glossary || typeof glossary !== 'object' || Array.isArray(glossary)) return {};
  const groups = Object.entries(glossary).slice(0, 256).map(([key, values]) => (
    Array.from(new Set([key, ...(Array.isArray(values) ? values : [])]
      .filter((value): value is string => typeof value === 'string' && value.length <= 120)
      .map(normalize).filter(Boolean))).slice(0, 8)
  ));
  const aliases: SubjectSearchAliases = {};
  MATERIAL_SUBJECTS.forEach((subject) => {
    const names = new Set([subject.name, ...subject.aliases].map(normalize));
    const matches = groups.filter((group) => group.some((term) => names.has(term)));
    if (matches.length) aliases[subject.id] = Array.from(new Set(matches.flat())).slice(0, 24);
  });
  return aliases;
}

export function readMaterialSubjectAliases(): SubjectSearchAliases {
  const path = process.env.STUDYHUB_MATERIAL_SEARCH_SYNONYMS_PATH
    || resolve(process.cwd(), '../private/material_search_synonyms.json');
  try {
    const stat = statSync(path);
    if (!stat.isFile() || stat.size > 256 * 1024) return {};
    const stamp = `${stat.mtimeMs}:${stat.size}`;
    if (cache?.path === path && cache.stamp === stamp) return cache.aliases;
    const aliases = publicSubjectAliases(JSON.parse(readFileSync(path, 'utf8')));
    cache = { path, stamp, aliases };
    return aliases;
  } catch {
    cache = undefined;
    return {};
  }
}
