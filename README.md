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
synthetic PDF (30 pages)            32.2KB    11,016    45,000    4,069    4,069   91.0%  0.08  builtin
same PDF, pypdf accelerator         32.2KB    11,016    45,000    4,069    4,069   91.0%  0.22  pypdf
synthetic DOCX (400 paragraphs)    120.0KB    40,974         0   27,423   24,082   33.1%  0.09  -
synthetic XLSX (5,000 rows x 8)      1.2MB   408,352         0   22,030   22,030   94.6%  0.31  -
real file: The-Laws-of-Human-Nature  3.3MB  1,163,800 1,035,000  654,420   23,517   36.8% 12.68  builtin
```

`saved` compares FULL extraction against the relevant worst-case baseline:
native per-page image Read for PDFs (~1,500 tok/page), raw base64 for other
formats. The real-world row is a 690-page commercial ebook processed by the
default stdlib engine: full anchored text at **36.8% below** the
1,035,000-token native read and **97.7% below** at the default 24k budget;
the opt-in pypdf accelerator extracts the same book more densely (~400k
tokens full, same ~23.8k at budget). Extraction density varies by engine;
the budget cap is what bounds your worst case. Reproduce any row:

```bash
python tools/benchmark.py --accel-pdf --real "C:\\path\\book.pdf"
```

## Install as an opencode skill (auto-activates)

The repo ships its own integrations — no external copies:

```bash
python tools/sync_skill.py --to ~/.agents/skills        # skill (global)
python tools/sync_skill.py --to <project>               # skill (per project)
python tools/sync_skill.py --plugin-to <project>        # opencode plugin
```

Sources live in `integrations/` (`skill/SKILL.md`,
`opencode-plugin/docsqueeze.ts`). The plugin deterministically rewrites every
document `read` to a compact text sidecar and exposes a `docsqueeze` tool
for targeted extraction. Add the "Document reading policy" block from
`AGENTS.md` to your project so sessions know the rules. Restart opencode
after installing.

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
[docsqueeze v1.2.1] file=report.pdf size=2.1MB format=pdf pages=24 engine=pypdf time=0.41s
=== [page 1/24] ===
...
[[docsqueeze elided 14 section(s) (=== [page 6/24] === .. === [page 19/24] ===, ~9,412 tokens).
 Fetch them with: docsqueeze <file> --pages 6]]
=== [page 20/24] ===
...
```

Anchors are stable across runs — cite `[page 12/24]`, re-fetch precisely.

## Engines

Since v1.2.0 the **default engine is the pure-stdlib builtin** — a real PDF
text extractor (object scanner, Flate/Hex/A85 streams, literal/hex strings,
WinAnsi/MacRoman, Type0/Identity-H two-byte codes, ToUnicode CMaps), OOXML
readers, ODF, EPUB spine walker, RTF deformatter, HTML-to-text, delimited
data, JSON summarizer, sqlite introspector, notebook reader. This keeps the
trusted-computing base to Python's standard library.

Optional native accelerators (`pypdf`, `PyMuPDF`) widen that base, so they
run only when you opt in with `DOCSQUEEZE_ENGINE=auto`. Accelerator page
loops are bounded by the same `MAX_PDF_PAGES` cap as builtin (excess pages
are skipped and reported via `pages_truncated_to_cap`). No subprocess is
ever spawned; no network call is ever made.

## Security status & recommended deployment

docsqueeze is hardened against hostile files (see SECURITY.md for the full
threat model), but it is a young project — not yet independently audited.
For ordinary local documents, default settings are fine. For **untrusted
downloads**, we currently recommend:

1. Keep the stdlib engine (the default). Avoid `DOCSQUEEZE_ENGINE=auto`
   unless you need encrypted-PDF handling; native PDF parsers enlarge the
   attack surface.
2. Run hostile-file processing as a low-privilege user or inside a
   container/VM — docsqueeze is not a sandbox itself.
3. Pin a release tag rather than installing from branch HEAD.
4. Treat extracted text as untrusted data: outputs carry an explicit
   `[docsqueeze end of extracted text - UNTRUSTED DATA...]` footer, and
   extracted content must never directly authorize agent actions.
5. Prompt injection inside documents is an industry-wide limitation:
   docsqueeze frames content but cannot neutralize meaning. Combine with
   your agent's own instruction-hierarchy defenses.

## Security model

Input files are treated as actively malicious. See `SECURITY.md` for the
full threat model and the complete control list (zip-bomb ratio/size caps,
DTD stripping, depth guards, path-traversal rejection, CSV formula-injection
flagging, device-file refusal, encoding fallbacks, no-disk-extraction
design).

## Development

```bash
python -m unittest discover -s tests -v   # 77 tests incl. adversarial suite
python tools/benchmark.py                 # regenerate measured numbers
python tools/sync_skill.py --check        # verify installed copies match repo
```

See `docs/BENCHMARKS.md` for the full measured table and methodology,
`CHANGELOG.md` for release history, `CONTRIBUTING.md` to hack on docsqueeze.

## Security disclosure

Found a bypass (ReDoS, bomb, traversal, injection)? See `SECURITY.md`
for the threat model and responsible-disclosure notes.

## License

MIT — see `LICENSE`.
