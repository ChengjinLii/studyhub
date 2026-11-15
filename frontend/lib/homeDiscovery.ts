import type { MaterialSubjectFolder } from './materialSubjects';

export type HomeDiscoveryView = 'requests' | 'subjects' | 'popular';
export const HOME_DISCOVERY_DEFAULT_VIEW: HomeDiscoveryView = 'subjects';

export interface HomeSubjectRank {
  id: string;
  name: string;
  materialCount: number;
  downloadCount: number;
}

export function rankHomeSubjects(folders: MaterialSubjectFolder[]): HomeSubjectRank[] {
  return folders.filter((folder) => folder.id !== 'other' && folder.materials.length > 0).map((folder) => ({
    id: folder.id,
    name: folder.name,
    materialCount: folder.materials.length,
    downloadCount: folder.materials.reduce((total, material) => {
      const count = material.downloadCount;
      return total + (typeof count === 'number' && Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0);
    }, 0),
  })).sort((a, b) => b.downloadCount - a.downloadCount || b.materialCount - a.materialCount || a.name.localeCompare(b.name, 'zh-CN'));
}

/** Maps raw scroll ratio [0, 1] so the bar responds briskly early and stretches the final part. */
export function easeHomeRevealProgress(raw: number): number {
  const clamped = Math.min(1, Math.max(0, raw));
  return 0.28 * clamped + 0.72 * (1 - Math.pow(1 - clamped, 2.4));
}

/** Normalized [0, 1] intensity across the final part of the bar (from 62% to 100%). */
export function computeHomeRevealTail(progress: number): number {
  return Math.min(1, Math.max(0, (progress - 0.62) / 0.38));
}
