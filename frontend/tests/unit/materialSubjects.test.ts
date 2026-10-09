import { describe, expect, it } from 'vitest';
import { filterSubjectFolders, groupMaterialSubjects, materialSubject } from '../../lib/materialSubjects';
import catalogue from '../../data/material-subject-catalogue.json';
import type { MaterialListItem } from '../../types/material';

const material = (id: number, title: string): MaterialListItem => ({ id, title, free: true, price: 0 });

describe('material subjects', () => {
  it.each([
    ['CPS六年期末考答案自制（2019-2024）', 'communication-principles'],
    ['通信原理手写笔记', 'communication-principles'],
    ['ESD2022期末卷UESTC3003_1_Electronic_System_Design_3', 'esd'],
    ['ESD-电子系统设计-2021年真题及答案', 'esd'],
    ['ADC-高阶数字通信-期中样卷答案', 'adc'],
    ['DC-数字通信-期末笔记', 'digital-communication'],
    ['大物实验 Physics EXP II', 'physics-lab'],
    ['大学物理II - PPT', 'physics'],
    ['AI & ML 25~26 PPT复习笔记', 'ai-ml'],
    ['DCD五年期末考答案', 'digital-logic'],
    ['Matrix_Theory.pdf', 'matrix'],
    ['研究生学术英语基本知识与技能', 'graduate-english'],
    ['EfES A Final Exam', 'academic-english'],
    ['domain name tutorial', 'other'],
    ['Another Sample', 'other'],
  ])('classifies %s without guessing from incidental description text', (title, id) => {
    expect(materialSubject({ title }).id).toBe(id);
  });

  it('groups aliases, keeps each material once, and keeps unknown titles visible', () => {
    const items = [material(1, 'CPS真题'), material(2, '通信原理笔记'), material(3, '未分类内容'), material(1, 'CPS真题')];
    const folders = groupMaterialSubjects(items);
    expect(folders.map((folder) => [folder.id, folder.materials.length])).toEqual([
      ['communication-principles', 2], ['other', 1],
    ]);
  });

  it('keeps a complete, nonduplicated offline snapshot of public card metadata', () => {
    const items = catalogue.folders.flatMap((folder) => folder.materials);
    expect(items).toHaveLength(catalogue.total);
    expect(new Set(items.map((item) => item.id)).size).toBe(catalogue.total);
    expect(new Set(catalogue.folders.map((folder) => folder.id)).size).toBe(catalogue.folders.length);
    expect(Number.isNaN(Date.parse(catalogue.updatedAt))).toBe(false);
    const allowed = new Set(['id', 'title', 'price', 'free', 'school', 'college', 'major', 'courseCategory',
      'generalEducation', 'gradeValue', 'tags', 'ratingAvg', 'ratingCount', 'likeCount', 'commentCount',
      'viewCount', 'downloadCount', 'createdAt', 'uploaderId', 'uploaderNickname']);
    items.forEach((item) => expect(Object.keys(item).every((key) => allowed.has(key))).toBe(true));
  });

  it('filters the stored folders locally without reclassifying their assignments', () => {
    const folders = [{ id: 'reviewed', name: '人工整理的学科', materials: [
      { ...material(1, 'ESD期末真题'), school: '电子科技大学', tags: ['期末真题'] },
      { ...material(2, 'ESD课堂笔记'), school: '电子科技大学', tags: ['日常笔记'] },
      { ...material(3, '微积分期末真题'), school: '其他学校' },
    ] }];
    const result = filterSubjectFolders(folders, { keyword: 'ESD 期末', school: '电子科技大学', tag: '期末真题' });
    expect(result.map((folder) => [folder.id, folder.materials.map((item) => item.id)])).toEqual([['reviewed', [1]]]);
    expect(filterSubjectFolders(folders, { keyword: '找不到的资料' })).toEqual([]);
    expect(folders[0].materials).toHaveLength(3);
  });

  it('keeps exact metadata and price filters, and sorts without mutating the snapshot', () => {
    const folders = [{ id: 'esd', name: '电子系统设计', materials: [
      { ...material(1, 'ESD'), college: '格院', major: '电工', courseCategory: 'MAJOR', gradeValue: '大三', downloadCount: 8, createdAt: '2025-01-01' },
      { ...material(2, 'ESD'), college: '格院', major: '电工', courseCategory: 'MAJOR', gradeValue: '大三', free: false, price: 1, downloadCount: 2, createdAt: '2026-01-01' },
    ] }];
    expect(filterSubjectFolders(folders, { sort: 'newest' })[0].materials.map((x) => x.id)).toEqual([2, 1]);
    expect(filterSubjectFolders(folders, { sort: 'downloads' })[0].materials.map((x) => x.id)).toEqual([1, 2]);
    expect(filterSubjectFolders(folders, { price: 'paid', college: '格院', major: '电工', courseCategory: 'MAJOR', gradeValue: '大三' })[0].materials.map((x) => x.id)).toEqual([2]);
    expect(filterSubjectFolders(folders, { college: '信通' })).toEqual([]);
    expect(filterSubjectFolders(folders, { price: 'free' })[0].materials.map((x) => x.id)).toEqual([1]);
    expect(folders[0].materials.map((x) => x.id)).toEqual([1, 2]);
  });
});
