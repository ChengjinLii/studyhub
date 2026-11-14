import localFont from 'next/font/local';

// Jost (SIL OFL 1.1, see styles/fonts/Jost-OFL.txt): the display numeral face.
export const brandFont = localFont({
  src: '../styles/fonts/jost-latin-wght-normal.woff2',
  weight: '100 900',
  style: 'normal',
  display: 'swap',
  variable: '--font-brand',
  preload: true,
});

// Outfit (SIL OFL 1.1, see styles/fonts/Outfit-OFL.txt): the "StudyHub" wordmark face. Its round,
// even letters hold up at the large size the wordmark has over the home search box.
export const wordmarkFont = localFont({
  src: '../styles/fonts/outfit-latin-wght-normal.woff2',
  weight: '100 900',
  style: 'normal',
  display: 'swap',
  variable: '--font-wordmark',
  preload: true,
});
