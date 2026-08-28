# MathTutor

Standalone K12 MathTutor repository extracted from the DeepTutor monorepo.

The Python distribution, import package, and console command are all named
`mathtutor`. Runtime code and packaged artifacts do not depend on the source
monorepo or its Python distribution.

## Backend development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
MATHTUTOR_DATA_ROOT=/tmp/mathtutor-data .venv/bin/mathtutor
```

The product data directory is runtime state and must not be committed.

Frontend and desktop development use their own lock files:

```bash
(cd web && npm ci && npm test && npm run build)
(cd desktop && npm ci && node --test tests/*.test.js)
```
