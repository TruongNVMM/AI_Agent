"""
text_extractor.py — Xử lý CPU cho TEXT và TABLE blocks.

Cải tiến so với phiên bản cũ:
  - Thêm apply_heading_prefix(): dùng block.heading_level để output #, ##, ###.
  - Inline math ($...$) đã được layout_detector chèn vào raw_content.
  - Hỗ trợ fallback cho ALGORITHM và FIGURE khi skip_ocr=True.

Không gọi Ollama. Toàn bộ chạy trên CPU, đồng bộ, cực nhanh.
"""

from __future__ import annotations

import logging
import re

from .models import BlockType, DocumentBlock

log = logging.getLogger(__name__)

# ─── Text cleaning helpers ────────────────────────────────────────────────────

_HYPHEN_WRAP_RE  = re.compile(r"(\w+)-\n(\w+)")
_MULTI_BLANK_RE  = re.compile(r"\n{3,}")
_LINE_TRAILING_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_INLINE_MATH_RE  = re.compile(r"\$[^$\n]+\$")


def _split_math_regions(text: str) -> list[tuple[bool, str]]:
    """Tách text thành các đoạn: (is_math, segment)."""
    parts: list[tuple[bool, str]] = []
    last = 0
    for m in _INLINE_MATH_RE.finditer(text):
        start, end = m.start(), m.end()
        if start > last:
            parts.append((False, text[last:start]))
        parts.append((True, text[start:end]))
        last = end
    if last < len(text):
        parts.append((False, text[last:]))
    return parts


def clean_text(text: str) -> str:
    """Làm sạch đoạn text thuần từ PDF, bảo vệ inline math $...$."""
    if not text:
        return ""

    segments = _split_math_regions(text)
    cleaned_parts: list[str] = []

    for is_math, segment in segments:
        if is_math:
            cleaned_parts.append(segment)
        else:
            segment = _HYPHEN_WRAP_RE.sub(r"\1\2", segment)
            segment = _LINE_TRAILING_RE.sub("", segment)
            cleaned_parts.append(segment)

    result = "".join(cleaned_parts)
    result = _MULTI_BLANK_RE.sub("\n\n", result)
    return result.strip()


# ─── Heading prefix ───────────────────────────────────────────────────────────

_HEADING_PREFIX = {1: "# ", 2: "## ", 3: "### "}


def apply_heading_prefix(block: DocumentBlock) -> str:
    """Trả về markdown_result với prefix heading tương ứng."""
    content = block.markdown_result
    level   = block.heading_level
    if not level or level not in _HEADING_PREFIX:
        return content

    prefix = _HEADING_PREFIX[level]
    lines  = content.splitlines()

    result_lines = []
    prefixed = False
    for line in lines:
        if line.strip() and not prefixed:
            result_lines.append(f"{prefix}{line.strip()}")
            prefixed = True
        else:
            result_lines.append(line)

    return "\n".join(result_lines)


# ─── Table helpers ────────────────────────────────────────────────────────────

def clean_table_markdown(table_md: str) -> str:
    """Post-process bảng Markdown đã được render bởi layout_detector."""
    if not table_md:
        return ""

    lines = [l.strip() for l in table_md.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        log.debug("Bảng quá ngắn, bỏ qua.")
        return ""

    if not re.match(r"^\|[\s\-|]+\|$", lines[1]):
        col_count = lines[0].count("|") - 1
        separator = "| " + " | ".join(["---"] * col_count) + " |"
        lines.insert(1, separator)

    return "\n".join(lines)


# ─── Main processors ──────────────────────────────────────────────────────────

def process_text_block(block: DocumentBlock) -> DocumentBlock:
    """Xử lý một TEXT block."""
    if block.block_type != BlockType.TEXT:
        return block

    cleaned = clean_text(block.raw_content)
    block.markdown_result = cleaned
    block.markdown_result = apply_heading_prefix(block)
    block.is_done = True
    return block


def process_table_block(block: DocumentBlock) -> DocumentBlock:
    """Xử lý một TABLE block."""
    if block.block_type != BlockType.TABLE:
        return block

    cleaned = clean_table_markdown(block.raw_content)
    block.markdown_result = cleaned if cleaned else block.raw_content
    block.is_done = True
    return block


def process_cpu_blocks(blocks: list[DocumentBlock]) -> list[DocumentBlock]:
    """Xử lý tất cả TEXT và TABLE blocks trong danh sách trên CPU."""
    text_count  = 0
    table_count = 0

    for block in blocks:
        if block.is_done:
            continue

        if block.block_type == BlockType.TEXT:
            process_text_block(block)
            text_count += 1

        elif block.block_type == BlockType.TABLE and block.ocr_mode == "table_simple":
            process_table_block(block)
            table_count += 1

    if text_count + table_count > 0:
        log.debug(
            "CPU processing done: %d text + %d table blocks.",
            text_count, table_count,
        )

    return blocks
