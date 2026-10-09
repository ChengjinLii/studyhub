import { MATERIAL_SUBJECTS, OTHER_MATERIAL_SUBJECT, MaterialSubject } from '../constants/materialSubjects';
import { MaterialListItem } from '../types/material';

export interface MaterialSubjectFolder extends Pick<MaterialSubject, 'id' | 'name'> {
  materials: MaterialListItem[];
}

const normalize = (value: string) => value.normalize('NFKC').replace(/_/g, ' ').toLowerCase();
const escapePattern = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const matchers = MATERIAL_SUBJECTS.map((subject) => ({
  subject,
  patterns: subject.aliases.map((alias) => {
    const normalized = normalize(alias);
    return /^[a-z\d &]+$/.test(normalized)
      ? new RegExp(`(?:^|[^a-z])${escapePattern(normalized)}(?:$|[^a-z])`, 'i')
      : new RegExp(escapePattern(normalized), 'i');
  }),
}));

export function materialSubject(material: Pick<MaterialListItem, 'title'>): MaterialSubject {
  const title = normalize(material.title);
  // Match the title only: descriptions often mention other courses incidentally.
  return matchers.find(({ patterns }) => patterns.some((pattern) => pattern.test(title)))?.subject || OTHER_MATERIAL_SUBJECT;
}

export function groupMaterialSubjects(materials: MaterialListItem[]): MaterialSubjectFolder[] {
  const folders = new Map<string, MaterialSubjectFolder>();
  const seen = new Set<number>();
  materials.forEach((material) => {
    if (seen.has(material.id)) return;
    seen.add(material.id);
    const subject = materialSubject(material);
    const folder = folders.get(subject.id) || { ...subject, materials: [] };
    folder.materials.push(material);
    folders.set(subject.id, folder);
  });
  return Array.from(folders.values()).sort((a, b) => {
    if (a.id === 'other') return 1;
    if (b.id === 'other') return -1;
    return b.materials.length - a.materials.length || a.name.localeCompare(b.name, 'zh-CN');
  });
}

export function filterSubjectFolders(folders: MaterialSubjectFolder[], filters: Record<string, string>): MaterialSubjectFolder[] {
  const terms = normalize(filters.keyword || '').trim().split(/\s+/).filter(Boolean);
  const fields = ['school', 'college', 'major', 'gradeValue', 'courseCategory'] as const;
  return folders.map((folder) => {
    const materials = folder.materials.filter((item) => {
      if (fields.some((field) => filters[field] && item[field] !== filters[field])) return false;
      if (filters.tag && !item.tags?.includes(filters.tag)) return false;
      if (filters.price === 'free' && !item.free) return false;
      if (filters.price === 'paid' && item.free) return false;
      const text = normalize([folder.name, item.title, item.description, ...(item.tags || [])].join(' '));
      return terms.every((term) => text.includes(term));
    });
    materials.sort((a, b) => {
      const downloads = (b.downloadCount || 0) - (a.downloadCount || 0);
      const newest = (Date.parse(b.createdAt || '') || 0) - (Date.parse(a.createdAt || '') || 0) || b.id - a.id;
      return filters.sort === 'newest' ? newest : downloads || newest;
    });
    return { id: folder.id, name: folder.name, materials };
  }).filter((folder) => folder.materials.length > 0);
}
