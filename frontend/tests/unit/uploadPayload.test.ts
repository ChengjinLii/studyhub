import { describe, expect, it } from 'vitest';
import { buildUploadPayload, deriveUploadGradeType } from '../../lib/uploadPayload';

describe('uploadPayload', () => {
  it('builds material payload with normalized money, majors, tags, and netdisk fields', () => {
    const payload = buildUploadPayload({
      title: '高数资料',
      description: '期末复习',
      priceValue: 3,
      school: '电子科技大学',
      college: '计算机科学与工程学院',
      majors: ['计算机科学与技术', '软件工程'],
      gradeValue: '大二',
      courseCategory: 'MAJOR',
      tags: ['期末真题', '2024'],
      deliveryMethod: 'NETDISK',
      netdiskUrl: ' https://disk.example/a ',
      netdiskPassword: ' abcd ',
      netdiskExpiredAt: '2026-12-01',
      netdiskReminderAt: '',
      previewWatermarkEnabled: true,
      previewSource: 'MANUAL',
      customPreviewText: ' 目录预览 ',
      copyrightOwner: '张三',
      isExperience: false,
      isQuickMode: false,
      isEditing: false,
      requestId: 12,
      customPreviewClear: false,
    });

    expect(payload).toMatchObject({
      price: 300,
      generalCourse: false,
      deliveryMethod: 'NETDISK',
      netdiskUrl: 'https://disk.example/a',
      netdiskPassword: 'abcd',
      customPreviewText: '目录预览',
      copyrightOwner: '张三',
      requestId: 12,
    });
    expect(payload.major).toContain('计算机科学与技术');
    expect(payload.tags).toBe('期末真题,2024');
  });

  it('clears paid delivery and copyright-only fields for experience posts', () => {
    const payload = buildUploadPayload({
      title: '经验分享',
      description: '内容',
      priceValue: 0,
      school: '电子科技大学',
      college: '',
      majors: [],
      gradeValue: '研究生',
      courseCategory: 'GENERAL',
      tags: ['经验分享'],
      deliveryMethod: 'FILE',
      netdiskUrl: 'https://disk.example/a',
      netdiskPassword: 'abcd',
      netdiskExpiredAt: '2026-12-01',
      netdiskReminderAt: '提醒',
      previewWatermarkEnabled: true,
      previewSource: 'AUTO',
      customPreviewText: '',
      copyrightOwner: '张三',
      isExperience: true,
      isQuickMode: false,
      isEditing: true,
      requestId: null,
      customPreviewClear: true,
    });

    expect(payload.netdiskUrl).toBeNull();
    expect(payload.netdiskPassword).toBeNull();
    expect(payload.netdiskExpiredAt).toBeNull();
    expect(payload.netdiskReminderAt).toBeNull();
    expect(payload.copyrightOwner).toBeNull();
    expect(payload.customPreviewClear).toBe(true);
    expect(payload.gradeType).toBe('GR');
  });

  it('derives grade type for skill stages', () => {
    expect(deriveUploadGradeType('英语')).toBe('SKILL');
    expect(deriveUploadGradeType('技能')).toBe('SKILL');
    expect(deriveUploadGradeType('大一')).toBe('UG');
  });
});
