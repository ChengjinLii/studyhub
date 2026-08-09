import { writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const nextEnvPath = fileURLToPath(new URL('../next-env.d.ts', import.meta.url));
const content = `/// <reference types="next" />
/// <reference types="next/image-types/global" />
/// <reference path="./.next/types/routes.d.ts" />

// NOTE: This file should not be edited
// see https://nextjs.org/docs/pages/api-reference/config/typescript for more information.
`;

await writeFile(nextEnvPath, content, 'utf8');
