import type { ReactNode } from 'react';
import { LazyMotion, MotionConfig } from 'motion/react';
import { APPLE_SPRINGS } from './tokens';

const loadFeatures = () => import('./features').then((mod) => mod.default);

interface MotionProviderProps {
  children: ReactNode;
}

/**
 * Global motion engine provider.
 * Uses LazyMotion + strict <m.*> components so gesture/layout features load asynchronously
 * without bloating initial hydration bundles, while respecting prefers-reduced-motion.
 */
export function MotionProvider({ children }: MotionProviderProps) {
  return (
    <LazyMotion features={loadFeatures} strict>
      <MotionConfig reducedMotion="user" transition={APPLE_SPRINGS.gentle}>
        {children}
      </MotionConfig>
    </LazyMotion>
  );
}
