"""
MinerU Processor — Wrapper xử lý 1 file PDF bằng MinerU (magic-pdf)
Hỗ trợ: single file, chunked (sách dài)
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from config import (
    CHUNK_SIZE_PAGES,
    DEVICE,
    GPU_ID,
    MINERU_PARSE_METHOD,
    OCR_LANGUAGES,
    OUTPUT_DIR,
    SAVE_IMAGES,
    TEMP_DIR,
)
from gpu_manager import clear_vram, log_vram, vram_guard
from pdf_chunker import (
    cleanup_chunks,
    is_large_book,
    merge_markdown_chunks,
    split_pdf_into_chunks,
)

logger = logging.getLogger(__name__)


def _run_mineru_on_single_pdf(
    pdf_path: Path,
    out_dir: Path,
) -> Optional[Path]:
    """
    Gọi MinerU (magic-pdf) để chuyển 1 file PDF → Markdown.

    Args:
        pdf_path: Đường dẫn file PDF input.
        out_dir:  Thư mục output cho file này.

    Returns:
        Đường dẫn file markdown output, hoặc None nếu thất bại.
    """
    try:
        # Import ở đây để tránh load model khi không cần
        from magic_pdf.data.data_reader_writer import FileBasedDataWriter
        from magic_pdf.data.dataset import PymuDocDataset
        from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
        from magic_pdf.config.make_content_config import DropMode, MakeMode

        out_dir.mkdir(parents=True, exist_ok=True)
        images_dir = out_dir / "images"
        images_dir.mkdir(exist_ok=True)

        # Data writer
        image_writer = FileBasedDataWriter(str(images_dir))
        md_writer     = FileBasedDataWriter(str(out_dir))

        # Load PDF
        pdf_bytes = pdf_path.read_bytes()
        ds = PymuDocDataset(pdf_bytes)

        # Phân tích layout + OCR
        logger.info(f"  → Đang phân tích layout với MinerU ({MINERU_PARSE_METHOD})...")
        infer_result = ds.apply(
            doc_analyze,
            ocr=True,
        )

        # Render markdown
        logger.info(f"  → Đang render Markdown...")
        if MINERU_PARSE_METHOD == "ocr":
            pipe_result = infer_result.pipe_ocr_mode(image_writer)
        else:
            pipe_result = infer_result.pipe_auto_mode(image_writer)

        md_filename = pdf_path.stem + ".md"
        pipe_result.dump_md(md_writer, md_filename, str(images_dir))

        md_path = out_dir / md_filename
        if md_path.exists():
            size_kb = md_path.stat().st_size / 1e3
            logger.info(f"  ✓ Output: {md_path.name} ({size_kb:.1f} KB)")
            return md_path

        logger.error(f"  ✗ Không tìm thấy file markdown output: {md_path}")
        return None

    except Exception as e:
        logger.error(f"  ✗ Lỗi khi xử lý {pdf_path.name}: {e}", exc_info=True)
        return None


def process_single_file(pdf_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Xử lý 1 file PDF bình thường (không phải sách dài).
    Dùng vram_guard để tự động monitor và clear VRAM.
    """
    out_dir = output_dir / pdf_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[NORMAL] Xử lý: {pdf_path.name}")
    log_vram(prefix=f"  [Before] ")

    with vram_guard(label=pdf_path.name, required_gb=4.0):
        result = _run_mineru_on_single_pdf(pdf_path, out_dir)

    return result


