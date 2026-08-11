import { UserAccountProfile } from '../types/userProfile';

export const getMissingProfileFields = (profile: UserAccountProfile | null): string[] => {
  if (!profile) return [];

  const missing: string[] = [];
  if (!profile.school?.trim()) missing.push('学校');
  if (!profile.college?.trim()) missing.push('学院');
  if (!profile.major?.trim()) missing.push('专业');
  if (!(profile.gradeStages ?? []).some((stage) => stage.trim())) missing.push('年级/阶段');
  return missing;
};
