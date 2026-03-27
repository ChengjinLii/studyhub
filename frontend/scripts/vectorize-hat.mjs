import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import ImageTracer from 'imagetracerjs';
import PNGReader from 'imagetracerjs/nodecli/PNGReader.js';
import { optimize } from 'svgo';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');
const inputPath = path.join(rootDir, 'public', 'xmas', 'hat-ref.png');
const rawPath = path.join(rootDir, 'public', 'xmas', 'hat-ref.raw.svg');
const outputPath = path.join(rootDir, 'public', 'xmas', 'hat-ref.svg');

const options = {
  colorsampling: 2,
  numberofcolors: 12,
  ltres: 0.5,
  qtres: 0.5,
  pathomit: 2,
  strokewidth: 0,
  roundcoords: 1,
  viewbox: true,
  linefilter: true,
};

const readPng = async () => {
  const bytes = await fs.readFile(inputPath);
  return new Promise((resolve, reject) => {
    const reader = new PNGReader(bytes);
    reader.parse((err, png) => {
      if (err) {
        reject(err);
        return;
      }
      resolve({ width: png.width, height: png.height, data: png.pixels });
    });
  });
};

const main = async () => {
  const imageData = await readPng();
  const rawSvg = ImageTracer.imagedataToSVG(imageData, options);
  await fs.writeFile(rawPath, rawSvg, 'utf8');

  const optimized = optimize(rawSvg, {
    multipass: true,
    plugins: [{ name: 'preset-default' }, 'removeDimensions'],
  });

  await fs.writeFile(outputPath, optimized.data, 'utf8');
  console.log(`Saved: ${outputPath}`);
};

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
