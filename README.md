# docsqueeze

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

Measured with `tools/benchmark.py` on this machine:

```text
document                    raw size   b64 tokens  native Read    dsq FULL  dsq BUDGET   saved
PDF  (30 pages)              32.4KB       11,082       45,000      13,160      13,160   70.8% vs Read
DOCX (400 paragraphs)       120.0KB       40,970            0      27,386      24,046   33.2% vs b64
XLSX (5,000 rows x 8)         1.2MB      408,336            0      21,993      21,993   94.6% vs b64
```

A real-world run: a **690-page** commercial ebook extracted to full anchored
text (~400k tokens, still 61% cheaper than the >1M-token native read) in
~34s; at the default budget it presents the first/last sections plus exact
re-fetch hints for ~24k tokens total.

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
[docsqueeze v1.0.0] file=report.pdf size=2.1MB format=pdf pages=24 engine=pypdf time=0.41s
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
python -m unittest discover -s tests -v   # 55 tests incl. adversarial suite
python tools/benchmark.py                 # regenerate measured numbers
python tools/sync_skill.py --check        # verify skill/repo copies match
```

## License

MIT — see `LICENSE`.
