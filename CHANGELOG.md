# Changelog

All notable changes to docsqueeze are documented here.
Format follows Keep a Changelog; versioning follows SemVer.

## [1.2.0] - 2026-08-24

### Security
- **Zip-bomb caps now run before any decompression.** The eager
  `ZipFile.testzip()` pass (which decompressed every member before the size/
  ratio caps could apply) is removed. Metadata checks — entry count,
  declared sizes, aggregate cap, ratio, names, symlinks — touch only the
  central directory; CRC integrity is verified per-member by `zipfile`
  during each budgeted read, failing closed with `SecurityError`.
  Timing-bounded regression test added.
- **PDF page cap now applies to optional accelerators.** pypdf/PyMuPDF page
  loops iterate only up to `MAX_PDF_PAGES` (excess pages reported via
  `pages_truncated_to_cap` / `pdf_total_pages`). Previously a 100k-page PDF
  was fully processed when an accelerator was installed. Regression test
  with a patched 25-page cap over a 120-page fixture.
- **Stdlib engine is now the default.** `DOCSQUEEZE_ENGINE` defaults to
  `builtin`; native accelerators (pypdf/PyMuPDF) are opt-in via `auto`,
  keeping the trusted-computing base at Python's standard library unless
  explicitly widened.
- Every output now ends with an explicit UNTRUSTED-DATA footer and
  `untrusted_notice` metadata, framing extracted text as data rather than
  instructions (prompt-injection mitigation; see SECURITY.md limitations).

### Changed
- The opencode skill and plugin are now shipped inside the repo under
  `integrations/`; `tools/sync_skill.py` installs from the repo as the
  canonical source and can also install the plugin (`--plugin-to`).

## [1.1.1] - 2026-08-24

### Fixed
- Token-budget window caps now scale with `--max-tokens`. Previously the
  head/tail windows carried fixed 300/200-token floors, so a tiny request
  (e.g. `--max-tokens 250`) could return ~4x the requested budget on
  small-cap docs. Caps now derive from the budget itself, and when a
  windowed head consumes the entire allowance the tail is omitted in favor
  of an elision banner instead of double-spending.
- Discovered during a 150-scenario real-world user simulation across 31
  documents (PDF/DOCX/XLSX/PPTX/ODT/EPUB/HTML/RTF/CSV/JSON/JSONL/TOML/
  INI/EML/IPYNB/SQLite/logs/zip incl. 6 malicious fixtures).

## [1.1.0] - 2026-08-24

### Security
- Replaced the regex-based DTD stripper with a single-pass linear scanner:
  adversarial XML containing thousands of unterminated `<!DOCTYPE`
  declarations could previously trigger quadratic backtracking (ReDoS-class).
  Fuzz-style timing test added.
- Replaced lazy-DOTALL CMap block parsing with an index-advancing bounded
  scanner: crafted ToUnicode maps full of `beginbfchar` markers without
  terminators were quadratic on up to 8 MB inputs. Timing test added.
- `detect_office_kind` no longer loads whole zip entries into memory to sniff
  them (`[Content_Types].xml`, `mimetype` are now read through a 64 KB/256 B
  bounded head reader), closing a memory-amplification vector via a giant
  first entry. Test with a 40 MB compressed entry added.
- CSV formula-injection flagging extended per OWASP guidance: leading `-`
  cells are flagged when they look like formulas, while plain negative
  numbers stay untouched. Regression tests for both sides.
- Numeric character references (`&#233;`, `&#xE8;`) survive the entity
  neutralization pass instead of being mangled into literal text.

### Fixed
- Elision banner is now inserted *between* head and tail sections instead of
  after the tail (positional regression test added).
- `_window_body` adapts to token density, so CJK-heavy sections window at
  roughly one character per token instead of overflowing the budget ~4x.
- Removed duplicated extension checks in format sniffing; HTML detection
  window widened from 8 KB to 256 KB for minified pages.

## [1.0.0] - 2026-08-24

### Added
- Zero-dependency stdlib engine: PDF text extraction (object scanner,
  FlateDecode/ASCIIHex/ASCII85 streams, literal/hex strings, escapes,
  WinAnsi/MacRoman, Type0/Identity-H two-byte codes, bfchar/bfrange
  ToUnicode CMaps), DOCX/XLSX/PPTX readers (shared strings, inline strings,
  date serials incl. 1904 workbooks, cached formula values), ODT/ODS/ODP,
  EPUB spine walker, RTF de-formatter, HTML-to-text, XML tree renderer,
  CSV/TSV with delimiter validation and formula-injection flags, JSON
  structural summarizer, JSONL head/tail windows, TOML, INI, EML (attachment
  names only), IPYNB (outputs stripped, stdout kept), SQLite introspection in
  strict read-only URI mode, log/text sanitizer with base64-blob elision and
  repeated-line collapse.
- Token-budget engine: head+tail section selection, oversized-section
  windowing, stable anchors (`[page N/M]`, `[sheet i: name]`, `[slide n/m]`)
  and exact re-fetch hints.
- Adversarial hardening: zip entry-count / aggregate-size / ratio caps,
  declared-size verification on every member read, traversal & drive-letter
  & symlink & NUL-name rejection, CRC verification, DTD stripping +
  undefined-entity neutralization, depth heuristics, device/fifo refusal,
  input size ceiling, encoding fallback chain, encrypted-PDF refusal.
- Optional accelerators (pypdf, PyMuPDF) used automatically when installed;
  `DOCSQUEEZE_ENGINE=builtin` forces the stdlib path.
- opencode integration: skill package plus plugin that transparently rewrites
  document reads to compact sidecars and exposes a `docsqueeze` tool.
- 55-test suite including adversarial security fixtures; benchmark tool;
  skill sync tool.
