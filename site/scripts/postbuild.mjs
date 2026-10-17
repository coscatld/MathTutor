import { writeFileSync, copyFileSync, existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';

const outDir = join(process.cwd(), 'out');
if (!existsSync(outDir)) {
  console.error('postbuild: missing out/');
  process.exit(1);
}

writeFileSync(join(outDir, '.nojekyll'), '');

const notFound = join(outDir, '404.html');
if (existsSync(notFound)) {
  // GitHub Pages serves /404.html for unknown paths on project sites.
  copyFileSync(notFound, join(outDir, '404.html'));
}

const cnameSkip = join(outDir, 'CNAME');
if (existsSync(cnameSkip)) {
  // Project site uses coscatld.github.io/MathTutor, not a custom domain.
}

console.log('postbuild: wrote out/.nojekyll');
