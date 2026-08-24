"""docsqueeze adversarial test-suite. Pure stdlib; run:

    python -m unittest discover -s tests -v

Every fixture is generated in a temp dir at runtime; nothing is downloaded.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from docsqueeze import core as eng  # noqa: E402

ENGINE_SKILL_COPY = (
    REPO_ROOT.parent
    / ".agents"
    / "skills"
    / "docsqueeze"
    / "scripts"
    / "docsqueeze.py"
)


# ---------------------------------------------------------------------------
# Fixture builders.
# ---------------------------------------------------------------------------


def build_pdf(pages_text: list[str], *, escapes: str | None = None, compress: bool = True) -> bytes:
    objects: dict[int, bytes] = {}
    n_pages = len(pages_text)
    kids = " ".join(f"{3 + i} 0 R" for i in range(n_pages))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode()
    font_id = 100
    objects[font_id] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
    for i, text in enumerate(pages_text):
        page_id = 3 + i
        content_id = 200 + i
        stream_parts = [b"BT /F1 12 Tf 72 720 Td "]
        if escapes:
            stream_parts.append(f"({escapes}) Tj ".encode("latin-1"))
        else:
            safe = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            stream_parts.append(f"({safe}) Tj ".encode("latin-1"))
        stream_parts.append(b"ET")
        stream_body = b"".join(stream_parts)
        if compress:
            comp = zlib.compress(stream_body)
            content_obj = (
                b"<< /Length " + str(len(comp)).encode() + b" /Filter /FlateDecode >>\nstream\n"
                + comp
                + b"\nendstream"
            )
        else:
            content_obj = (
                b"<< /Length " + str(len(stream_body)).encode() + b" >>\nstream\n"
                + stream_body
                + b"\nendstream"
            )
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        ).encode()
        objects[content_id] = content_obj
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for oid in sorted(objects):
        offsets[oid] = len(out)
        out += f"{oid} 0 obj\n".encode() + objects[oid] + b"\nendobj\n"
    xref_pos = len(out)
    max_id = max(objects) + 1
    out += f"xref\n0 {max_id}\n".encode()
    out += b"0000000000 65535 f \n"
    for oid in range(1, max_id):
        if oid in offsets:
            out += f"{offsets[oid]:010d} 00000 n \n".encode()
        else:
            out += b"0000000000 65535 f \n"
    out += (
        f"trailer\n<< /Size {max_id} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _ct_xml(extra: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{extra}"
        "</Types>"
    )


def build_docx(paragraphs: list[tuple[str, str | None]], table_rows: list[list[str]] | None = None) -> bytes:
    body_parts: list[str] = []
    for text, style in paragraphs:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body_parts.append(
            f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"
        )
    if table_rows:
        trs = "".join(
            "<w:tr>"
            + "".join(f'<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>' for c in row)
            + "</w:tr>"
            for row in table_rows
        )
        body_parts.append(f"<w:tbl>{trs}</w:tbl>")
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body_parts)}<w:sectPr/></w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", _ct_xml('<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'))
        zf.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        zf.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


def build_xlsx(sheets: dict[str, list[list[str]]]) -> bytes:
    sheet_names = list(sheets.keys())
    sheets_xml_parts = "".join(
        f'<sheet name="{name}" sheetId="{i+1}" r:id="rId{i+1}"/>'
        for i, name in enumerate(sheet_names)
    )
    workbook_xml = (
        '<?xml version="1.0"?'
        '><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets_xml_parts}</sheets></workbook>"
    )
    rels_xml = (
        '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>'
            for i in range(len(sheet_names))
        )
        + "</Relationships>"
    )
    shared = ["Alpha", "Beta", "Gamma"]
    shared_xml = (
        '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{s}</t></si>" for s in shared)
        + "</sst>"
    )
    styles_xml = (
        '<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="0"/><fonts count="1"><font/></fonts>'
        '<fills count="1"><fill/></fills><borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="14" xfId="0"/><xf numFmtId="0" xfId="0"/></cellXfs>'
        "</styleSheet>"
    )
    ct_extra = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(len(sheet_names))
    ) + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", _ct_xml(ct_extra))
        zf.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        zf.writestr("xl/sharedStrings.xml", shared_xml)
        zf.writestr("xl/styles.xml", styles_xml)
        for i, (name, rows) in enumerate(sheets.items()):
            row_xml_parts = []
            for r_idx, row in enumerate(rows, start=1):
                cells = []
                for c_idx, val in enumerate(row, start=1):
                    ref = f"{chr(64+c_idx)}{r_idx}"
                    if val.startswith("@DATE@"):
                        try:
                            serial = float(val[6:])
                        except ValueError:
                            serial = 1.0
                        cells.append(f'<c r="{ref}" s="0"><v>{serial}</v></c>')
                    elif val.startswith("@F=") :
                        cells.append(f'<c r="{ref}"><f>{val[3:]}</f><v>42</v></c>')
                    elif val.startswith("@I:"):
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{val[3:]}</t></is></c>')
                    elif val in shared:
                        idx2 = shared.index(val)
                        cells.append(f'<c r="{ref}" t="s"><v>{idx2}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}"><v>{val}</v></c>')
                row_xml_parts.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
            sheet_xml = (
                '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f"<sheetData>{''.join(row_xml_parts)}</sheetData></worksheet>"
            )
            zf.writestr(f"xl/worksheets/sheet{i+1}.xml", sheet_xml)
    return buf.getvalue()


def build_pptx(slides: list[tuple[str, list[str], str | None]]) -> bytes:
    slide_ids = "".join(
        f'<p:sldId id="{256+i}" r:id="rIdS{i+1}"/>' for i in range(len(slides))
    )
    pres_xml = (
        '<?xml version="1.0"?><p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        f"<p:sldIdLst>{slide_ids}</p:sldIdLst></p:presentation>"
    )
    ct_extra = '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
    rels_slide = ""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", _ct_xml(ct_extra))
        zf.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>')
        zf.writestr("ppt/presentation.xml", pres_xml)
        for i, (_title, lines, notes) in enumerate(slides):
            paras = "".join(
                f"<a:p><a:r><a:t>{line}</a:t></a:r></a:p>" for line in lines
            )
            slide_xml = (
                '<?xml version="1.0"?><p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                f"<p:cSld><p:spTree>{paras}</p:spTree></p:cSld></p:sld>"
            )
            zf.writestr(f"ppt/slides/slide{i+1}.xml", slide_xml)
            ct_extra += f'<Override PartName="/ppt/slides/slide{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            rels_entry = ""
            if notes:
                note_paras = "".join(
                    f"<a:p><a:r><a:t>{notes}</a:t></a:r></a:p>"
                )
                notes_xml = (
                    '<?xml version="1.0"?><p:notes xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                    f"<p:cSld><p:spTree>{note_paras}</p:spTree></p:cSld></p:notes>"
                )
                zf.writestr(f"ppt/notesSlides/notesSlide{i+1}.xml", notes_xml)
                rels_entry = (
                    f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    f'<Relationship Id="rIdN" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide{i+1}.xml"/></Relationships>'
                )
                zf.writestr(f"ppt/slides/_rels/slide{i+1}.xml.rels", rels_entry)
        # rewrite content types including slides is already handled above via closure
    return buf.getvalue()


def build_epub(chapters: list[tuple[str, str]]) -> bytes:
    manifest_items = "".join(
        f'<item id="ch{i+1}" href="ch{i+1}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(len(chapters))
    )
    spine_items = "".join(
        f'<itemref idref="ch{i+1}"/>' for i in range(len(chapters))
    )
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
        '<manifest>' + manifest_items + '</manifest>'
        '<spine>' + spine_items + '</spine></package>'
    )
    container = (
        '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        for i, (title, body) in enumerate(chapters):
            zf.writestr(
                f"OEBPS/ch{i+1}.xhtml",
                f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head><body><h1>{title}</h1>{body}</body></html>',
            )
    return buf.getvalue()


def write_fixture(tmp: Path, name: str, data: bytes) -> Path:
    p = tmp / name
    p.write_bytes(data)
    return p


def run_engine(path: Path, *args: str):
    argv = [str(path), *args]
    saved = sys.argv
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    code = 0
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = captured_out, captured_err
    try:
        code = eng.main(argv)
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    return code, captured_out.getvalue(), captured_err.getvalue()


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="dsq-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        if os.environ.get("DOCSQUEEZE_ENGINE"):
            self.addCleanup(os.environ.pop, "DOCSQUEEZE_ENGINE", None)

    def extract(self, data: bytes, name: str, *args: str):
        p = write_fixture(self.tmp, name, data)
        return run_engine(p, *args)

    def assertOk(self, code: int, err: str) -> None:
        self.assertEqual(code, 0, msg=f"engine failed: {err}")


class TestSyncBetweenCopies(Base):
    def test_skill_copy_matches_repo_core(self) -> None:
        if not ENGINE_SKILL_COPY.exists():
            self.skipTest("skill copy not installed")
        repo_hash = __import__("hashlib").sha256(
            (REPO_ROOT / "docsqueeze" / "core.py").read_bytes()
        ).hexdigest()
        skill_hash = __import__("hashlib").sha256(
            ENGINE_SKILL_COPY.read_bytes()
        ).hexdigest()
        self.assertEqual(repo_hash, skill_hash, "engine copies drifted; re-sync")


class TestPdf(Base):
    def setUp(self) -> None:
        super().setUp()
        os.environ["DOCSQUEEZE_ENGINE"] = "builtin"

    def test_basic_multipage_with_anchors(self) -> None:
        pdf = build_pdf(["Hello from page one", "Second page content", "Third and final"])
        code, out, err = self.extract(pdf, "doc.pdf")
        self.assertOk(code, err)
        self.assertIn("engine=builtin", out.splitlines()[0])
        self.assertIn("=== [page 1/3] ===", out)
        self.assertIn("=== [page 3/3] ===", out)
        self.assertIn("Hello from page one", out)
        self.assertIn("Third and final", out)

    def test_accelerator_auto_used_when_present(self) -> None:
        try:
            import pypdf  # type: ignore  # noqa: F401
        except ImportError:
            self.skipTest("pypdf not installed")
        os.environ["DOCSQUEEZE_ENGINE"] = "auto"
        pdf = build_pdf(["auto engine picks pypdf"])
        code, out, err = self.extract(pdf, "auto.pdf")
        self.assertOk(code, err)
        self.assertIn("engine=pypdf", out.splitlines()[0])

    def test_default_engine_is_builtin(self) -> None:
        os.environ.pop("DOCSQUEEZE_ENGINE", None)
        pdf = build_pdf(["default must be the stdlib engine"])
        code, out, err = self.extract(pdf, "defeng.pdf")
        self.assertOk(code, err)
        self.assertIn("engine=builtin", out.splitlines()[0])

    def test_accelerator_respects_page_cap(self) -> None:
        try:
            import pypdf  # type: ignore  # noqa: F401
        except ImportError:
            self.skipTest("pypdf not installed")
        os.environ["DOCSQUEEZE_ENGINE"] = "auto"
        saved_cap = eng.MAX_PDF_PAGES
        eng.MAX_PDF_PAGES = 25
        try:
            pdf = build_pdf([f"cap page {i}" for i in range(120)])
            code, out, err = self.extract(pdf, "capped.pdf", "--json")
            self.assertOk(code, err)
            env = json.loads(out)
            self.assertEqual(env["meta"]["pages"], 25)
            self.assertTrue(env["meta"].get("pages_truncated_to_cap"))
            self.assertEqual(env["meta"]["pdf_total_pages"], 120)
        finally:
            eng.MAX_PDF_PAGES = saved_cap

    def test_escaped_parens_and_backslash(self) -> None:
        pdf = build_pdf(["x"], escapes=r"a\(b\)c \\ end")
        code, out, err = self.extract(pdf, "esc.pdf")
        self.assertOk(code, err)
        self.assertIn("a(b)c \\ end", out)

    def test_hex_string_decoded(self) -> None:
        raw = build_pdf(["placeholder"], compress=False)
        patched = raw.replace(
            b"(placeholder) Tj", b"(x) Tj <48656C6C6F20776F726C64> Tj"
        )
        self.assertIn(b"48656C6C6F", patched)
        p = write_fixture(self.tmp, "hex.pdf", patched)
        code, out, err = run_engine(p)
        self.assertOk(code, err)
        self.assertIn("xHello world", out)

    def test_kerning_inserts_space(self) -> None:
        stream = b"BT /F1 12 Tf 72 720 Td (AB) -250 (CD) Tj ET"
        fonts: dict[str, dict[int, str]] = {}
        got = eng.pdf_extract_text_from_content(stream, fonts, False)
        self.assertEqual(got, "AB CD")

    def test_tounicode_cmap_bfchar_bfrange(self) -> None:
        cmap = b"""
        /CIDInit /ProcSet findresource begin
        12 dict begin begincmap
        1 beginbfchar
        <0041> <00E9>
        endbfchar
        1 beginbfrange
        <0061> <0063> <0430>
        endbfrange
        endcmap CMapName currentdict /CMap defineresource pop end end
        """
        m = eng.parse_tounicode_cmap(cmap)
        self.assertEqual(m[0x41], "\u00e9")
        self.assertEqual(m[0x61], "\u0430")
        self.assertEqual(m[0x63], "\u0432")

    def test_two_byte_decode_via_font_map(self) -> None:
        fonts = {"F1": {0x48: "H", 0x69: "i", "__two_byte__": True}}
        got = eng._decode_pdf_string(bytes([0x00, 0x48, 0x00, 0x69]), fonts, "F1", False)
        self.assertEqual(got, "Hi")

    def test_truncated_pdf_reports_error_not_crash(self) -> None:
        pdf = build_pdf(["hello"])[:120]
        code, out, err = self.extract(pdf, "trunc.pdf")
        self.assertIn(code, (eng.EXIT_PARSE, 0))
        if code != 0:
            self.assertIn("ERROR", err)

    def test_encrypted_stub_refused_in_builtin_mode(self) -> None:
        pdf = build_pdf(["secret"])
        enc = pdf.replace(b"/Root 1 0 R", b"/Encrypt 5 0 R /Root 1 0 R")
        code, out, err = self.extract(enc, "enc.pdf")
        self.assertEqual(code, eng.EXIT_SECURITY)
        self.assertIn("encrypted", err.lower())

    def test_page_selection_flag(self) -> None:
        pdf = build_pdf([f"page {i} unique-token-{i}" for i in range(1, 11)])
        code, out, err = self.extract(pdf, "sel.pdf", "--pages", "2,7-8")
        self.assertOk(code, err)
        self.assertNotIn("unique-token-1 ", out.split("\n")[0])
        self.assertNotIn("[page 1/", out)
        self.assertIn("[page 2/", out)
        self.assertIn("[page 7/", out)
        self.assertIn("[page 8/", out)
        self.assertNotIn("[page 5/", out)

    def test_lying_extension_still_detected_as_pdf(self) -> None:
        pdf = build_pdf(["magic beats extensions"])
        code, out, err = self.extract(pdf, "not_a_pdf.txt")
        self.assertOk(code, err)
        self.assertIn("magic beats extensions", out)
        self.assertIn("format=txt", out.splitlines()[0])


class TestDocx(Base):
    def test_paragraphs_headings_table(self) -> None:
        docx = build_docx(
            [
                ("Report Title", "Title"),
                ("Intro paragraph here", None),
                ("Section A", "Heading1"),
                ("Body of section", "Heading3"),
            ],
            table_rows=[["Name", "Value"], ["alpha", "1"], ["beta", "2"]],
        )
        code, out, err = self.extract(docx, "r.docx")
        self.assertOk(code, err)
        self.assertIn("# Report Title", out)
        self.assertIn("# Section A", out)
        self.assertIn("### Body of section", out)
        self.assertIn("| Name | Value |", out)
        self.assertIn("| alpha | 1 |", out)
        self.assertIn("Intro paragraph here", out)


class TestXlsx(Base):
    def test_shared_inline_dates_formula(self) -> None:
        xlsx = build_xlsx(
            {
                "Data": [
                    ["Alpha", "@I:inline cell", "@DATE@1"],
                    ["Beta", "@F=SUM(A1:A2)", "7"],
                ],
                "Empty": [["only"]],
            }
        )
        code, out, err = self.extract(xlsx, "b.xlsx")
        self.assertOk(code, err)
        self.assertIn("=== [sheet 1: Data] ===", out)
        self.assertIn("=== [sheet 2: Empty] ===", out)
        self.assertIn("inline cell", out)
        from datetime import date, timedelta

        expected_iso = (date(1899, 12, 30) + timedelta(days=1)).isoformat()
        self.assertIn(expected_iso, out)
        self.assertEqual(eng._serial_to_iso(25569, False), "1970-01-01")
        self.assertIn("[=]", out)

    def test_sheet_filter_by_name(self) -> None:
        xlsx = build_xlsx({"Keep": [["k"]], "Drop": [["d"]]})
        code, out, err = self.extract(xlsx, "f.xlsx", "--sheets", "Keep")
        self.assertOk(code, err)
        self.assertIn("[sheet 1: Keep]", out)
        self.assertNotIn("[sheet 2: Drop]", out)


class TestPptx(Base):
    def test_slides_and_notes(self) -> None:
        pptx = build_pptx(
            [
                ("T1", ["Slide one line", "Second line"], "Remember this"),
                ("T2", ["Slide two"], None),
            ]
        )
        code, out, err = self.extract(pptx, "deck.pptx")
        self.assertOk(code, err)
        self.assertIn("=== [slide 1/2] ===", out)
        self.assertIn("Slide one line", out)
        self.assertIn("--- speaker notes ---", out)
        self.assertIn("Remember this", out)
        self.assertIn("=== [slide 2/2] ===", out)
        self.assertIn("Slide two", out)


class TestEpubHtmlRtf(Base):
    def test_epub_spine_order(self) -> None:
        epub = build_epub(
            [("Chapter One", "<p>First chapter body</p>"), ("Chapter Two", "<p>Second</p>")]
        )
        code, out, err = self.extract(epub, "book.epub")
        self.assertOk(code, err)
        self.assertIn("# Chapter One", out)
        pos1 = out.find("# Chapter One")
        pos2 = out.find("# Chapter Two")
        self.assertLess(pos1, pos2)
        self.assertIn("First chapter body", out)

    def test_html_script_stripped_entities_links(self) -> None:
        html = (
            "<html><head><script>alert('x')</script><style>p{{}}</style></head>"
            "<body><h1>Head &amp; Shoulders</h1>"
            '<a href="https://example.com/x">cool link</a>'
            "<img src='a.png' alt='an image'>"
            "<script>var a = '</scr'+'ipt>';</script></body></html>"
        ).replace("{{}}", "")
        code, out, err = self.extract(html.encode(), "p.html")
        self.assertOk(code, err)
        self.assertIn("Head & Shoulders", out)
        self.assertIn("[cool link](https://example.com/x)", out)
        self.assertIn("[image: an image]", out)
        self.assertNotIn("alert(", out)

    def test_rtf_control_words_and_unicode(self) -> None:
        rtf = r"{\rtf1\ansi Hello{\fonttbl{\f0 Times;}}\par World \u9731? end}"
        code, out, err = self.extract(rtf.encode("latin-1"), "d.rtf")
        self.assertOk(code, err)
        self.assertIn("Hello", out)
        self.assertIn("World", out)
        self.assertIn("\u2603", out)
        self.assertNotIn("fonttbl", out)


class TestZipSecurity(Base):
    def test_path_traversal_entry_blocked(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.txt", "boom")
        code, out, err = self.extract(buf.getvalue(), "evil.zip")
        self.assertEqual(code, eng.EXIT_SECURITY)
        self.assertIn("traversal", err.lower())

    def test_absolute_entry_blocked(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/abs.txt", "x")
        code, out, err = self.extract(buf.getvalue(), "abs.zip")
        self.assertEqual(code, eng.EXIT_SECURITY)

    def test_zip_bomb_ratio_blocked(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("zeros.bin", b"\x00" * (40 * 1024 * 1024))
        code, out, err = self.extract(buf.getvalue(), "bomb.zip")
        self.assertEqual(code, eng.EXIT_SECURITY)
        self.assertTrue("ratio" in err.lower() or "bomb" in err.lower())

    def test_symlink_entry_blocked(self) -> None:
        info = zipfile.ZipInfo("link.txt")
        info.external_attr = (0o120777 << 16)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(info, "/etc/passwd")
        code, out, err = self.extract(buf.getvalue(), "sym.zip")
        self.assertEqual(code, eng.EXIT_SECURITY)
        self.assertIn("symlink", err.lower())

    def test_generic_listing_flags_executables(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "fine")
            zf.writestr("dropper.exe", "MZ...")
        code, out, err = self.extract(buf.getvalue(), "mixed.zip")
        self.assertOk(code, err)
        self.assertIn("EXECUTABLE", out)
        self.assertIn("dropper.exe", out)

    def test_crc_corruption_detected_on_read(self) -> None:
        # CRC is verified per-member during budgeted reads (metadata caps run
        # first, so there is no eager full-archive scan). Corrupt a DOCX
        # member's compressed bytes and the read must fail closed.
        good = build_docx([("hello", None)])
        blob = bytearray(good)
        name = b"word/document.xml"
        sig = b"PK\x03\x04"
        i = -1
        data_start = -1
        while True:
            i = blob.find(sig, i + 1)
            if i == -1:
                self.fail("local header for document.xml not found")
            fnlen = int.from_bytes(blob[i + 26 : i + 28], "little")
            extralen = int.from_bytes(blob[i + 28 : i + 30], "little")
            if blob[i + 30 : i + 30 + fnlen] == name:
                data_start = i + 30 + fnlen + extralen
                break
        blob[data_start] = (blob[data_start] + 1) % 256
        code, out, err = self.extract(bytes(blob), "crc.docx")
        self.assertIn(code, (eng.EXIT_SECURITY, eng.EXIT_PARSE))
        if code == eng.EXIT_SECURITY:
            self.assertIn("CRC", err)

    def test_zip_metadata_caps_precede_decompression(self) -> None:
        import time as _t

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("z.bin", "\x00" * (40 * 1024 * 1024))
        p = write_fixture(self.tmp, "fastbomb.zip", buf.getvalue())
        started = _t.perf_counter()
        code, out, err = run_engine(p)
        elapsed = _t.perf_counter() - started
        self.assertEqual(code, eng.EXIT_SECURITY)
        self.assertLess(elapsed, 5.0, f"metadata caps applied late: {elapsed:.2f}s")

    def test_untrusted_data_footer_present(self) -> None:
        sections = [eng.Section("=== [text] ===", "plain body")]
        text, meta = eng.build_output(["[h]"], sections, budget_tokens=10000, full=False)
        self.assertTrue(meta.get("untrusted_notice"))
        self.assertTrue(text.rstrip().endswith(eng.UNTRUSTED_FOOTER))
        self.assertIn("UNTRUSTED DATA", eng.UNTRUSTED_FOOTER)


class TestXmlAttacks(Base):
    def test_billion_laughs_docx_neutralized(self) -> None:
        lol_dtd = (
            '<!DOCTYPE bomb [<!ENTITY a "aaaaaaaaaa">'
            '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
        )
        doc_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + lol_dtd +
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>ok &amp; safe &c;</w:t></w:r></w:p></w:body></w:document>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("[Content_Types].xml", _ct_xml('<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'))
            zf.writestr("word/document.xml", doc_xml)
        code, out, err = self.extract(buf.getvalue(), "lol.docx")
        self.assertOk(code, err)
        self.assertNotIn("a" * 50, out)

    def test_deep_nesting_recursion_guard(self) -> None:
        deep = ("<a>" * 5000) + ("</a>" * 5000)
        code, out, err = self.extract(deep.encode(), "deep.xml")
        self.assertEqual(code, eng.EXIT_SECURITY)
        self.assertIn("nest", err.lower())

    def test_external_entity_reference_neutralized(self) -> None:
        xml = (
            '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            "<root>&xxe;</root>"
        )
        code, out, err = self.extract(xml.encode(), "xxe.xml")
        self.assertIn(code, (eng.EXIT_OK, eng.EXIT_PARSE))
        if code == eng.EXIT_OK:
            self.assertIn("&xxe;", out)
            self.assertNotIn("root:x:0:0", out)

    def test_numeric_entities_preserved_after_hardening(self) -> None:
        xml = '<?xml version="1.0"?><root>caf&#233; cr&#xE8;me &amp; sugar</root>'
        code, out, err = self.extract(xml.encode(), "ents.xml")
        self.assertOk(code, err)
        self.assertIn("caf\u00e9", out)
        self.assertIn("\u00e8", out)
        self.assertIn("&amp; sugar" if "&amp;" in out else "& sugar", out)


class TestDelimitedAndInjection(Base):
    def test_formula_injection_flagged(self) -> None:
        csv_data = "name,comment\nbob,=HYPERLINK(http://evil.com)\nalice,+1+cmd|'/c'\ncarol,@SUM(1,2)\n"
        code, out, err = self.extract(csv_data.encode(), "inj.csv")
        self.assertOk(code, err)
        self.assertIn("[FORMULA?]", out)
        self.assertIn("'=HYPERLINK", out)

    def test_row_caps_apply_with_note(self) -> None:
        rows = ",".join(str(i) for i in range(5000))
        csv_data = "\n".join(str(i) for i in range(8000)) + "\n"
        code, out, err = self.extract(csv_data.encode(), "big.csv")
        self.assertOk(code, err)
        self.assertIn("elided", out)
        self.assertIn("caps", out)


class TestTextFormats(Base):
    def test_json_over_budget_gets_structural_summary(self) -> None:
        big = {"items": [{"id": i, "blob": "x" * 80} for i in range(3000)]}
        code, out, err = self.extract(json.dumps(big).encode(), "big.json", "--max-tokens", "1500")
        self.assertOk(code, err)
        self.assertIn("list of 3,000 items", out)

    def test_jsonl_head_tail(self) -> None:
        recs = "\n".join(json.dumps({"n": i}) for i in range(1000))
        code, out, err = self.extract(recs.encode(), "s.jsonl")
        self.assertOk(code, err)
        self.assertIn("records]", out)
        self.assertIn('{"n": 999}', out)
        self.assertIn("elided", out)

    def test_base64_blob_elided_in_logs(self) -> None:
        blob = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=" * 30
        log = f"INFO start\npayload={blob}\nINFO end\n"
        code, out, err = self.extract(log.encode(), "run.log")
        self.assertOk(code, err)
        self.assertIn("[base64 blob:", out)
        self.assertNotIn("QUJDREVGR0hJ", out)

    def test_repeated_lines_collapsed(self) -> None:
        log = "ERROR disk full\n" * 300 + "done\n"
        code, out, err = self.extract(log.encode(), "rep.log")
        self.assertOk(code, err)
        self.assertIn("identical line repeated", out)

    def test_utf16_bom_decoded(self) -> None:
        txt = "unicode works".encode("utf-16")
        code, out, err = self.extract(txt, "u.txt")
        self.assertOk(code, err)
        self.assertIn("unicode works", out)

    def test_latin1_fallback(self) -> None:
        raw = b"caf\xe9 cr\xe8me"
        code, out, err = self.extract(raw, "l.txt")
        self.assertOk(code, err)
        self.assertIn("caf\xe9", out)

    def test_toml_parsed(self) -> None:
        toml = '[owner]\nname = "Ada"\n[server]\nport = 8080\n'
        code, out, err = self.extract(toml.encode(), "c.toml")
        self.assertOk(code, err)
        self.assertIn("Ada", out)
        self.assertIn("8080", out)

    def test_ini_parsed(self) -> None:
        ini = "[db]\nhost = localhost\nport = 5432\n"
        code, out, err = self.extract(ini.encode(), "app.ini")
        self.assertOk(code, err)
        self.assertIn("localhost", out)


class TestSqliteIpynbEmlImage(Base):
    def test_sqlite_introspection_readonly(self) -> None:
        db_path = self.tmp / "data.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany("INSERT INTO users VALUES (?,?)", [(1, "ann"), (2, "bo")])
        conn.commit()
        conn.close()
        code, out, err = run_engine(db_path)
        self.assertOk(code, err)
        self.assertIn("## table: users (2 rows)", out)
        self.assertIn("id:INTEGER PK", out)
        self.assertIn("ann", out)

    def test_ipynb_outputs_stripped_but_stdout_kept(self) -> None:
        nb = {
            "cells": [
                {
                    "cell_type": "code",
                    "source": ["print('hi')"],
                    "outputs": [
                        {"output_type": "stream", "text": ["hello stdout"]},
                        {
                            "output_type": "display_data",
                            "data": {
                                "image/png": "iVBORw0KGgoAAAANSUhEUgAAAAUAAAAFCAYAAACNbyblAAAAHElEQVQI12P4//8/w38GIAXDIBKE0DHxgljNBAAO9TXL0Y4OHwAAAABJRU5ErkJggg=="
                            },
                        },
                    ],
                },
                {"cell_type": "markdown", "source": ["# Title"]},
            ]
        }
        code, out, err = self.extract(json.dumps(nb).encode(), "nb.ipynb")
        self.assertOk(code, err)
        self.assertIn("=== [notebook] ===", out)
        self.assertIn("print('hi')", out)
        self.assertIn("hello stdout", out)
        self.assertNotIn("iVBORw0KGgoAAAAN", out)
        code2, out2, err2 = self.extract(json.dumps(nb).encode(), "nb2.ipynb", "--stats-only")
        self.assertOk(code2, err2)
        stats = json.loads(out2)
        self.assertEqual(stats["outputs_stripped"], 2)
        self.assertEqual(stats["cells"], 2)

    def test_eml_headers_attachments_body(self) -> None:
        import email.message

        m = email.message.EmailMessage()
        m["From"] = "a@example.com"
        m["To"] = "b@example.com"
        m["Subject"] = "Quarterly numbers"
        m.set_content("Body text here.")
        m.add_attachment(b"BINARYPAYLOAD" * 100, maintype="application", subtype="octet-stream", filename="q4.xlsx")
        raw = bytes(m)
        code, out, err = self.extract(raw, "mail.eml")
        self.assertOk(code, err)
        self.assertIn("Subject: Quarterly numbers", out)
        self.assertIn("Body text here.", out)
        self.assertIn("q4.xlsx", out)
        self.assertNotIn("BINARYPAYLOAD", out)

    def test_png_dims_reported(self) -> None:
        import struct as st

        ihdr = st.pack(">II", 1920, 1080) + b"\x08\x06\x00\x00\x00"
        chunk_len = st.pack(">I", 13)
        crc_placeholder = b"\x00\x00\x00\x00"
        png = b"\x89PNG\r\n\x1a\n" + chunk_len + b"IHDR" + ihdr + crc_placeholder
        code, out, err = self.extract(png, "img.png")
        self.assertOk(code, err)
        self.assertIn("dimensions=1920x1080", out)


class TestBudgetEngine(Base):
    def test_budget_elides_middle_keeps_ends(self) -> None:
        sections = [
            eng.Section(f"=== [page {i}/10] ===", f"content-{i} " + "filler " * 400, f"--pages {i}")
            for i in range(1, 11)
        ]
        header = ["[header]"]
        text, meta = eng.build_output(header, sections, budget_tokens=1500, full=False)
        self.assertEqual(meta["strategy"], "head+tail")
        self.assertIn("elided", text)
        self.assertIn("content-1", text)
        self.assertIn("content-10", text)
        self.assertNotIn("content-5 filler", text)
        self.assertLessEqual(meta["est_tokens_out"], 1500 + 600)

    def test_full_mode_overrides(self) -> None:
        sections = [eng.Section("=== [a] ===", "x " * 50000)]
        text, meta = eng.build_output(["h"], sections, budget_tokens=10, full=True)
        self.assertEqual(meta["strategy"], "full")

    def test_single_giant_section_windowed(self) -> None:
        sections = [eng.Section("=== [text] ===", "word " * 100000)]
        text, meta = eng.build_output(["h"], sections, budget_tokens=800, full=False)
        self.assertIn("characters elided", text)
        self.assertIn(meta["strategy"], ("single-window",))

    def test_token_estimator_reasonable(self) -> None:
        prose = "The quick brown fox jumps over the lazy dog. " * 100
        est = eng.estimate_tokens(prose)
        self.assertGreater(est, 400)
        self.assertLess(est, 1600)
        cjk = "\u4f60\u597d\u4e16\u754c" * 50
        est_cjk = eng.estimate_tokens(cjk)
        self.assertGreater(est_cjk, 150)


class TestInputValidation(Base):
    def test_empty_file_rejected(self) -> None:
        p = write_fixture(self.tmp, "empty.txt", b"")
        code, out, err = run_engine(p)
        self.assertEqual(code, eng.EXIT_IO)

    def test_missing_file_exit_code(self) -> None:
        code, out, err = run_engine(self.tmp / "nope.pdf")
        self.assertEqual(code, eng.EXIT_IO)

    def test_directory_rejected(self) -> None:
        sub = self.tmp / "adir"
        sub.mkdir()
        code, out, err = run_engine(sub)
        self.assertEqual(code, eng.EXIT_USAGE)

    def test_fifo_refused(self) -> None:
        fifo = self.tmp / "pipe"
        try:
            os.mkfifo(fifo)
        except (AttributeError, NotImplementedError, OSError):
            self.skipTest("fifo unsupported on this platform/filesystem")
        code, out, err = run_engine(fifo)
        self.assertEqual(code, eng.EXIT_SECURITY)


class TestLegacyRefusals(Base):
    def test_ole_magic_refused_with_guidance(self) -> None:
        ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
        code, out, err = self.extract(ole, "old.doc")
        self.assertEqual(code, eng.EXIT_UNSUPPORTED)
        self.assertIn("soffice", err)

    def test_gzip_refused(self) -> None:
        import gzip as gz

        gz_bytes = gz.compress(b"data")
        code, out, err = self.extract(gz_bytes, "f.gz")
        self.assertEqual(code, eng.EXIT_UNSUPPORTED)


class TestCliEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="dsq-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_subprocess_json_envelope(self) -> None:
        target = self.tmp / "t.txt"
        target.write_text("hello world", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, r'%s'); import docsqueeze.core as c; sys.exit(c.main())"
             % str(REPO_ROOT),
             str(target), "--json"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        envelope = json.loads(proc.stdout)
        self.assertTrue(envelope["ok"])
        self.assertIn("hello world", envelope["text"])
        self.assertIn("est_tokens_out", envelope["meta"])

    def test_subprocess_stats_only(self) -> None:
        target = self.tmp / "t.md"
        target.write_text("# hi\n" * 50, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, r'%s'); import docsqueeze.core as c; sys.exit(c.main())"
             % str(REPO_ROOT),
             str(target), "--stats-only"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stats = json.loads(proc.stdout)
        self.assertEqual(stats["words"], 100)

    def test_subprocess_security_exit_code(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../up.txt", "x")
        target = self.tmp / "bad.zip"
        target.write_bytes(buf.getvalue())
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, r'%s'); import docsqueeze.core as c; sys.exit(c.main())"
             % str(REPO_ROOT),
             str(target)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, eng.EXIT_SECURITY)


class TestHardeningV11(Base):
    """v1.1.0 hardening: ReDoS probes, memory bounds, positioning, fidelity."""

    def test_banner_sits_between_head_and_tail(self) -> None:
        sections = [
            eng.Section(f"=== [page {i}/6] ===", f"content-{i} " + "filler " * 500, f"--pages {i}")
            for i in range(1, 7)
        ]
        text, meta = eng.build_output(["[h]"], sections, budget_tokens=1200, full=False)
        self.assertEqual(meta["strategy"], "head+tail")
        pos_head = text.find("content-1")
        pos_banner = text.find("[[docsqueeze elided")
        pos_tail = text.find("=== [page 6/6] ===", pos_banner if pos_banner > 0 else 0)
        self.assertGreater(pos_banner, 0, "banner missing")
        self.assertGreater(pos_tail, pos_banner, "tail must come AFTER banner")
        self.assertGreater(pos_banner, pos_head, "banner must come AFTER head")

    def test_cmap_quadratic_probe_completes_fast(self) -> None:
        import time as _t

        crafted = (b"beginbfchar <0041> <0042> endbfchar\n" * 200) + b"beginbfchar " + b"x" * (1_000_000)
        started = _t.perf_counter()
        mapping = eng.parse_tounicode_cmap(crafted)
        elapsed = _t.perf_counter() - started
        self.assertEqual(mapping.get(0x41), "B")
        self.assertLess(elapsed, 5.0, f"CMap parse too slow: {elapsed:.2f}s (quadratic?)")

    def test_doctype_scanner_linear_on_adversarial_xml(self) -> None:
        import time as _t

        payload = b'<?xml version="1.0"?><!DOCTYPE a' * 4000 + b"<root>ok</root>"
        p = write_fixture(self.tmp, "adv.xml", payload)
        started = _t.perf_counter()
        code, out, err = run_engine(p)
        elapsed = _t.perf_counter() - started
        self.assertIn(code, (eng.EXIT_OK, eng.EXIT_PARSE))
        self.assertLess(elapsed, 10.0, f"DTD handling too slow: {elapsed:.2f}s")

    def test_giant_content_types_entry_bounded(self) -> None:
        import time as _t

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", "<Types/>" + "\x00" * (40 * 1024 * 1024))
            zf.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>hi</w:t></w:r></w:p></w:body></w:document>',
            )
        p = write_fixture(self.tmp, "giant.docx", buf.getvalue())
        started = _t.perf_counter()
        code, out, err = run_engine(p)
        elapsed = _t.perf_counter() - started
        self.assertIn(code, (eng.EXIT_OK, eng.EXIT_SECURITY, eng.EXIT_PARSE))
        self.assertLess(elapsed, 15.0, f"giant entry handling too slow: {elapsed:.1f}s")
        if code == eng.EXIT_OK:
            self.assertIn("hi", out)

    def test_csv_minus_formula_variants(self) -> None:
        csv_data = "a,b\n-42,=HYPERLINK(http://x)\n7,-5\n"
        code, out, err = self.extract(csv_data.encode(), "minus.csv")
        self.assertOk(code, err)
        self.assertIn("'=HYPERLINK(http://x)[FORMULA?]", out)
        self.assertIn("-42\t", out)
        self.assertIn("\t-5", out)
        self.assertNotIn("-42[FORMULA?]", out)
        self.assertNotIn("-5[FORMULA?]", out)

    def test_backslash_traversal_entry_blocked(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("..\\evil.txt", "boom")
        code, out, err = self.extract(buf.getvalue(), "bs.zip")
        self.assertEqual(code, eng.EXIT_SECURITY)

    def test_empty_archive_lists_cleanly(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            pass
        code, out, err = self.extract(buf.getvalue(), "empty.zip")
        self.assertOk(code, err)
        self.assertIn("archive contents", out)

    def test_deep_mime_eml_no_crash(self) -> None:
        import email.message
        import email.encoders
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEText("leaf", "plain")
        for _ in range(60):
            outer = MIMEMultipart()
            outer.attach(msg)
            msg = outer
        raw = msg.as_bytes()
        code, out, err = self.extract(raw, "deep.eml")
        self.assertIn(code, (eng.EXIT_OK, eng.EXIT_PARSE))

    def test_jsonl_single_giant_line_bounded(self) -> None:
        big = {"blob": "y" * (3 * 1024 * 1024)}
        code, out, err = self.extract(json.dumps(big).encode(), "giant.jsonl")
        self.assertOk(code, err)
        body_chars = len(out.split("\n", 1)[1]) if "\n" in out else len(out)
        self.assertLess(body_chars, 600_000)

    def test_cjk_single_section_windowing_respects_budget(self) -> None:
        sections = [eng.Section("=== [text] ===", "\u4f60\u597d\u4e16\u754c" * 30000)]
        text, meta = eng.build_output(["h"], sections, budget_tokens=1000, full=False)
        self.assertEqual(meta["strategy"], "single-window")
        self.assertIn("characters elided", text)
        self.assertLessEqual(meta["est_tokens_out"], 1000 + 800)

    def test_form_feed_and_control_chars_sanitized(self) -> None:
        raw = b"a\x0cb\x07c\x1b[31md"
        code, out, err = self.extract(raw, "ctl.txt")
        self.assertOk(code, err)
        self.assertNotIn("\x07", out)
        self.assertNotIn("\x1b", out)

    def test_symlinked_input_file_resolves(self) -> None:
        target = write_fixture(self.tmp, "real.txt", b"symlink ok")
        link = self.tmp / "link.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unsupported here")
        code, out, err = run_engine(link)
        self.assertOk(code, err)
        self.assertIn("symlink ok", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
