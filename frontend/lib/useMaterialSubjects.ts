import { useMemo } from 'react';
import catalogue from '../data/material-subject-catalogue.json';
import { filterSubjectFolders, searchSubjectFolders, SubjectSearchAliases } from './materialSubjects';

export type MaterialBrowseMode = 'materials' | 'subjects';
const EMPTY_ALIASES: SubjectSearchAliases = {};

export function useMaterialSubjects(filters: Record<string, string>, aliases: SubjectSearchAliases = EMPTY_ALIASES) {
  const { keyword, school, college, major, tag, gradeValue, courseCategory, price, sort } = filters;
  const folders = useMemo(() => filterSubjectFolders(catalogue.folders, {
    keyword, school, college, major, tag, gradeValue, courseCategory, price, sort,
  }, aliases), [keyword, school, college, major, tag, gradeValue, courseCategory, price, sort, aliases]);
  const allFolders = useMemo(() => filterSubjectFolders(catalogue.folders, {
    keyword: '', school, college, major, tag, gradeValue, courseCategory, price, sort,
  }), [school, college, major, tag, gradeValue, courseCategory, price, sort]);
  const relatedFolders = useMemo(() => searchSubjectFolders(allFolders, keyword || '', aliases), [allFolders, keyword, aliases]);
  const items = useMemo(() => folders.flatMap((folder) => folder.materials), [folders]);
  return { folders, allFolders, relatedFolders, items, updatedAt: catalogue.updatedAt };
}
