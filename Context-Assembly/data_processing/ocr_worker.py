"""
ocr_worker.py — Worker điều phối OCR cho các blocks IMAGE, FIGURE, MATH, ALGORITHM, TABLE.

Chiến lược chống OOM trên RTX 2080 Ti (11 GB VRAM):
- Semaphore giới hạn số request Ollama đồng thời (OCR_CONCURRENT_REQUESTS=1).
- Tùy theo block.ocr_mode để dispatch prompt phù hợp ("math", "figure", "table_complex", "algorithm", "image").
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

from .config import OCR_CONCURRENT_REQUESTS
from .markdown_utils import markdown_image_for_block
from .models import BlockType, DocumentBlock
from .vision_client import OCRMode, call_qwen2_vl

log = logging.getLogger(__name__)

# Semaphore toàn cục: giới hạn số request Ollama đồng thời
_OLLAMA_SEMAPHORE = threading.Semaphore(OCR_CONCURRENT_REQUESTS)


def _ocr_single_block(block: DocumentBlock) -> DocumentBlock:
    """
    Xử lý OCR cho 1 block với mode thích hợp.
    """
    if not block.needs_ocr or block.crop_bytes is None:
        block.is_done = True
        return block

    # Determine mode based on block_type and ocr_mode
    mode: OCRMode = "image"
    if block.block_type == BlockType.MATH:
        mode = "math"
    elif block.block_type == BlockType.FIGURE:
        mode = "figure"
    elif block.block_type == BlockType.ALGORITHM:
        mode = "algorithm"
    elif block.block_type == BlockType.TABLE:
        mode = "table_complex"
    else:
        mode = getattr(block, "ocr_mode", "image")

    log.info(
        "OCR [%s] | Trang %d | Block #%d (%s) | %.0fx%.0f pt",
        mode, block.page_num, block.block_id, block.block_type.value, block.width, block.height,
    )

    with _OLLAMA_SEMAPHORE:
        result = call_qwen2_vl(block.crop_bytes, mode)

    # Format result based on block type
    if not result or result.startswith("[OCR Failed"):
        log.warning(
            "OCR thất bại: Trang %d Block #%d (%s) — dùng fallback",
            block.page_num, block.block_id, block.block_type.value,
        )
        if block.block_type == BlockType.MATH:
            block.markdown_result = f"$$ [Formula p{block.page_num} #{block.block_id}] $$"
        elif block.block_type == BlockType.ALGORITHM:
            block.markdown_result = f"```algorithm\n// [Algorithm p{block.page_num} #{block.block_id}]\n{block.raw_content}\n```"
        elif block.image_rel_path:
            block.markdown_result = markdown_image_for_block(
                block.image_rel_path,
                block.page_num,
                block.block_id,
            )
        else:
            block.markdown_result = f"> [{block.block_type.value.capitalize()} p{block.page_num} — OCR Fallback]"
    else:
        if block.block_type in (BlockType.IMAGE, BlockType.FIGURE) and block.image_rel_path:
            img_tag = markdown_image_for_block(
                block.image_rel_path,
                block.page_num,
                block.block_id,
            )
            caption_str = f"\n\n> {block.caption}" if block.caption else ""
            block.markdown_result = f"{img_tag}{caption_str}\n\n{result.strip()}"
        else:
            block.markdown_result = result.strip()

    block.is_done = True
    return block


def process_ocr_blocks(
    blocks: list[DocumentBlock],
) -> list[DocumentBlock]:
    """
    Xử lý tất cả blocks cần OCR trong `blocks`.
    """
    ocr_blocks = [b for b in blocks if b.needs_ocr and not b.is_done]

    if not ocr_blocks:
        log.debug("Không có block OCR nào cần xử lý.")
        return blocks

    log.info("Bắt đầu OCR %d blocks (max %d đồng thời)...", len(ocr_blocks), OCR_CONCURRENT_REQUESTS)

    block_map = {b.block_id: b for b in blocks}
    futures: dict[Future, int] = {}

    with ThreadPoolExecutor(max_workers=OCR_CONCURRENT_REQUESTS) as executor:
        for blk in ocr_blocks:
            future = executor.submit(_ocr_single_block, blk)
            futures[future] = blk.block_id

        for future in as_completed(futures):
            bid = futures[future]
            try:
                done_block = future.result()
                block_map[bid].markdown_result = done_block.markdown_result
                block_map[bid].is_done         = done_block.is_done
                log.debug("Block #%d hoàn thành OCR.", bid)
            except Exception as exc:
                log.error("Lỗi khi OCR Block #%d: %s", bid, exc)
                block_map[bid].markdown_result = f"> [OCR Error: {exc}]"
                block_map[bid].is_done         = True

    done_count = sum(1 for b in blocks if b.is_done)
    log.info("Hoàn thành OCR: %d/%d blocks.", done_count, len(blocks))

    return blocks
