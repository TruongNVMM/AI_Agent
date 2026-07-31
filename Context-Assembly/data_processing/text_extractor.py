"""
text_extractor.py — Xử lý CPU cho TEXT và TABLE blocks.

Module này chịu trách nhiệm xử lý các blocks không cần GPU:
  - TEXT blocks: làm sạch, chuẩn hoá khoảng trắng, giữ nguyên nội dung
  - TABLE blocks: đã được layout_detector render sẵn thành Markdown;
    module này thực hiện post-processing thêm nếu cần.

Không gọi Ollama. Toàn bộ chạy trên CPU, đồng bộ, cực nhanh.
"""

from __future__ import annotations

import logging
import re

from .models import BlockType, DocumentBlock

log = logging.getLogger(__name__)

# ─── Text cleaning helpers ────────────────────────────────────────────────────

# Ký tự gạch nối cuối dòng thường xuất hiện khi PDF wrap text: "auto-\nregressive"
_HYPHEN_WRAP_RE = re.compile(r"(\w+)-\n(\w+)")

# Nhiều dòng trắng liên tiếp → thu gọn thành 1
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

# Khoảng trắng đầu/cuối mỗi dòng
_LINE_TRAILING_RE = re.compile(r"[ \t]+$", re.MULTILINE)


def clean_text(text: str) -> str:
    """
    Làm sạch đoạn text thuần từ PDF.

    Các bước:
      1. Sửa hyphenation xuống dòng: "auto-\\nregressive" → "autoregressive"
      2. Chuẩn hóa newline: nhiều dòng trắng → 1 dòng trắng
      3. Xoá khoảng trắng thừa cuối dòng
      4. Strip đầu/cuối đoạn
    """
    if not text:
        return ""

    # Sửa hyphenation cuối dòng
    text = _HYPHEN_WRAP_RE.sub(r"\1\2", text)

    # Xoá khoảng trắng cuối dòng
    text = _LINE_TRAILING_RE.sub("", text)

    # Thu gọn nhiều dòng trắng
    text = _MULTI_BLANK_RE.sub("\n\n", text)

    return text.strip()


def clean_table_markdown(table_md: str) -> str:
    """
    Post-process bảng Markdown đã được render bởi layout_detector.

    Kiểm tra và đảm bảo:
      - Đầy đủ dòng header separator (| --- | --- |)
      - Không có ô trống toàn bộ (thay bằng khoảng trắng)
      - Bảng không quá ngắn (ít hơn 2 dòng → bỏ qua, trả về chuỗi rỗng)
    """
    if not table_md:
        return ""

    lines = [l.strip() for l in table_md.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        log.debug("Bảng quá ngắn, bỏ qua.")
        return ""

    # Đảm bảo dòng 2 là separator (| --- |)
    if not re.match(r"^\|[\s\-|]+\|$", lines[1]):
        # Thêm separator tự động nếu thiếu
        col_count = lines[0].count("|") - 1
        separator = "| " + " | ".join(["---"] * col_count) + " |"
        lines.insert(1, separator)

    return "\n".join(lines)


# ─── Main processor ───────────────────────────────────────────────────────────

def process_text_block(block: DocumentBlock) -> DocumentBlock:
    """
    Xử lý một TEXT block: làm sạch và set markdown_result.

    Args:
        block: DocumentBlock với block_type == TEXT.

    Returns:
        Cùng block, với markdown_result và is_done đã được set.
    """
    if block.block_type != BlockType.TEXT:
        log.warning(
            "process_text_block nhận block không phải TEXT: %s (block #%d)",
            block.block_type, block.block_id,
        )
        return block

    block.markdown_result = clean_text(block.raw_content)
    block.is_done = True
    return block


def process_table_block(block: DocumentBlock) -> DocumentBlock:
    """
    Xử lý một TABLE block: post-process Markdown table và set markdown_result.

    layout_detector đã render sẵn bảng thành chuỗi Markdown.
    Hàm này chỉ làm sạch thêm và gán kết quả.

    Args:
        block: DocumentBlock với block_type == TABLE.

    Returns:
        Cùng block, với markdown_result và is_done đã được set.
    """
    if block.block_type != BlockType.TABLE:
        log.warning(
            "process_table_block nhận block không phải TABLE: %s (block #%d)",
            block.block_type, block.block_id,
        )
        return block

    cleaned = clean_table_markdown(block.raw_content)
    block.markdown_result = cleaned if cleaned else block.raw_content
    block.is_done = True
    return block


def process_cpu_blocks(blocks: list[DocumentBlock]) -> list[DocumentBlock]:
    """
    Xử lý tất cả TEXT và TABLE blocks trong danh sách trên CPU.

    IMAGE và MATH blocks được bỏ qua (xử lý bởi ocr_worker).
    Thứ tự danh sách KHÔNG thay đổi.

    Args:
        blocks: Danh sách DocumentBlock đã có block_id bất biến.

    Returns:
        Cùng danh sách blocks, TEXT/TABLE đã có markdown_result.
    """
    text_count  = 0
    table_count = 0

    for block in blocks:
        if block.is_done:
            continue

        if block.block_type == BlockType.TEXT:
            process_text_block(block)
            text_count += 1

        elif block.block_type == BlockType.TABLE:
            process_table_block(block)
            table_count += 1

        # IMAGE/MATH: bỏ qua, ocr_worker sẽ xử lý

    if text_count + table_count > 0:
        log.debug(
            "CPU processing done: %d text + %d table blocks.",
            text_count, table_count,
        )

    return blocks
