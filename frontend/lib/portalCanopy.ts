/**
 * Shared SVG straight-horizon geometry for the home portal dark canopy and the
 * opening splash so the dark upper stage aligns seamlessly at handoff.
 */
export const PORTAL_CANOPY_VIEWBOX_WIDTH = 1440;
export const PORTAL_CANOPY_VIEWBOX_HEIGHT = 736;
export const PORTAL_CANOPY_LEFT_Y = 678;
export const PORTAL_CANOPY_CENTER_Y = 678;
export const PORTAL_CANOPY_RIGHT_Y = 678;

export const PORTAL_CANOPY_RIM_PATH = 'M 0,678 L 1440,678';

export const PORTAL_CANOPY_FILL_PATH =
  `M 0,0 L 1440,0 L 1440,${PORTAL_CANOPY_RIGHT_Y} L 0,${PORTAL_CANOPY_LEFT_Y} Z`;
