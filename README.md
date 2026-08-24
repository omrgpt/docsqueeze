# docsqueeze

[![CI](https://github.com/omrgpt/docsqueeze/actions/workflows/ci.yml/badge.svg)](https://github.com/omrgpt/docsqueeze/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen)

**Token-efficient universal document reader for AI coding agents.**

One auditable, zero-dependency Python script that turns heavy documents —
PDF, DOCX, XLSX, PPTX, ODT/ODS/ODP, EPUB, RTF, HTML, XML, CSV, TSV, JSON,
JSONL, TOML, INI, EML, Jupyter notebooks, SQLite databases, logs, text —
into compact, page/sheet/slide-anchored text sized to a token budget.

Built to be *strictly better* than reading raw files (or rendering PDF pages
as images) and than existing converter tools:

| | native agent Read | markitdown / pandoc | **docsqueeze** |
|---|---|---|---|
| 30-page PDF cost | ~45,000 tokens (page images) | n/a (CLI tool) | **~13,000 full / 24k hard cap** |
| Dependencies | provider vision | heavy Python/npm trees | **zero (stdlib only)** |
| Token budgeting | none | none | **head+tail elision + fetch hints** |
| Citation anchors | page images only | inconsistent | **stable `[page N/M]` `[sheet N: name]`** |
| Adversarial hardening | n/a | not a design goal | **zip bombs, XXE, traversal, formula injection, recursion bombs** |
| Network access | n/a | some paths fetch URLs | **none. ever.** |
| Supply-chain surface | n/a | large transitive deps | **one file you can read in an afternoon** |

Measured locally with `tools/benchmark.py` (Python 3.12, Windows;
token counts via docsqueeze's calibrated BPE heuristic):

```text
document                              size   b64 tok  Read tok     FULL     24k  saved*   sec  engine
synthetic PDF (30 pages)            32.2KB    11,016    45,000    4,033    4,033   91.0%  0.25  pypdf
same PDF, stdlib engine only        32.2KB    11,016    45,000    4,033    4,033   91.0%  0.09  builtin
synthetic DOCX (400 paragraphs)    120.0KB    40,974         0   27,386   24,045   33.2%  0.10  -
synthetic XLSX (5,000 rows x 8)      1.2MB   408,352         0   21,993   21,993   94.6%  0.36  -
real file: The-Laws-of-Human-Nature  3.3MB  1,163,800 1,035,000  399,840   23,789   61.4% 36.01  pypdf
```

`saved` compares FULL extraction against the relevant worst-case baseline:
native per-page image Read for PDFs (~1,500 tok/page), raw base64 for other
formats. The real-world row is a 690-page commercial ebook: full anchored
text costs 399,840 tokens (**61.4% cheaper than the 1,035,000-token native
read**), and at the default 24k budget docsqueeze presents head+tail with
exact fetch hints at **97.7% below native cost**. Reproduce any row:

```bash
python tools/benchmark.py --builtin-pdf --real "C:\\path\\book.pdf"
```

## Install as an opencode skill (auto-activates)

```bash
python tools/sync_skill.py --to ~/.agents/skills        # global
python tools/sync_skill.py --to <project>/.agents/skills  # per project
```

Copy `.opencode/plugins/docsqueeze.ts` into your project's
`.opencode/plugins/` for deterministic auto-routing: every `read` of a
supported document is transparently rewritten to a compact text sidecar, and
a `docsqueeze` tool becomes available for targeted extraction.
Add the "Document reading policy" block from `AGENTS.md` to your project's
`AGENTS.md` so every session knows the rules.

Restart opencode after installing. That's it — no slash commands needed.

## CLI

```
python docsqueeze/core.py <file>
    [--pages 1-5,8]        PDF page selection
    [--sheets Summary,3]   xlsx/ods sheet selection
    [--max-tokens N]       token budget (default $DOCSQUEEZE_BUDGET or 24000)
    [--full]               disable truncation explicitly
    [--json]               machine-readable envelope {meta, text}
    [--stats-only]         metadata without body
    [--format pdf]         override detection
```

Exit codes: `0` ok · `2` usage · `3` unsupported · `4` security block ·
`5` parse failure · `6` I/O error · `130` interrupted.

### Output contract

```
[docsqueeze v1.1.0] file=report.pdf size=2.1MB format=pdf pages=24 engine=pypdf time=0.41s
=== [page 1/24] ===
...
[[docsqueeze elided 14 section(s) (=== [page 6/24] === .. === [page 19/24] ===, ~9,412 tokens).
 Fetch them with: docsqueeze <file> --pages 6]]
=== [page 20/24] ===
...
```

Anchors are stable across runs — cite `[page 12/24]`, re-fetch precisely.

## Engines

The built-in extractor is pure standard library: a real PDF text extractor
(object scanner, Flate/Hex/A85 streams, literal/hex strings, WinAnsi/
MacRoman, Type0/Identity-H two-byte codes, ToUnicode CMaps), OOXML readers
for DOCX/XLSX/PPTX (shared strings, inline strings, date serials, cached
formula values), ODF, EPUB spine walker, RTF deformatter, HTML-to-text,
delimited data, JSON summarizer, sqlite introspector, notebook reader.

If `pypdf` or `PyMuPDF` happens to be installed it is used automatically for
PDFs (`engine=` shows which). Force stdlib-only with
`DOCSQUEEZE_ENGINE=builtin`. No subprocess is ever spawned; no network call
is ever made.

## Security model

Input files are treated as actively malicious. See `SECURITY.md` for the
full threat model and the complete control list (zip-bomb ratio/size caps,
DTD stripping, depth guards, path-traversal rejection, CSV formula-injection
flagging, device-file refusal, encoding fallbacks, no-disk-extraction
design).

## Development

```bash
python -m unittest discover -s tests -v   # 68 tests incl. adversarial suite
python tools/benchmark.py                 # regenerate measured numbers
python tools/sync_skill.py --check        # verify skill/repo copies match
```

See `docs/BENCHMARKS.md` for the full measured table and methodology,
`CHANGELOG.md` for release history, `CONTRIBUTING.md` to hack on docsqueeze.

## Security disclosure

Found a bypass (ReDoS, bomb, traversal, injection)? See `SECURITY.md`
for the threat model and responsible-disclosure notes.

## License

MIT — see `LICENSE`.
