import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const manifest = JSON.parse(readFileSync(new URL('../../public/manifest.json', import.meta.url), 'utf8'));

describe('PWA installation assets', () => {
  it('keeps the previous application identity and covers all business routes', () => {
    expect(manifest.id).toBe('/?source=pwa');
    expect(manifest.start_url).toBe('/?source=pwa');
    expect(manifest.scope).toBe('/');
    expect(manifest.display).toBe('standalone');
    expect(manifest.shortcuts.map(item => item.url)).toEqual(['/materials', '/upload', '/me']);
  });
  it.each(manifest.icons)('has a valid full-size $sizes PNG for $src', icon => {
    const png = readFileSync(new URL(`../../public${icon.src}`, import.meta.url));
    expect(png.subarray(1, 4).toString()).toBe('PNG');
    expect(`${png.readUInt32BE(16)}x${png.readUInt32BE(20)}`).toBe(icon.sizes);
    expect(icon.type).toBe('image/png');
  });
  it('provides a distinct maskable icon and a 180px Apple icon', () => {
    expect(manifest.icons.find(icon => icon.purpose === 'maskable').src).toBe('/icons/bot-maskable.png');
    const apple = readFileSync(new URL('../../public/icons/bot-apple-touch-icon.png', import.meta.url));
    expect(apple.readUInt32BE(16)).toBe(180);
    expect(apple.readUInt32BE(20)).toBe(180);
  });
});
