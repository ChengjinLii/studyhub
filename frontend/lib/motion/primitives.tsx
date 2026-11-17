import type { HTMLMotionProps } from 'motion/react';
import { m } from 'motion/react';
import type { ReactNode } from 'react';
import { APPLE_SPRINGS, APPLE_TAP } from './tokens';

interface SpringPressProps extends Omit<HTMLMotionProps<'div'>, 'whileTap' | 'transition'> {
  children: ReactNode;
  variant?: keyof typeof APPLE_TAP;
  hoverLift?: boolean;
  disabled?: boolean;
}

/**
 * Tactile spring-press wrapper for buttons, cards, and interactive chips.
 */
export function SpringPress({
  children,
  variant = 'button',
  hoverLift = false,
  disabled = false,
  ...rest
}: SpringPressProps) {
  return (
    <m.div
      whileTap={disabled ? undefined : APPLE_TAP[variant]}
      whileHover={disabled || !hoverLift ? undefined : { y: -2 }}
      transition={APPLE_SPRINGS.snappy}
      {...rest}
    >
      {children}
    </m.div>
  );
}

interface SegmentedPillProps {
  layoutId: string;
  className?: string;
}

/**
 * Shared-element spring capsule indicator for segmented controls and tabs.
 */
export function SegmentedPill({ layoutId, className }: SegmentedPillProps) {
  return (
    <m.span
      layoutId={layoutId}
      className={className}
      transition={APPLE_SPRINGS.snappy}
      aria-hidden="true"
    />
  );
}

interface AppleRevealProps extends Omit<HTMLMotionProps<'div'>, 'initial' | 'animate' | 'transition'> {
  children: ReactNode;
  delay?: number;
  yOffset?: number;
}

/**
 * Subtle non-linear entrance transition with gentle scale settle.
 */
export function AppleReveal({ children, delay = 0, yOffset = 10, ...rest }: AppleRevealProps) {
  return (
    <m.div
      initial={{ opacity: 0, y: yOffset, scale: 0.985 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ ...APPLE_SPRINGS.gentle, delay }}
      {...rest}
    >
      {children}
    </m.div>
  );
}
