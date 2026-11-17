import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { APPLE_EASE, APPLE_SPRINGS, APPLE_TAP, rubberBand } from '../../lib/motion/tokens';

describe('motion engine', () => {
  it('defines Apple spring presets with positive stiffness and damping', () => {
    for (const preset of Object.values(APPLE_SPRINGS)) {
      expect(preset.type).toBe('spring');
      expect(preset.stiffness).toBeGreaterThan(0);
      expect(preset.damping).toBeGreaterThan(0);
      expect(preset.mass).toBeGreaterThan(0);
    }
    expect(APPLE_EASE.ios).toHaveLength(4);
    expect(APPLE_TAP.button.scale).toBeLessThan(1);
  });

  it('applies symmetric, asymptotic rubber-band damping', () => {
    expect(rubberBand(0, 300)).toBe(0);
    expect(rubberBand(100, 0)).toBe(0);
    const pos = rubberBand(120, 300);
    const neg = rubberBand(-120, 300);
    expect(pos).toBeGreaterThan(0);
    expect(pos).toBeLessThan(120);
    expect(neg).toBe(-pos);
    expect(rubberBand(600, 300)).toBeGreaterThan(pos);
    expect(rubberBand(100000, 300)).toBeLessThanOrEqual(300);
  });

  it('wires MotionProvider into pages/_app.tsx', () => {
    const app = readFileSync(join(process.cwd(), 'pages/_app.tsx'), 'utf8');
    expect(app).toContain("import { MotionProvider } from '../lib/motion';");
    expect(app).toContain('<MotionProvider>');
    expect(app).toContain('<AppProviders initialUser={initialSessionUser}>');
  });
});
