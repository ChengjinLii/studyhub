export type HomeDiscoveryView = 'requests' | 'popular' | 'cooperation';

export const resolveInitialHomeDiscoveryView = (requestCount: number): HomeDiscoveryView =>
  requestCount > 0 ? 'requests' : 'popular';
