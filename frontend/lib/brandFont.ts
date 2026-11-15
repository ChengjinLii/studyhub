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

// Instrument Sans (SIL OFL 1.1, see styles/fonts/InstrumentSans-OFL.txt): the "StudyHub"
// wordmark face, chosen for its crisp neo-grotesque stems alongside the geometric S chevron.
export const wordmarkFont = localFont({
  src: '../styles/fonts/instrument-sans-latin-wght-normal.woff2',
  weight: '400 700',
  style: 'normal',
  display: 'block',
  variable: '--font-wordmark',
  preload: true,
});
