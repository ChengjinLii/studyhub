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
