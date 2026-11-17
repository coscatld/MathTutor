import { readFileSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import openapiTS, { astToString } from 'openapi-typescript'

const root = fileURLToPath(new URL('../../', import.meta.url))
const check = process.argv.includes('--check')
const result = spawnSync(
  process.env.PYTHON || 'python',
  ['scripts/export_api_schema.py', ...(check ? ['--check'] : [])],
  {
    cwd: root,
    stdio: 'inherit',
    env: { ...process.env, PYTHONPATH: path.join(root, 'src') },
  }
)
if (result.error) throw result.error
if (result.status !== 0) process.exit(result.status ?? 1)
const directory = path.join(root, 'web/features/math-tutor/desktop/generated')
const output = astToString(
  await openapiTS(JSON.parse(readFileSync(path.join(directory, 'openapi.json'), 'utf8')), {
    defaultNonNullable: false,
  })
)
const target = path.join(directory, 'api.d.ts')
if (check) {
  if (readFileSync(target, 'utf8') !== output)
    throw new Error('HTTP types are stale; run npm run api:generate.')
} else writeFileSync(target, output)
