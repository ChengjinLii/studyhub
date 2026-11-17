import type { Transition } from 'motion/react';

/**
 * Apple HIG inspired non-linear spring presets for StudyHub.
 * Tuned for interruptible, velocity-preserving UI interactions without excessive oscillation.
 */
export const APPLE_SPRINGS = {
  /** Tactile controls: buttons, pills, segmented controls, switches */
  snappy: {
    type: 'spring',
    stiffness: 520,
    damping: 36,
    mass: 0.8,
  },
  /** Desktop/macOS panels, dialogs, cards settling into rest */
  gentle: {
    type: 'spring',
    stiffness: 320,
    damping: 30,
    mass: 0.9,
  },
  /** Expressive physical feedback: FloatingSidebar bot, star/like micro-bounces */
  bouncy: {
    type: 'spring',
    stiffness: 420,
    damping: 22,
    mass: 0.85,
  },
  /** Mobile bottom sheets and draggable drawers */
  sheet: {
    type: 'spring',
    stiffness: 360,
    damping: 34,
    mass: 0.95,
  },
  /** Wheel picker / scroll settle */
  wheel: {
    type: 'spring',
    stiffness: 260,
    damping: 28,
    mass: 1,
  },
} as const satisfies Record<string, Transition>;

export const APPLE_EASE = {
  /** Standard iOS push/sheet cubic-bezier */
  ios: [0.32, 0.72, 0, 1] as const,
  /** Smooth deceleration curve */
  decelerate: [0.22, 1, 0.36, 1] as const,
  /** Fast responsive exit/enter */
  swift: [0.2, 0, 0, 1] as const,
} as const;

export const APPLE_TAP = {
  subtle: { scale: 0.985 },
  button: { scale: 0.965 },
  icon: { scale: 0.92 },
} as const;

export const APPLE_VIEWPORT = {
  once: true,
  amount: 0.15,
} as const;

/**
 * Apple UIScrollView style rubber-band resistance curve for over-drag / boundary damping.
 */
export function rubberBand(offset: number, dimension: number, constant = 0.55): number {
  if (!Number.isFinite(offset) || !Number.isFinite(dimension) || dimension <= 0) {
    return 0;
  }
  const absOffset = Math.abs(offset);
  const clampedConstant = Math.max(0.01, constant);
  const resisted =
    (absOffset * dimension * clampedConstant) / (dimension + clampedConstant * absOffset);
  return offset < 0 ? -resisted : resisted;
}
