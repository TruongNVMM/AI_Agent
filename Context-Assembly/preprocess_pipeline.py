from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_PATH = ROOT / "processed_documents.jsonl"

HEADER_ZONE_PT = 50
FOOTER_ZONE_PT = 50
TWO_COLUMN_GUTTER_RATIO = 0.14
TWO_COLUMN_MIN_BLOCKS = 6


@dataclass
class CleanedPage:
    doc_name: str
    doc_group: str
    page_number: int
    language: str
    layout: str
    section_path: str
    is_references: bool
    has_math: bool
    has_table: bool
    text: str
    tables_md: list[str] = field(default_factory=list)


def classify_layout(doc: fitz.Document) -> str:
    sample_pages = sorted({0, min(1, len(doc) - 1), min(2, len(doc) - 1)})
    two_column_votes = 0
    for page_index in sample_pages:
        page = doc[page_index]
        width = page.rect.width
        x_mid = width / 2.0
        blocks = [b for b in page.get_text("blocks") if b[4].strip()]
        left = [b for b in blocks if b[2] <= x_mid + 30]
        right = [b for b in blocks if b[0] >= x_mid - 30]
        if len(left) >= 2 and len(right) >= 2:
            two_column_votes += 1
    return "2-column" if two_column_votes >= 2 else "1-column"


def repair_hyphenation(text: str) -> str:
    text = re.sub(r"(\w+)-\s*\n\s*([a-z])", r"\1\2", text)
    text = re.sub(r"([a-z,;])\n([a-z])", r"\1 \2", text)
    return text


def detect_language_from_text(text: str) -> str:
    vi_markers = len(re.findall(r"[àáạảãâầấậẩẫăằắặẳẵđèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹ]", text.lower()))
    latin_words = len(re.findall(r"\b[a-zA-Z]{3,}\b", text))
    if vi_markers > 20 and vi_markers > latin_words // 2:
        return "vi"
    if vi_markers > 0 and latin_words > 0:
        return "mixed"
    return "en"


def is_header_or_footer(block: tuple[Any, ...], page_height: float) -> bool:
    y0, y1 = block[1], block[3]
    return y1 < HEADER_ZONE_PT or y0 > (page_height - FOOTER_ZONE_PT)


def extract_single_column_page(page: fitz.Page) -> tuple[str, list[str]]:
    blocks = sorted(page.get_text("blocks"), key=lambda b: (b[1], b[0]))
    text_parts: list[str] = []
    for b in blocks:
        if b[6] != 0:
            continue
        text = b[4].strip()
        if text and not is_header_or_footer(b, page.rect.height):
            text_parts.append(normalize_block_text(text))
    return join_paragraphs(text_parts), []


def normalize_block_text(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return text.strip()
    merged: list[str] = []
    buffer = lines[0]
    for line in lines[1:]:
        if buffer.endswith("-"):
            buffer = buffer[:-1] + line.lstrip()
        elif len(buffer.split()) < 10 and not buffer.endswith((".", ":", ";", "?", "!")):
            buffer = buffer + " " + line.lstrip()
        else:
            merged.append(buffer)
            buffer = line
    merged.append(buffer)
    return "\n".join(merged)


def join_paragraphs(parts: list[str]) -> str:
    cleaned = [p.strip() for p in parts if p.strip()]
    if not cleaned:
        return ""
    return "\n\n".join(cleaned)


def extract_two_column_page(page: fitz.Page) -> tuple[str, list[str]]:
    width = page.rect.width
    x_mid = width / 2.0
    blocks = page.get_text("blocks")
    text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip() and not is_header_or_footer(b, page.rect.height)]

    gutter = width * TWO_COLUMN_GUTTER_RATIO
    left_col = sorted([b for b in text_blocks if b[2] <= x_mid - gutter], key=lambda b: (b[1], b[0]))
    right_col = sorted([b for b in text_blocks if b[0] >= x_mid + gutter], key=lambda b: (b[1], b[0]))

    if len(left_col) < TWO_COLUMN_MIN_BLOCKS // 2 or len(right_col) < TWO_COLUMN_MIN_BLOCKS // 2:
        return extract_single_column_page(page)

    left_text = [normalize_block_text(b[4].strip()) for b in left_col if b[4].strip()]
    right_text = [normalize_block_text(b[4].strip()) for b in right_col if b[4].strip()]
    all_text = join_paragraphs(left_text + right_text)
    return all_text, []


def extract_tables_as_markdown(page: fitz.Page) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        tab_finder = page.find_tables()
    except Exception:
        return results

    for table in getattr(tab_finder, "tables", []):
        try:
            data = table.extract()
        except Exception:
            continue
        if not data:
            continue
        header = data[0]
        md_rows = ["| " + " | ".join(str(c or "") for c in header) + " |"]
        md_rows.append("| " + " | ".join(["---"] * len(header)) + " |")
        for row in data[1:]:
            md_rows.append("| " + " | ".join(str(c or "") for c in row) + " |")
        results.append({"bbox": table.bbox, "markdown": "\n".join(md_rows)})
    return results


def find_repeated_strings(pages_raw: list[str], min_pages: int = 4) -> set[str]:
    counter: Counter[str] = Counter()
    for page_text in pages_raw:
        lines = [line.strip() for line in page_text.strip().split("\n") if line.strip()]
        for candidate in lines[:2] + lines[-2:]:
            if candidate and len(candidate) > 3 and len(candidate.split()) <= 8:
                counter[candidate] += 1
    return {text for text, count in counter.items() if count >= min_pages}


