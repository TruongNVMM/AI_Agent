"""
ocr_worker.py — Worker điều phối OCR cho các blocks IMAGE và MATH.

Thiết kế để tránh OOM:
- Chỉ 1 thread gọi Ollama tại một thời điểm (OCR_CONCURRENT_REQUESTS=1).
- Sử dụng threading.Semaphore để đảm bảo không bao giờ có 2 request song song.
- Nếu người dùng muốn tăng throughput sau khi xác nhận VRAM đủ, chỉ cần
  tăng OCR_CONCURRENT_REQUESTS trong config.py.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Literal

from .config import OCR_CONCURRENT_REQUESTS
from .models import BlockType, DocumentBlock
from .vision_client import call_qwen2_vl

log = logging.getLogger(__name__)

# Semaphore toàn cục: giới hạn số request Ollama đồng thời
# Đây là cơ chế chính ngăn OOM khi nhiều page được xử lý song song.
_OLLAMA_SEMAPHORE = threading.Semaphore(OCR_CONCURRENT_REQUESTS)


def _ocr_single_block(block: DocumentBlock) -> DocumentBlock:
    """
    Xử lý OCR cho 1 block (IMAGE hoặc MATH).

    Luôn acquire Semaphore trước khi gọi Ollama để đảm bảo
    tối đa OCR_CONCURRENT_REQUESTS request đồng thời.
    """
    if not block.needs_ocr or block.crop_bytes is None:
        block.is_done = True
        return block

    mode: Literal["image", "math"] = (
        "math" if block.block_type == BlockType.MATH else "image"
    )

    log.info(
        "OCR [%s] | Trang %d | Block #%d | %.0fx%.0f pt",
        mode, block.page_num, block.block_id, block.width, block.height,
    )

    with _OLLAMA_SEMAPHORE:
        result = call_qwen2_vl(block.crop_bytes, mode)

    # Fallback nếu OCR thất bại
    if not result or result.startswith("[OCR Failed"):
        log.warning(
            "OCR thất bại: Trang %d Block #%d — dùng placeholder",
            block.page_num, block.block_id,
        )
        if block.block_type == BlockType.MATH:
            block.markdown_result = f"$[Công thức trang {block.page_num}]$"
        else:
            block.markdown_result = f"> [Hình ảnh trang {block.page_num} — không thể OCR]"
    else:
        block.markdown_result = result

    block.is_done = True
    return block


def process_ocr_blocks(
    blocks: list[DocumentBlock],
) -> list[DocumentBlock]:
    """
    Xử lý tất cả blocks cần OCR trong danh sách `blocks`.

    Blocks TEXT/TABLE đã có markdown_result từ layout_detector — bỏ qua.
    Chỉ submit các block IMAGE/MATH vào ThreadPoolExecutor.

    Args:
        blocks: Danh sách DocumentBlock đã có block_id bất biến.

    Returns:
        Cùng danh sách blocks, với markdown_result đã được điền cho IMAGE/MATH.
        Thứ tự danh sách KHÔNG thay đổi.
    """
    # Tách blocks cần OCR
    ocr_blocks = [b for b in blocks if b.needs_ocr and not b.is_done]

    if not ocr_blocks:
        log.debug("Không có block OCR nào cần xử lý.")
        return blocks

    log.info("Bắt đầu OCR %d blocks (max %d đồng thời)...", len(ocr_blocks), OCR_CONCURRENT_REQUESTS)

    # Build lookup dict: block_id → block object
    block_map = {b.block_id: b for b in blocks}

    # Submit vào thread pool
    futures: dict[Future, int] = {}  # future → block_id
    with ThreadPoolExecutor(max_workers=OCR_CONCURRENT_REQUESTS) as executor:
        for blk in ocr_blocks:
            future = executor.submit(_ocr_single_block, blk)
            futures[future] = blk.block_id

        # Thu thập kết quả theo thứ tự hoàn thành (không ảnh hưởng thứ tự cuối)
        for future in as_completed(futures):
            bid = futures[future]
            try:
                done_block = future.result()
                # Ghi đè kết quả vào đúng block trong block_map
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
