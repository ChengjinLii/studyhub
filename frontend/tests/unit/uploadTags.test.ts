import { describe, expect, it } from 'vitest';
import { deriveUploadTags, type UploadTagsInput } from '../../lib/uploadTags';

const base: UploadTagsInput = {
  selectedTags: [], customTags: '', yearTag: '', isExperience: false,
  resolvedExperienceExtraTag: null, maxTags: 3,
};

// Characterization of the useMemo body at 4a9c757. Do not share implementation
// helpers with the new module: this reference protects the existing ordering.
const previousTags = (input: UploadTagsInput) => {
  const { selectedTags, customTags, yearTag, isExperience, resolvedExperienceExtraTag, maxTags: MAX_TAGS } = input;
  if (isExperience) {
    return { list: ['经验分享', ...(resolvedExperienceExtraTag ? [resolvedExperienceExtraTag] : [])], trimmedCustom: false };
  }
  const trimmedYear = yearTag.trim();
  const baseSet = new Set<string>(selectedTags.filter((tag) => tag !== '经验分享'));
  if (trimmedYear) {
    if (trimmedYear !== '经验分享') baseSet.add(trimmedYear);
  }
  const customEntries = Array.from(new Set(customTags.split(/[,，\s]+/).map((tag) => tag.trim()).filter((tag) => tag && tag !== '经验分享')));
  const combined: string[] = [];
  Array.from(baseSet).forEach((tag) => { if (combined.length < MAX_TAGS) combined.push(tag); });
  let trimmedCustom = false;
  for (const tag of customEntries) {
    if (combined.length >= MAX_TAGS) {
      trimmedCustom = true;
      break;
    }
    if (!combined.includes(tag)) combined.push(tag);
  }
  return { list: combined.slice(0, MAX_TAGS), trimmedCustom };
};

describe('upload tags', () => {
  it('keeps selected tags, year and custom tags in their original priority', () => {
    expect(deriveUploadTags({ ...base, selectedTags: ['真题'], yearTag: ' 2026 ', customTags: '笔记,解析' }))
      .toEqual({ list: ['真题', '2026', '笔记'], trimmedCustom: true });
  });

  it('deduplicates without sorting and accepts existing separators', () => {
    expect(deriveUploadTags({ ...base, selectedTags: ['笔记', '笔记'], customTags: '笔记， 真题\n解析\t' }))
      .toEqual({ list: ['笔记', '真题', '解析'], trimmedCustom: false });
  });

  it('excludes the reserved experience tag for material posts', () => {
    expect(deriveUploadTags({ ...base, selectedTags: ['经验分享', '笔记'], yearTag: '经验分享', customTags: '经验分享,真题' }))
      .toEqual({ list: ['笔记', '真题'], trimmedCustom: false });
  });

  it('preserves the full-capacity warning even for a duplicate custom tag', () => {
    expect(deriveUploadTags({ ...base, selectedTags: ['A', 'B', 'C'], customTags: 'A' }))
      .toEqual({ list: ['A', 'B', 'C'], trimmedCustom: true });
    expect(deriveUploadTags({ ...base, selectedTags: ['A', 'B', 'C', 'D'] }))
      .toEqual({ list: ['A', 'B', 'C'], trimmedCustom: false });
  });

  it('keeps experience tags separate from material limits and deduplication', () => {
    expect(deriveUploadTags({ ...base, isExperience: true, selectedTags: ['ignored'], customTags: 'ignored', maxTags: 1, resolvedExperienceExtraTag: '经验分享' }))
      .toEqual({ list: ['经验分享', '经验分享'], trimmedCustom: false });
    expect(deriveUploadTags({ ...base, isExperience: true }))
      .toEqual({ list: ['经验分享'], trimmedCustom: false });
  });

  it('does not mutate selected tags', () => {
    const selectedTags = ['A', 'A', 'B'];
    Object.freeze(selectedTags);
    expect(deriveUploadTags({ ...base, selectedTags }).list).toEqual(['A', 'B']);
    expect(selectedTags).toEqual(['A', 'A', 'B']);
  });

  it('matches the previous algorithm across 2880 input combinations', () => {
    let combinations = 0;
    for (const isExperience of [false, true]) {
      for (const resolvedExperienceExtraTag of [null, '', '经验分享']) {
        for (const selectedTags of [[], ['A'], ['A', 'B', 'C'], ['A', 'A', 'B'], ['经验分享', 'A'], [' A ', '', 'B', 'C']]) {
          for (const customTags of ['', 'A', 'A,B,C,D', '经验分享，A\nB', ' ,  ']) {
            for (const yearTag of ['', '2026', ' A ', '经验分享']) {
              for (const maxTags of [0, 1, 3, 5]) {
                const input = { selectedTags, customTags, yearTag, isExperience, resolvedExperienceExtraTag, maxTags };
                expect(deriveUploadTags(input)).toEqual(previousTags(input));
                combinations += 1;
              }
            }
          }
        }
      }
    }
    expect(combinations).toBe(2880);
  });
});
