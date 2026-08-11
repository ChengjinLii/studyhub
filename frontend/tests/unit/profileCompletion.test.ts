import { describe, expect, it } from 'vitest';
import { getMissingProfileFields } from '../../lib/profileCompletion';
import { UserAccountProfile } from '../../types/userProfile';

const completeProfile: UserAccountProfile = {
  id: 1,
  username: 'student',
  nickname: 'Student',
  school: '电子科技大学',
  college: '信通',
  major: '通信',
  gradeStages: ['研究生'],
};

describe('profile completion', () => {
  it('returns no missing fields for a complete profile or an unavailable profile', () => {
    expect(getMissingProfileFields(completeProfile)).toEqual([]);
    expect(getMissingProfileFields(null)).toEqual([]);
  });

  it('reports each missing school field with whitespace treated as empty', () => {
    expect(
      getMissingProfileFields({
        ...completeProfile,
        school: '',
        college: ' ',
        major: null,
        gradeStages: [],
      })
    ).toEqual(['学校', '学院', '专业', '年级/阶段']);
  });
});
