import { describe, expect, it } from 'vitest';
import { resolveInitialHomeDiscoveryView } from '../../lib/homeDiscovery';

describe('home discovery default view', () => {
  it('prioritizes requests when at least one request is available', () => {
    expect(resolveInitialHomeDiscoveryView(1)).toBe('requests');
    expect(resolveInitialHomeDiscoveryView(8)).toBe('requests');
  });

  it('falls back to popular materials when the request list is empty', () => {
    expect(resolveInitialHomeDiscoveryView(0)).toBe('popular');
  });
});
