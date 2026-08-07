export type HomeDiscoveryView = 'requests' | 'popular';

export const resolveInitialHomeDiscoveryView = (requestCount: number): HomeDiscoveryView =>
  requestCount > 0 ? 'requests' : 'popular';