REFERENCE_HEADERS = [
    r"^\s*(References|REFERENCES)\s*$",
    r"^\s*(Bibliography|BIBLIOGRAPHY)\s*$",
    r"^\s*TÀI LIỆU THAM KHẢO\s*$",
]


APPENDIX_HEADERS = [r"^\s*(Appendix|APPENDIX)\b", r"^\s*A\s+Additional"]


def find_references_start(pages_text: list[str]) -> int | None:
    for i in range(len(pages_text) - 1, -1, -1):
        for pattern in REFERENCE_HEADERS:
            if re.search(pattern, pages_text[i], re.MULTILINE):
                return i
    return None


def find_appendix_start(pages_text: list[str]) -> int | None:
    for i, text in enumerate(pages_text):
        for pattern in APPENDIX_HEADERS:
            if re.search(pattern, text, re.MULTILINE):
                return i
    return None


def build_section_map(doc: fitz.Document) -> dict[int, str]:
    toc = doc.get_toc()
    section_map: dict[int, str] = {}
    stack: list[tuple[int, str]] = []
    for level, title, page in toc:
        stack = [(l, t) for l, t in stack if l < level]
        stack.append((level, title))
        section_map[page] = " > ".join(t for _, t in stack)

    current = ""
    result: dict[int, str] = {}
    for pg in range(1, len(doc) + 1):
        if pg in section_map:
            current = section_map[pg]
        result[pg] = current
    return result


def guess_group(layout: str, page_count: int, toc_count: int) -> str:
    if layout == "2-column":
        return "A"
    if layout == "1-column" and page_count > 80 and toc_count > 50:
        return "C"
    return "B"


def has_math(text: str) -> bool:
    return bool(re.search(r"[∑∂∇√≈≠≤≥±×÷∫]|\\[a-zA-Z]+", text))


def is_page_number_only(text: str) -> bool:
    return bool(re.fullmatch(r"\s*\d{1,3}\s*", text))


def extract_doc(pdf_path: Path) -> list[CleanedPage]:
    doc = fitz.open(pdf_path)
    layout = classify_layout(doc)
    toc_count = len(doc.get_toc())
    doc_group = guess_group(layout, len(doc), toc_count)
    section_map = build_section_map(doc)

    raw_pages: list[str] = []
    page_tables: dict[int, list[str]] = defaultdict(list)
    page_texts: list[str] = []

    for page_index in range(len(doc)):
        page = doc[page_index]
        if layout == "2-column":
            text, tables = extract_two_column_page(page)
        else:
            text, tables = extract_single_column_page(page)

        tables_md = extract_tables_as_markdown(page)
        text = repair_hyphenation(text)
        if page_index + 1 in section_map and section_map[page_index + 1].lower().startswith("appendix"):
            text = text
        raw_pages.append(text)
        page_texts.append(text)
        for t in tables_md:
            page_tables[page_index + 1].append(t["markdown"])

    repeated_strings = find_repeated_strings(page_texts)
    ref_start = find_references_start(page_texts)
    appendix_start = find_appendix_start(page_texts)

    cleaned_pages: list[CleanedPage] = []
    for page_index, raw in enumerate(page_texts, start=1):
        text = raw
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        filtered_lines = []
        for line in lines:
            if line in repeated_strings:
                continue
            if is_page_number_only(line):
                continue
            filtered_lines.append(line)
        text = join_paragraphs(filtered_lines).strip()

        is_ref = ref_start is not None and page_index > ref_start + 1
        if appendix_start is not None and page_index > appendix_start + 1:
            section_path = f"Appendix > {section_map.get(page_index, '').strip()}".strip(" >")
        else:
            section_path = section_map.get(page_index, "")

        if ref_start is not None and page_index >= ref_start + 1:
            is_ref = True

        cleaned_pages.append(
            CleanedPage(
                doc_name=pdf_path.name,
                doc_group=doc_group,
                page_number=page_index,
                language=detect_language_from_text(text),
                layout=layout,
                section_path=section_path,
                is_references=is_ref,
                has_math=has_math(text),
                has_table=bool(page_tables.get(page_index)),
                text=text,
                tables_md=page_tables.get(page_index, []),
            )
        )

    return cleaned_pages


def validate_processed_page(page: CleanedPage) -> list[str]:
    issues: list[str] = []
    short_lines = [l for l in page.text.split("\n") if 0 < len(l.split()) < 3]
    if page.layout == "2-column" and page.text and len(short_lines) > max(3, page.text.count("\n")) * 0.6:
        issues.append("Possible column-mixing: too many short fragments")
    if re.search(r"^\d{1,3}$", page.text.strip()[:10], re.MULTILINE):
        issues.append("Page number may not be filtered")
    if len(page.text.strip()) < 50:
        issues.append("Page text too short - possible extraction failure")
    return issues


def iter_pdf_files() -> list[Path]:
    return sorted(DATA_DIR.glob("*.pdf"))


def main() -> None:
    pdf_files = iter_pdf_files()
    if not pdf_files:
        raise SystemExit(f"No PDF files found in {DATA_DIR}")

    results: list[dict[str, Any]] = []
    stats: dict[str, Any] = {"documents": 0, "pages": 0, "issues": []}

    for pdf_path in pdf_files:
        cleaned_pages = extract_doc(pdf_path)
        stats["documents"] += 1
        stats["pages"] += len(cleaned_pages)
        for page in cleaned_pages:
            issues = validate_processed_page(page)
            if issues:
                stats["issues"].append(
                    {
                        "doc_name": page.doc_name,
                        "page_number": page.page_number,
                        "issues": issues,
                    }
                )
            results.append(asdict(page))

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for item in results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(json.dumps({"output": str(OUTPUT_PATH), **stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
