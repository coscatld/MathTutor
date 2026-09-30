# Third-party notices

## CSSwitch

- Project: [SuperJJ007/CSSwitch](https://github.com/SuperJJ007/CSSwitch)
- Source commit: `4e0af6ba7909dca22f1257b168172ecbe4af4836`
- License: MIT
- Copyright: Copyright (c) 2026 shanjunjie
- Adapted concepts: PKCE loopback login, auth generations, atomic credential updates, model-catalog cache invalidation, and redacted operation states.

DeepTutor's Codex OAuth support draws on the design concepts listed above and
implements them independently against DeepTutor's own settings directory, model
catalog, and provider lifecycle. The MIT license text from that source commit
follows:

```text
MIT License

Copyright (c) 2026 shanjunjie

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## ASSISTments 2009–2010 skill builder data (bundled DKT weights)

- Bundled asset: `src/mathtutor/learning/knowledge_tracing/assets/assist2009-source-v2-seed29/model.json`
  (SHA-256 `d30fb23c69ce995874ad6466d7a32ec41accca2f6afcebe2e62dd3603a3c03a4`).
- What it is: numeric weights of a single-layer LSTM (DKT) trained on the public
  ASSISTments 2009–2010 skill builder dataset (corrected, collapsed). No raw dataset
  rows, student identifiers or CSV files are distributed with the application.
- Source dataset: ASSISTments, Worcester Polytechnic Institute. Please cite:
  Feng, M., Heffernan, N. T., & Koedinger, K. R. (2009). Addressing the assessment
  challenge with an online system that tutors as it assesses. *User Modeling and
  User-Adapted Interaction*, 19(3), 243–266.
- Licensing status: the dataset's terms of use for redistributing derived model
  weights in a distributed application have **not yet been confirmed** by the
  project. Treat this asset as research-only until that review is recorded.
- Product use: shadow mode only; it does not control teaching and yields no
  probability for MathTutor tasks.
