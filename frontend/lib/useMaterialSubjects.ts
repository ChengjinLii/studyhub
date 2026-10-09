import { useMemo } from 'react';
import catalogue from '../data/material-subject-catalogue.json';
import { filterSubjectFolders } from './materialSubjects';

export type MaterialBrowseMode = 'materials' | 'subjects';

export function useMaterialSubjects(filters: Record<string, string>) {
  const { keyword, school, college, major, tag, gradeValue, courseCategory, price, sort } = filters;
  const folders = useMemo(() => filterSubjectFolders(catalogue.folders, {
    keyword, school, college, major, tag, gradeValue, courseCategory, price, sort,
  }), [keyword, school, college, major, tag, gradeValue, courseCategory, price, sort]);
  const items = useMemo(() => folders.flatMap((folder) => folder.materials), [folders]);
  return { folders, items, updatedAt: catalogue.updatedAt };
}
