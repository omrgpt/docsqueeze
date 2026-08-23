"""docsqueeze benchmark.

Generates synthetic but representative documents entirely locally, then
measures how many tokens each ingestion strategy would cost:

  strategy A  raw file read as base64 into context
  strategy B  native agent Read on PDF (page images) - approx 1500 tok/page
  strategy C  docsqueeze --full   (all text, no truncation)
  strategy D  docsqueeze default budget (24k tokens)

Usage:  python tools/benchmark.py [--pages N] [--rows N]
"""

from __future__ import annotations

import argparse
import io
import json
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


def make_pdf(pages: int, words_per_page: int = 220) -> bytes:
    objects: dict[int, bytes] = {}
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode()
    objects[900] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    for i in range(pages):
        text = LOREM * (words_per_page // len(LOREM.split()) + 1)
        text = " ".join(text.split()[:words_per_page])
        safe = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = f"BT /F1 11 Tf 60 740 Td ({safe}) Tj ET".encode("latin-1")
        comp = zlib.compress(stream)
        pid, cid = 3 + i, 1000 + i
        objects[pid] = (
            f"<< /Type /Page /Parent 2 0 R /Contents {cid} 0 R "
            f"/Resources << /Font << /F1 900 0 R >> >> >>"
        ).encode()
        objects[cid] = (
            b"<< /Length " + str(len(comp)).encode() + b" /Filter /FlateDecode >>\nstream\n"
            + comp + b"\nendstream"
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
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        zf.writestr("word/document.xml", doc)
    return buf.getvalue()


def make_xlsx(rows: int, cols: int = 8) -> bytes:
    shared = ["Alpha", "Beta", "Gamma", "Delta"]
    row_xml = []
    epoch = date(1899, 12, 30)
    for r in range(rows):
        cells = []
        for c in range(cols):
            ref = f"{chr(65 + c)}{r + 1}"
            v = shared[(r + c) % 4] if (r + c) % 7 == 0 else str((r * cols + c) % 9973)
            t_attr = ' t="s"' if (r + c) % 7 == 0 else ""
            idx = shared.index(v) if t_attr else ""
            inner = idx if t_attr else v
            cells.append(f'<c r="{ref}"{t_attr}><v>{inner}</v></c>')
        row_xml.append(f'<row r="{r + 1}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(row_xml)}</sheetData></worksheet>"
    )
    wb = (
        '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    ct = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    )
    sst = (
        '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
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


def measure(name: str, data: bytes, fname: str, tmp: Path, *, pdf_pages: int | None) -> dict[str, object]:
    p = tmp / fname
    p.write_bytes(data)
    started = time.perf_counter()
    sections, meta = extract_document(p)
    header = [f"[benchmark] file={fname}"]
    full_text, full_meta = build_output(header, sections, budget_tokens=10_000_000, full=True)
    elapsed_full = time.perf_counter() - started

    budgeted_text, budgeted_meta = build_output(header, sections, budget_tokens=24000, full=False)

    base64_tokens = estimate_tokens(f"data:{fname};base64," + __import__("base64").b64encode(data).decode())
    native_vision_tokens = int((pdf_pages or 0) * 1500)

    return {
        "file": name,
        "raw_bytes": len(data),
        "raw_base64_tokens": base64_tokens,
        "native_read_tokens": native_vision_tokens,
        "dsq_full_tokens": full_meta["est_tokens_out"],
        "dsq_budget_tokens": budgeted_meta["est_tokens_out"],
        "dsq_full_chars": len(full_text),
        "extract_seconds": round(elapsed_full, 3),
        "strategy": budgeted_meta["strategy"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-pages", type=int, default=30)
    ap.add_argument("--docx-paras", type=int, default=400)
    ap.add_argument("--xlsx-rows", type=int, default=5000)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="dsq-bench-") as td:
        tmp = Path(td)
        results = [
            measure(
                f"PDF ({args.pdf_pages} pages)",
                make_pdf(args.pdf_pages),
                "bench.pdf",
                tmp,
                pdf_pages=args.pdf_pages,
            ),
            measure(
                f"DOCX ({args.docx_paras} paragraphs)",
                make_docx(args.docx_paras),
                "bench.docx",
                tmp,
                pdf_pages=None,
            ),
            measure(
                f"XLSX ({args.xlsx_rows:,} rows x 8)",
                make_xlsx(args.xlsx_rows),
                "bench.xlsx",
                tmp,
                pdf_pages=None,
            ),
        ]

    print()
    print(f"{'document':<28}{'raw size':>10}{'b64 tokens':>13}{'native Read':>13}{'dsq FULL':>12}{'dsq BUDGET':>12}{'saved':>8}{'vs':>10}")
    print("-" * 103)
    for r in results:
        if r["native_read_tokens"] > 0:
            baseline = r["native_read_tokens"]
            label = "Read"
        else:
            baseline = r["raw_base64_tokens"]
            label = "b64"
        saved = 100 * (baseline - r["dsq_full_tokens"]) / baseline if baseline else 0.0
        print(
            f"{r['file']:<28}{human_size(r['raw_bytes']):>10}"
            f"{r['raw_base64_tokens']:>13,}{r['native_read_tokens']:>13,}"
            f"{r['dsq_full_tokens']:>12,}{r['dsq_budget_tokens']:>12,}{saved:>7.1f}%{label:>10}"
        )
    print("-" * 103)
    print("notes: 'native Read' models per-PDF-page image cost (~1,500 tokens/page);")
    print("       dsq BUDGET is capped by the 24,000-token default budget with")
    print("       head+tail elision and exact fetch hints for elided ranges.")
    print()
    print(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
