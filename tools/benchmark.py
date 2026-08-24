"""docsqueeze benchmark - measures real token costs of ingestion strategies.

Strategies compared per document:
  b64      raw file base64-dumped into context (worst case some agents do)
  Read     native agent PDF read: one page image each (~1,500 tokens/page)
  dsq-full docsqueeze --full (every extracted character, no truncation)
  dsq-24k  docsqueeze at the default 24,000-token budget

Everything is generated or read locally; nothing is downloaded.

Usage:
    python tools/benchmark.py                        # synthetic suite
    python tools/benchmark.py --pdf-pages 50         # bigger PDF
    python tools/benchmark.py --real "C:\\path\\book.pdf"
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import tempfile
import time
import zipfile
import zlib
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from docsqueeze.core import build_output, estimate_tokens, extract_document, human_size  # type: ignore


LOREM = (
    "The quarterly analysis demonstrates measurable improvement across all "
    "operational metrics. Revenue increased by twelve percent while customer "
    "acquisition costs declined. Regional teams exceeded their targets in "
    "every market segment during the review period. "
)

NATIVE_PAGE_TOKENS = 1500


def make_pdf(pages: int, words_per_page: int = 220) -> bytes:
    objects: dict[int, bytes] = {}
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode()
    objects[900] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    words = LOREM.split()
    for i in range(pages):
        text = " ".join(words[(i * 7) % len(words):] + words[: (i * 7) % len(words)])
        text = " ".join((text + " " + LOREM).split()[:words_per_page])
        safe = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = f"BT /F1 11 Tf 60 740 Td ({safe}) Tj ET".encode("latin-1")
        comp = zlib.compress(stream)
        pid, cid = 3 + i, 1000 + i
        objects[pid] = (
            f"<< /Type /Page /Parent 2 0 R /Contents {cid} 0 R "
            f"/Resources << /Font << /F1 900 0 R >> >> >>"
        ).encode()
        objects[cid] = (
            b"<< /Length " + str(len(comp)).encode()
            + b" /Filter /FlateDecode >>\nstream\n" + comp + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for oid in sorted(objects):
        offsets[oid] = len(out)
        out += f"{oid} 0 obj\n".encode() + objects[oid] + b"\nendobj\n"
    xref = len(out)
    max_id = max(objects) + 1
    out += f"xref\n0 {max_id}\n0000000000 65535 f \n".encode()
    for oid in range(1, max_id):
        out += f"{offsets.get(oid, 0):010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {max_id} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_docx(paragraphs: int) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>Paragraph {i}: {LOREM}</w:t></w:r></w:p>"
        for i in range(paragraphs)
    )
    doc = (
        '<?xml version="1.0"?><w:document '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        zf.writestr("word/document.xml", doc)
    return buf.getvalue()


def make_xlsx(rows: int, cols: int = 8) -> bytes:
    shared = ["Alpha", "Beta", "Gamma", "Delta"]
    row_xml = []
    for r in range(rows):
        cells = []
        for c in range(cols):
            ref = f"{chr(65 + c)}{r + 1}"
            if (r + c) % 7 == 0:
                v = shared[(r + c) % 4]
                cells.append(f'<c r="{ref}" t="s"><v>{shared.index(v)}</v></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{(r * cols + c) % 9973}</v></c>')
        row_xml.append(f'<row r="{r + 1}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main"><sheetData>' + "".join(row_xml) + "</sheetData></worksheet>"
    )
    wb = (
        '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships"><sheets>'
        '<sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    ct = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
        'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.'
        'openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sst = (
        '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/'
        'spreadsheetml/2006/main">'
        + "".join(f"<si><t>{s}</t></si>" for s in shared)
        + "</sst>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", ct)
        zf.writestr("xl/workbook.xml", wb)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/sharedStrings.xml", sst)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def measure(path: Path, label: str, *, pdf_pages: int | None) -> dict[str, object]:
    data = path.read_bytes()
    started = time.perf_counter()
    sections, meta = extract_document(path)
    header = [f"[docsqueeze] file={path.name}"]
    full_text, full_meta = build_output(header, sections, budget_tokens=10_000_000, full=True)
    elapsed = time.perf_counter() - started
    budgeted_text, budgeted_meta = build_output(header, sections, budget_tokens=24000, full=False)

    b64_tokens = estimate_tokens(
        "data:application/octet-stream;base64," + base64.b64encode(data).decode()
    )
    native_tokens = int((pdf_pages or 0) * NATIVE_PAGE_TOKENS)
    baseline = native_tokens if native_tokens else b64_tokens
    return {
        "label": label,
        "raw_bytes": len(data),
        "b64_tokens": b64_tokens,
        "native_read_tokens": native_tokens,
        "dsq_full_tokens": full_meta["est_tokens_out"],
        "dsq_24k_tokens": budgeted_meta["est_tokens_out"],
        "strategy_at_24k": budgeted_meta["strategy"],
        "extract_seconds": round(elapsed, 2),
        "engine": meta.get("engine_note", "-"),
        "baseline_kind": "Read" if native_tokens else "b64",
        "saved_pct_vs_baseline_full": round(
            100.0 * (baseline - full_meta["est_tokens_out"]) / max(baseline, 1), 1
        ),
        "saved_pct_vs_baseline_24k": round(
            100.0 * (baseline - budgeted_meta["est_tokens_out"]) / max(baseline, 1), 1
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-pages", type=int, default=30)
    ap.add_argument("--docx-paras", type=int, default=400)
    ap.add_argument("--xlsx-rows", type=int, default=5000)
    ap.add_argument("--real", default=None, help="benchmark a real file on disk")
    ap.add_argument("--accel-pdf", action="store_true",
                    help="add a pypdf-accelerated row for the synthetic PDF "
                         "(default runs are stdlib-builtin since v1.2.0)")
    args = ap.parse_args()

    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="dsq-bench-") as td:
        tmp = Path(td)

        pdf_path = tmp / "bench.pdf"
        pdf_path.write_bytes(make_pdf(args.pdf_pages))
        rows.append(measure(pdf_path, f"synthetic PDF ({args.pdf_pages} pages)", pdf_pages=args.pdf_pages))

        if args.accel_pdf:
            os.environ["DOCSQUEEZE_ENGINE"] = "auto"
            try:
                rows.append(measure(pdf_path, "same PDF, pypdf accelerator", pdf_pages=args.pdf_pages))
            finally:
                os.environ.pop("DOCSQUEEZE_ENGINE", None)

        docx_path = tmp / "bench.docx"
        docx_path.write_bytes(make_docx(args.docx_paras))
        rows.append(measure(docx_path, f"synthetic DOCX ({args.docx_paras} paras)", pdf_pages=None))

        xlsx_path = tmp / "bench.xlsx"
        xlsx_path.write_bytes(make_xlsx(args.xlsx_rows))
        rows.append(measure(xlsx_path, f"synthetic XLSX ({args.xlsx_rows:,} rows x 8)", pdf_pages=None))

        real_label = None
        if args.real:
            rp = Path(args.real)
            if rp.exists():
                ext = rp.suffix.lower()
                pages = None
                if ext == ".pdf":
                    try:
                        import pypdf  # type: ignore

                        pages = len(pypdf.PdfReader(str(rp)).pages)
                    except Exception:
                        pages = None
                real_label = f"real file: {rp.name}" + (f" ({pages} pages)" if pages else "")
                rows.append(measure(rp, real_label, pdf_pages=pages))

    print()
    print(
        f"{'document':<38}{'size':>9}{'b64 tok':>10}{'Read tok':>10}"
        f"{'FULL':>9}{'24k':>8}{'saved*':>8}{'sec':>7}{'engine':>9}"
    )
    print("-" * 108)
    for r in rows:
        print(
            f"{str(r['label'])[:37]:<38}{human_size(r['raw_bytes']):>9}"
            f"{r['b64_tokens']:>10,}{r['native_read_tokens']:>10,}"
            f"{r['dsq_full_tokens']:>9,}{r['dsq_24k_tokens']:>8,}"
            f"{r['saved_pct_vs_baseline_full']:>7.1f}%{r['extract_seconds']:>7.2f}"
            f"{str(r['engine']):>9}"
        )
    print("-" * 108)
    print("* saved vs the relevant worst-case baseline (page-image Read for PDFs,")
    print("  raw-base64 for everything else), using FULL untruncated extraction.")
    print()
    print(json.dumps(rows, indent=1))

    md_path = REPO_ROOT / "docs" / "BENCHMARKS.md"
    if md_path.parent.exists():
        lines = [
            "# Measured benchmarks",
            "",
            f"Machine: local run on {sys.platform}, Python {sys.version.split()[0]},",
            f"docsqueeze {__import__('docsqueeze.core', fromlist=['VERSION']).VERSION}.",
            "Token counts use docsqueeze's calibrated BPE heuristic (chars/4 ASCII, ~1/char CJK).",
            "'Read' models native per-page image ingestion at ~1,500 tokens/page.",
            "",
            "| document | size | b64 tokens | Read tokens | dsq FULL | dsq @24k | saved vs baseline (full) | seconds | engine |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(
                f"| {r['label']} | {human_size(r['raw_bytes'])} | {r['b64_tokens']:,} | "
                f"{r['native_read_tokens']:,} | {r['dsq_full_tokens']:,} | {r['dsq_24k_tokens']:,} | "
                f"{r['saved_pct_vs_baseline_full']}% | {r['extract_seconds']}s | {r['engine']} |"
            )
        lines += [
            "",
            "Reproduce with `python tools/benchmark.py --real <file>`.",
            "",
        ]
        md_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
