/**
 * Shared SVG curve geometry for the desktop home portal canopy and the swirling
 * opening splash so the dark Yin stage aligns seamlessly at handoff.
 */
export const PORTAL_CANOPY_VIEWBOX_WIDTH = 1440;
export const PORTAL_CANOPY_VIEWBOX_HEIGHT = 736;
export const PORTAL_CANOPY_LEFT_Y = 686;
export const PORTAL_CANOPY_CENTER_Y = 678;
export const PORTAL_CANOPY_RIGHT_Y = 654;

export const PORTAL_CANOPY_RIM_PATH =
  'M 0,686 C 260,722 510,690 720,678 C 930,666 1190,646 1440,654';

export const PORTAL_CANOPY_FILL_PATH =
  `M 0,0 L 1440,0 L 1440,${PORTAL_CANOPY_RIGHT_Y} C 1190,646 930,666 720,${PORTAL_CANOPY_CENTER_Y} C 510,690 260,722 0,${PORTAL_CANOPY_LEFT_Y} Z`;
