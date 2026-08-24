# Measured benchmarks

Machine: local run on win32, Python 3.12.10,
docsqueeze 1.2.0.
Token counts use docsqueeze's calibrated BPE heuristic (chars/4 ASCII, ~1/char CJK).
'Read' models native per-page image ingestion at ~1,500 tokens/page.

| document | size | b64 tokens | Read tokens | dsq FULL | dsq @24k | saved vs baseline (full) | seconds | engine |
|---|---|---|---|---|---|---|---|---|
| synthetic PDF (30 pages) | 32.2KB | 11,016 | 45,000 | 4,069 | 4,069 | 91.0% | 0.08s | builtin |
| same PDF, pypdf accelerator | 32.2KB | 11,016 | 45,000 | 4,069 | 4,069 | 91.0% | 0.22s | pypdf |
| synthetic DOCX (400 paras) | 120.0KB | 40,974 | 0 | 27,423 | 24,082 | 33.1% | 0.09s | - |
| synthetic XLSX (5,000 rows x 8) | 1.2MB | 408,352 | 0 | 22,030 | 22,030 | 94.6% | 0.31s | - |
| real file: The-Laws-of-Human-Nature.pdf (690 pages) | 3.3MB | 1,163,800 | 1,035,000 | 654,420 | 23,517 | 36.8% | 12.68s | builtin |

Reproduce with `python tools/benchmark.py --real <file>`.
