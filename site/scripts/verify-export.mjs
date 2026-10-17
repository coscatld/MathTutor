import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const outDir = join(process.cwd(), 'out');
const errors = [];

function fail(message) {
  errors.push(message);
}

function walk(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    const st = statSync(path);
    if (st.isDirectory()) walk(path, acc);
    else acc.push(path);
  }
  return acc;
}

if (!existsSync(outDir)) fail('out/ does not exist');
if (!existsSync(join(outDir, '.nojekyll'))) fail('missing out/.nojekyll');
if (!existsSync(join(outDir, 'index.html'))) fail('missing out/index.html');
if (!existsSync(join(outDir, '404.html'))) fail('missing out/404.html');

const required = [
  'zh/index.html',
  'en/index.html',
  'zh/features/index.html',
  'en/features/index.html',
  'zh/download/index.html',
  'en/download/index.html',
  'zh/architecture/index.html',
  'en/architecture/index.html',
  'zh/roadmap/index.html',
  'en/roadmap/index.html',
  'zh/docs/index.html',
  'en/docs/index.html',
  'zh/docs/user/introduction/index.html',
  'en/docs/user/introduction/index.html',
  'zh/docs/developer/architecture/index.html',
  'en/docs/developer/architecture/index.html',
  'sitemap.xml',
  'robots.txt',
  'favicon.svg',
  'screenshots/teaching-desktop.png',
];

for (const rel of required) {
  if (!existsSync(join(outDir, rel))) fail(`missing ${rel}`);
}

const htmlFiles = existsSync(outDir)
  ? walk(outDir).filter((p) => p.endsWith('.html') || p.endsWith('.xml') || p.endsWith('.txt'))
  : [];

for (const file of htmlFiles) {
  const text = readFileSync(file, 'utf8');
  if (text.includes('http://localhost') || text.includes('https://localhost')) {
    fail(`localhost URL in ${file.slice(outDir.length + 1)}`);
  }
}

const sample = existsSync(join(outDir, 'zh/index.html'))
  ? readFileSync(join(outDir, 'zh/index.html'), 'utf8')
  : '';
if (sample && !sample.includes('/MathTutor/')) {
  fail('zh/index.html does not reference /MathTutor/ assets or links');
}
if (sample.includes('href="/_next/') || sample.includes('src="/_next/')) {
  fail('zh/index.html has root-relative _next URLs without /MathTutor');
}
if (sample.includes('src="/screenshots/') || sample.includes("src='/screenshots/")) {
  fail('zh/index.html screenshot src is missing the /MathTutor basePath');
}
if (!sample.includes('src="/MathTutor/screenshots/')) {
  fail('zh/index.html does not reference /MathTutor/screenshots/');
}

if (existsSync(join(outDir, 'sitemap.xml'))) {
  const sitemap = readFileSync(join(outDir, 'sitemap.xml'), 'utf8');
  if (!sitemap.includes('https://coscatld.github.io/MathTutor/')) {
    fail('sitemap.xml missing GitHub Pages origin');
  }
  if (sitemap.includes('localhost')) fail('sitemap.xml contains localhost');
}

if (existsSync(join(outDir, 'robots.txt'))) {
  const robots = readFileSync(join(outDir, 'robots.txt'), 'utf8');
  if (!robots.includes('https://coscatld.github.io/MathTutor/sitemap.xml')) {
    fail('robots.txt sitemap URL is not the GitHub Pages URL');
  }
}

if (errors.length) {
  console.error('verify-export failed:');
  for (const error of errors) console.error(' -', error);
  process.exit(1);
}

console.log(`verify-export ok (${htmlFiles.length} text files scanned)`);