def process_large_book(pdf_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Xử lý sách dài bằng cách chia thành chunk nhỏ.

    Chiến lược chống tràn VRAM:
    1. Chia PDF thành các chunk 30 trang
    2. Xử lý từng chunk, clear VRAM giữa mỗi chunk
    3. Ghép các markdown chunk lại thành 1 file hoàn chỉnh
    4. Dọn dẹp file tạm
    """
    logger.info(f"[LARGE BOOK] Xử lý sách dài: {pdf_path.name}")
    logger.info(f"  Chiến lược: Chunked processing ({CHUNK_SIZE_PAGES} trang/chunk)")

    # ── Bước 1: Chia PDF ─────────────────────────────────────────────────────
    chunk_pdf_paths = split_pdf_into_chunks(pdf_path, CHUNK_SIZE_PAGES)
    total_chunks = len(chunk_pdf_paths)
    logger.info(f"  Tổng số chunk: {total_chunks}")

    # ── Bước 2: Xử lý từng chunk ─────────────────────────────────────────────
    chunk_md_paths: list[Path] = []
    failed_chunks:  list[int]  = []

    for i, chunk_pdf in enumerate(chunk_pdf_paths, start=1):
        chunk_out_dir = TEMP_DIR / pdf_path.stem / f"chunk_{i:03d}_output"
        chunk_out_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"  ── Chunk {i}/{total_chunks}: {chunk_pdf.name}")
        log_vram(prefix=f"    [Before chunk {i}] ")

        with vram_guard(label=f"chunk {i}/{total_chunks}", required_gb=3.0):
            md_path = _run_mineru_on_single_pdf(chunk_pdf, chunk_out_dir)

        if md_path and md_path.exists():
            chunk_md_paths.append(md_path)
            logger.info(f"  ✓ Chunk {i} hoàn thành")
        else:
            logger.error(f"  ✗ Chunk {i} thất bại, bỏ qua...")
            failed_chunks.append(i)

    # ── Bước 3: Ghép markdown ─────────────────────────────────────────────────
    if not chunk_md_paths:
        logger.error(f"[{pdf_path.name}] Tất cả chunk đều thất bại!")
        cleanup_chunks(pdf_path)
        return None

    if failed_chunks:
        logger.warning(
            f"[{pdf_path.name}] {len(failed_chunks)} chunk thất bại: {failed_chunks}. "
            f"Ghép {len(chunk_md_paths)} chunk thành công."
        )

    final_out_dir = output_dir / pdf_path.stem
    final_out_dir.mkdir(parents=True, exist_ok=True)
    final_md_path = final_out_dir / f"{pdf_path.stem}.md"

    merge_markdown_chunks(chunk_md_paths, final_md_path, pdf_path.name)

    # Copy hình ảnh từ các chunk vào thư mục images chung
    _merge_images(chunk_pdf_paths, final_out_dir, pdf_path.stem)

    # ── Bước 4: Dọn dẹp ──────────────────────────────────────────────────────
    cleanup_chunks(pdf_path)
    logger.info(f"[{pdf_path.name}] ✓ Hoàn thành sách dài → {final_md_path}")

    return final_md_path


def _merge_images(
    chunk_pdf_paths: list[Path],
    final_out_dir: Path,
    stem: str,
) -> None:
    """Copy toàn bộ hình ảnh từ chunk outputs vào images/ chung."""
    if not SAVE_IMAGES:
        return

    merged_images_dir = final_out_dir / "images"
    merged_images_dir.mkdir(exist_ok=True)

    for i, chunk_pdf in enumerate(chunk_pdf_paths, start=1):
        chunk_out_dir = TEMP_DIR / stem / f"chunk_{i:03d}_output"
        chunk_images_dir = chunk_out_dir / "images"

        if not chunk_images_dir.exists():
            continue

        for img_file in chunk_images_dir.iterdir():
            if img_file.is_file():
                # Đổi tên để tránh conflict: chunk001_image_0.png
                new_name = f"chunk{i:03d}_{img_file.name}"
                dest = merged_images_dir / new_name
                shutil.copy2(img_file, dest)

    count = len(list(merged_images_dir.iterdir()))
    if count > 0:
        logger.info(f"  Đã merge {count} ảnh → {merged_images_dir}")


def process_pdf(pdf_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Entry point: tự động chọn chế độ xử lý phù hợp.
    - Sách dài (> 5MB hoặc > 100 trang) → chunked processing
    - File bình thường → single processing
    """
    if is_large_book(pdf_path):
        return process_large_book(pdf_path, output_dir)
    else:
        return process_single_file(pdf_path, output_dir)
