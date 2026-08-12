import { describe, expect, it } from 'vitest';
import {
  buildUploadDraftKey,
  readUploadDraft,
  UPLOAD_DRAFT_TTL_MS,
  UploadTextDraft,
  writeUploadDraft,
} from '../../lib/uploadDraft';

class MemoryStorage implements Storage {
  private values = new Map<string, string>();
  get length() {
    return this.values.size;
  }
  clear() {
    this.values.clear();
  }
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  key(index: number) {
    return Array.from(this.values.keys())[index] ?? null;
  }
  removeItem(key: string) {
    this.values.delete(key);
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

const draft = (updatedAt: number): UploadTextDraft => ({
  version: 1,
  updatedAt,
  title: '通信原理复习资料',
  description: '包含重点与例题',
  uploadMode: 'material',
  experienceTopic: 'experience',
  experienceCustomTag: '',
  price: '0',
  school: '电子科技大学',
  college: '信通',
  selectedMajors: ['通信'],
  gradeValue: '大二',
  courseCategory: 'MAJOR',
  selectedTags: ['期末速成'],
  customTags: '',
  yearTag: '2026',
  deliveryMethod: 'FILE',
  previewSource: 'AUTO',
  previewWatermarkEnabled: true,
  customPreviewText: '',
});

describe('upload text draft', () => {
  it('isolates drafts by user and upload scope', () => {
    expect(buildUploadDraftKey(12, 'request-8')).toBe('studyhub:upload-draft:v1:12:request-8');
    expect(buildUploadDraftKey(13, 'request-8')).not.toBe(buildUploadDraftKey(12, 'request-8'));
  });

  it('round trips safe text fields and expires old drafts', () => {
    const storage = new MemoryStorage();
    const now = Date.now();
    writeUploadDraft(storage, 'draft', draft(now));
    expect(readUploadDraft(storage, 'draft', now)?.title).toBe('通信原理复习资料');
    expect(readUploadDraft(storage, 'draft', now + UPLOAD_DRAFT_TTL_MS + 1)).toBeNull();
    expect(storage.getItem('draft')).toBeNull();
  });

  it('does not persist an untouched empty form', () => {
    const storage = new MemoryStorage();
    const empty = {
      ...draft(Date.now()),
      title: '',
      description: '',
      courseCategory: '',
      selectedTags: [],
      yearTag: '',
    };
    writeUploadDraft(storage, 'draft', empty);
    expect(storage.getItem('draft')).toBeNull();
  });
});
