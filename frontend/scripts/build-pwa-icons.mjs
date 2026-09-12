import sharp from 'sharp';
import { fileURLToPath } from 'node:url';

const source = fileURLToPath(new URL('../public/icons/studyhub-app.svg', import.meta.url));
for (const [name, size] of [['bot-192.png', 192], ['bot-512.png', 512], ['bot-apple-touch-icon.png', 180]]) {
  const icon = sharp(source).resize(size, size);
  if (name.includes('apple')) icon.flatten({ background: '#080b12' });
  await icon.png().toFile(fileURLToPath(new URL(`../public/icons/${name}`, import.meta.url)));
}
await sharp(source).flatten({ background: '#080b12' }).png()
  .toFile(fileURLToPath(new URL('../public/icons/bot-maskable.png', import.meta.url)));
