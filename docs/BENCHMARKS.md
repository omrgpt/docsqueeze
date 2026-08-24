# Measured benchmarks

Machine: local run on win32, Python 3.12.10,
docsqueeze 1.1.0.
Token counts use docsqueeze's calibrated BPE heuristic (chars/4 ASCII, ~1/char CJK).
'Read' models native per-page image ingestion at ~1,500 tokens/page.

| document | size | b64 tokens | Read tokens | dsq FULL | dsq @24k | saved vs baseline (full) | seconds | engine |
|---|---|---|---|---|---|---|---|---|
| synthetic PDF (30 pages) | 32.2KB | 11,016 | 45,000 | 4,033 | 4,033 | 91.0% | 0.24s | pypdf |
| same PDF, stdlib engine only | 32.2KB | 11,016 | 45,000 | 4,033 | 4,033 | 91.0% | 0.08s | builtin |
| synthetic DOCX (400 paras) | 120.0KB | 40,974 | 0 | 27,386 | 24,045 | 33.2% | 0.1s | - |
| synthetic XLSX (5,000 rows x 8) | 1.2MB | 408,352 | 0 | 21,993 | 21,993 | 94.6% | 0.36s | - |
| real file: The-Laws-of-Human-Nature.pdf (690 pages) | 3.3MB | 1,163,800 | 1,035,000 | 399,840 | 23,789 | 61.4% | 36.38s | pypdf |

Reproduce with `python tools/benchmark.py --real <file>`.
