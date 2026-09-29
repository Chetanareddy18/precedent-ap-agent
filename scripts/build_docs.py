"""Build Word (.docx) and PDF versions of the content in content/*.md.

    pip install python-docx docx2pdf
    python scripts/build_docs.py          # -> deliverables/*.docx (+ .pdf if MS Word is installed)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deliverables"
ACCENT = RGBColor(0x1F, 0x4E, 0x79)
INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|\*[^*\s][^*]*\*)")


def _hyperlink(par, text, url):
    part = par.part
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                          is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    color = OxmlElement("w:color"); color.set(qn("w:val"), "0563C1"); rpr.append(color)
    u = OxmlElement("w:u"); u.set(qn("w:val"), "single"); rpr.append(u)
    run.append(rpr)
    t = OxmlElement("w:t"); t.text = text; t.set(qn("xml:space"), "preserve"); run.append(t)
    link.append(run)
    par._p.append(link)


def add_inline(par, text, bold=False, size=None):
    for chunk in INLINE.split(text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**"):
            r = par.add_run(chunk[2:-2]); r.bold = True
        elif chunk.startswith("`") and chunk.endswith("`"):
            r = par.add_run(chunk[1:-1]); r.font.name = "Consolas"; r.font.size = Pt(9.5)
            r.font.color.rgb = RGBColor(0xA3, 0x1F, 0x34)
        elif chunk.startswith("[") and "](" in chunk:
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", chunk).groups()
            if url.startswith("http"):
                _hyperlink(par, label, url)
                continue
            r = par.add_run(label)
        elif chunk.startswith("*") and chunk.endswith("*") and len(chunk) > 2:
            r = par.add_run(chunk[1:-1]); r.italic = True
        else:
            r = par.add_run(chunk)
        if bold:
            r.bold = True
        if size:
            r.font.size = Pt(size)


def shade(cell_or_par, hex_fill):
    el = cell_or_par._tc if hasattr(cell_or_par, "_tc") else cell_or_par._p
    props = el.get_or_add_tcPr() if hasattr(cell_or_par, "_tc") else el.get_or_add_pPr()
    shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_fill)
    props.append(shd)


def add_table(doc, rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    cells = [r for r in cells if not all(re.fullmatch(r":?-{2,}:?", c) for c in r)]
    ncol = max(len(r) for r in cells)
    t = doc.add_table(rows=len(cells), cols=ncol)
    t.style = "Table Grid"
    for i, r in enumerate(cells):
        for j in range(ncol):
            cell = t.cell(i, j)
            cell.paragraphs[0].text = ""
            add_inline(cell.paragraphs[0], r[j] if j < len(r) else "", bold=(i == 0), size=9.5)
            if i == 0:
                shade(cell, "DCE6F1")
    doc.add_paragraph()


def md_to_docx(md_path: Path, out_path: Path, subtitle: str | None = None):
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(11)
    for s in ("Heading 1", "Heading 2", "Heading 3", "Title"):
        doc.styles[s].font.color.rgb = ACCENT
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Inches(0.9)

    lines = md_path.read_text(encoding="utf-8").splitlines()
    i, first_h1 = 0, True
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i]); i += 1
            p = doc.add_paragraph()
            shade(p, "F2F2F2")
            r = p.add_run("\n".join(code)); r.font.name = "Consolas"; r.font.size = Pt(9)
            i += 1
            continue
        if s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i]); i += 1
            add_table(doc, rows)
            continue
        m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", s)
        if m:
            img = (md_path.parent / m.group(2)).resolve()
            if img.exists():
                doc.add_picture(str(img), width=Inches(6.4))
                cap = doc.add_paragraph(m.group(1)); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                cap.runs[0].italic = True; cap.runs[0].font.size = Pt(9)
            i += 1
            continue
        if s.startswith("# "):
            if first_h1:
                doc.add_heading(s[2:], level=0)
                if subtitle:
                    p = doc.add_paragraph(subtitle); p.runs[0].italic = True
                first_h1 = False
            else:
                doc.add_heading(s[2:], level=1)
        elif s.startswith("## "):
            doc.add_heading(s[3:], level=1)
        elif s.startswith("### "):
            doc.add_heading(s[4:], level=2)
        elif s in ("---", "***"):
            p = doc.add_paragraph("─" * 60); p.runs[0].font.color.rgb = RGBColor(0xBF, 0xBF, 0xBF)
        elif re.match(r"^[-*] ", s):
            add_inline(doc.add_paragraph(style="List Bullet"), s[2:])
        elif re.match(r"^\d+\. ", s):
            add_inline(doc.add_paragraph(style="List Number"), re.sub(r"^\d+\. ", "", s))
        elif s.startswith(">"):
            p = doc.add_paragraph(); add_inline(p, s.lstrip("> ")); p.paragraph_format.left_indent = Inches(0.3)
            for r in p.runs:
                r.italic = True
        elif s:
            add_inline(doc.add_paragraph(), s)
        i += 1
    doc.save(out_path)
    return out_path


def main():
    OUT.mkdir(exist_ok=True)
    jobs = [
        ("project_overview.md", "Precedent_Project_Overview.docx", None),
        ("article.md", "Precedent_Article.docx", None),
        ("talk_script.md", "Precedent_Talk_Script.docx", None),
        ("linkedin_reddit_video.md", "Precedent_LinkedIn_Reddit_Video.docx", None),
    ]
    built = [md_to_docx(ROOT / "content" / src, OUT / dst, sub) for src, dst, sub in jobs]
    for b in built:
        print("wrote", b)
    try:
        from docx2pdf import convert
        for b in built[:3]:
            convert(str(b), str(b.with_suffix(".pdf")))
            print("wrote", b.with_suffix(".pdf"))
    except Exception as exc:  # Word not installed
        print("PDF export skipped:", exc)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
