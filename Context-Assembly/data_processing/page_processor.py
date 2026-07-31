"""
page_processor.py — Xử lý một trang PDF hoàn chỉnh.

Orchestrate toàn bộ quy trình cho 1 trang:
  1. Segment blocks (layout_detector)
  2. CPU blocks: làm sạch text + post-process bảng (text_extractor)
  3. Gửi OCR blocks vào ocr_worker (Ollama Qwen2-VL)
  4. Reassemble theo block_id → markdown đúng thứ tự
"""

from __future__ import annotations

import logging

import fitz

from .layout_detector import segment_page
from .models import BlockType, DocumentBlock, PageResult
from .ocr_worker import process_ocr_blocks
from .text_extractor import process_cpu_blocks

log = logging.getLogger(__name__)


def process_page(
    page: fitz.Page,
    page_num: int,
    doc_name: str,
    layout: str,
    skip_ocr: bool = False,
) -> PageResult:
    """
    Xử lý hoàn chỉnh một trang PDF.

    Args:
        page:      fitz.Page object.
        page_num:  Số trang (1-indexed).
        doc_name:  Tên tài liệu (dùng trong log).
        layout:    "1-column" hoặc "2-column".
        skip_ocr:  Nếu True, bỏ qua Ollama OCR (dùng khi dry-run hoặc offline).

    Returns:
        PageResult với markdown đã ghép đúng thứ tự.
    """
    log.info("[%s] Xử lý trang %d (layout: %s)...", doc_name, page_num, layout)

    # ── 1. Phân đoạn và sắp xếp blocks ──────────────────────────────────────
    blocks: list[DocumentBlock] = segment_page(page, page_num, layout)

    if not blocks:
        log.debug("[%s] Trang %d không có block nào.", doc_name, page_num)
        return PageResult(page_num=page_num, doc_name=doc_name, layout=layout, blocks=[])

    # ── 2. CPU blocks: làm sạch text và post-process bảng ─────────────────────
    blocks = process_cpu_blocks(blocks)

    # ── 3. Ghi ảnh ra đĩa & Gửi IMAGE/MATH blocks sang Ollama OCR ──────────────
    ocr_count = sum(1 for b in blocks if b.needs_ocr)
    if ocr_count > 0:
        from .config import IMAGE_DIR
        # Lưu các ảnh cần OCR ra thư mục output/images/ và set image_rel_path
        for b in blocks:
            if b.needs_ocr and b.crop_bytes:
                clean_doc_name = doc_name.replace('.pdf', '')
                img_filename   = f"{clean_doc_name}_p{page_num}_b{b.block_id}_{b.block_type.name.lower()}.png"
                img_path       = IMAGE_DIR / img_filename
                img_path.write_bytes(b.crop_bytes)
                b.image_rel_path = f"images/{img_filename}"

    if ocr_count > 0 and not skip_ocr:
        log.info("[%s] Trang %d: gửi %d block(s) sang Ollama OCR...", doc_name, page_num, ocr_count)
        blocks = process_ocr_blocks(blocks)
    elif skip_ocr and ocr_count > 0:
        log.info("[%s] Trang %d: bỏ qua OCR (skip_ocr=True), dùng placeholder.", doc_name, page_num)
        for b in blocks:
            if b.needs_ocr:
                if b.block_type == BlockType.MATH:
                    b.markdown_result = f"$[Formula block #{b.block_id}]$"
                else:
                    if b.image_rel_path:
                        b.markdown_result = f"![Image p{b.page_num} #{b.block_id}]({b.image_rel_path})"
                    else:
                        b.markdown_result = f"> [Image block #{b.block_id}]"
                b.is_done = True

    # ── 4. Đảm bảo tất cả blocks đều có kết quả ─────────────────────────────
    for b in blocks:
        if not b.is_done:
            b.markdown_result = b.raw_content or ""
            b.is_done = True

    result = PageResult(
        page_num=page_num,
        doc_name=doc_name,
        layout=layout,
        blocks=blocks,
    )

    # Log thống kê thứ tự
    log.debug(
        "[%s] Trang %d → %d blocks: [%s]",
        doc_name,
        page_num,
        len(blocks),
        ", ".join(f"#{b.block_id}:{b.block_type.value}" for b in blocks),
    )

    return result
