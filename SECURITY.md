# SECURITY.md

docsqueeze parses **untrusted, potentially malicious documents**. This file
is the authoritative threat model and control list. The implementation is a
single Python file (`docsqueeze/core.py`) with zero third-party runtime
dependencies — audit it end to end.

## Threat model

An attacker controls the content of any document an agent is asked to read:
email attachments, downloads, repository fixtures. Attacker goals:

1. Exhaust agent memory/disk/CPU (denial of service).
2. Escape the reader into arbitrary file writes or code execution.
3. Smuggle instructions to the model (prompt injection) via hidden content.
4. Exfiltrate data (network callbacks triggered by parsing).

## Controls

### Resource exhaustion
- Input size ceiling: 512 MB default (`DOCSQUEEZE_MAX_INPUT_MB`, hard cap 2 GB).
- Zip entry count cap: 5,000; aggregate uncompressed cap: 512 MB;
  per-entry compression-ratio cap: 300:1 above 1 MB → `SECURITY` exit.
- Every zip member is read with declared-size verification; inflation beyond
  the declared size is rejected.
- PDF object-count cap (500k), page cap (4,096), per-stream inflate cap
  (256 MB), nesting depth caps everywhere (page tree 64, XML heuristic 2,000,
  walkers ≤128).
- JSON/TOML/INI parse caps; JSONL head/tail windows; CSV row caps.
- Repeated-line collapse and base64-blob elision stop log-flooding tricks.

### File-system & execution safety
- **Nothing is ever extracted to disk by the engine.** All parsing happens
  in memory under byte budgets — no TOCTOU, no partial-write attacks.
- Archive entries with absolute paths, drive letters, `..` traversal, NUL
  bytes, over-long names, or symlink mode bits are rejected outright.
- Device/fifo/socket input files are refused (no reading from special files).
- No subprocess is ever spawned; no network call exists anywhere in the
  codebase; no dynamic imports beyond optional stdlib/accelerators.
- Executable-looking entries inside archives are listed but flagged
  `EXECUTABLE - do NOT run`; they are never written or executed.

### XML / OOXML attacks
- XXE/billion-laughs: DTDs (`DOCTYPE`, `ENTITY`) are stripped before
  parsing; remaining unknown entity references are neutralized to literal
  text. stdlib ElementTree additionally refuses external resolution.
- Deep-nesting recursion bombs are caught by a streaming depth pre-scan.

### Content-injection hygiene for agents
- CSV/TSV cells starting with `= + @` are escaped and flagged
  `[FORMULA?]` — spreadsheet formula injection can never execute because
  nothing evaluates formulas; output only annotates them.
- Email attachments are listed (name/type/size), never decoded into context.
- Notebook image/base64 outputs are stripped; giant embedded blobs elided.
- Encrypted PDFs are refused rather than guessed at.

### Encoding robustness
- BOM sniffing (UTF-8/16/32) → strict UTF-8 → cp1252 → latin-1 replacement;
  control characters stripped; invalid sequences never crash the pipeline.

## Trust boundaries of the opencode integration

- The plugin runs the engine as a local subprocess on a path *you* install;
  it passes only the resolved document path and numeric/string flags.
- Sidecar files (`.name.dsq.md`) contain extracted text only. They inherit
  the source directory's permissions. Delete them anytime; they are caches,
  not sources of truth.
- If Python or the engine is missing, reads fall back to native behavior
  silently — the plugin can never make a read fail.

## Reporting

Open a GitHub issue with a minimized reproducer document. Do not attach
live exploit archives to issues; share hashes and a generator script.
