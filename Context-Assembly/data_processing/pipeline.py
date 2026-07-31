"""
pipeline.py — Điều phối toàn bộ pipeline xử lý PDF → Markdown.

Kiến trúc xử lý song song:
  - ProcessPoolExecutor: xử lý nhiều file PDF song song (CPU-bound: render, detect).
  - Mỗi worker process chạy toàn bộ pipeline cho 1 file.
  - Ollama OCR được gọi tuần tự qua Semaphore trong mỗi worker.

Lưu ý quan trọng về OOM:
  - GPU RTX 2080 Ti nhận request OCR từ 1 process tại một thời điểm (Semaphore).
  - Nếu chạy CPU_PDF_WORKERS=4, tối đa 4 process cùng RENDER PDF (CPU RAM).
  - Nhưng tối đa OCR_CONCURRENT_REQUESTS=1 gọi Ollama → VRAM an toàn.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import fitz

from .config import CPU_PDF_WORKERS, OUTPUT_DIR, IMAGE_DIR
from .layout_detector import classify_document_layout
from .models import DocumentResult, PageResult
from .page_processor import process_page
from .postprocessor import postprocess_document
from .vision_client import check_ollama_health

log = logging.getLogger(__name__)


# ─── Single document processor (chạy trong 1 process riêng) ──────────────────

def process_document(
    pdf_path: Path,
    output_dir: Path,
    skip_ocr: bool = False,
) -> DocumentResult:
    """
    Xử lý hoàn chỉnh 1 file PDF.

    Được thiết kế để chạy trong ProcessPoolExecutor worker.
    Mỗi worker tự mở riêng file PDF, tự xử lý từng trang,
    tự gọi Ollama (với Semaphore toàn cục).

    Args:
        pdf_path:   Đường dẫn đến file PDF.
        output_dir: Thư mục lưu file .md kết quả.
        skip_ocr:   Nếu True, không gọi Ollama (offline / dry-run).

    Returns:
        DocumentResult với toàn bộ thống kê.
    """
    t_start  = time.perf_counter()
    doc_name = pdf_path.name
    log.info("=" * 60)
    log.info("Processing: %s", doc_name)

    result = DocumentResult(doc_name=doc_name, source_path=pdf_path)

    try:
        doc    = fitz.open(pdf_path)
        layout = classify_document_layout(doc)
        log.info("[%s] Layout: %s | %d pages", doc_name, layout, len(doc))

        pages_markdown_raw: list[str] = []
        page_results: list[PageResult] = []

        # ── Xử lý từng trang tuần tự ─────────────────────────────────────────
        # (OCR là bottleneck; không lợi gì khi song song hóa trong cùng process)
        for page_num in range(1, len(doc) + 1):
            page   = doc[page_num - 1]
            pr     = process_page(
                page=page,
                page_num=page_num,
                doc_name=doc_name,
                layout=layout,
                skip_ocr=skip_ocr,
            )
            page_results.append(pr)
            pages_markdown_raw.append(pr.markdown)

            # Cập nhật thống kê
            for block in pr.blocks:
                result.total_blocks += 1
                match block.block_type.value:
                    case "text":  result.text_blocks  += 1
                    case "table": result.table_blocks += 1
                    case "image": result.image_blocks += 1
                    case "math":  result.math_blocks  += 1

        result.pages = page_results

        # ── Hậu xử lý cấp tài liệu ────────────────────────────────────────────
        processed_pages, doc_metadata = postprocess_document(
            pages_markdown_raw, doc, doc_name
        )

        # ── Ghi file Markdown ─────────────────────────────────────────────────
        output_dir.mkdir(parents=True, exist_ok=True)
        stem      = pdf_path.stem
        out_md    = output_dir / f"{stem}.md"
        out_meta  = output_dir / f"{stem}_metadata.json"

        # Tổng hợp markdown cuối cùng
        final_parts: list[str] = []
        # YAML frontmatter
        final_parts.append(
            f"---\n"
            f"title: \"{stem}\"\n"
            f"source: \"{doc_name}\"\n"
            f"pages: {len(doc)}\n"
            f"layout: \"{layout}\"\n"
            f"---\n"
        )

        for i, page_md in enumerate(processed_pages):
            page_num = i + 1
            if page_md.strip():
                final_parts.append(f"<!-- page {page_num} -->\n\n{page_md}")

        final_markdown = "\n\n---\n\n".join(final_parts)
        out_md.write_text(final_markdown, encoding="utf-8")
        log.info("[%s] Saved: %s (%d chars)", doc_name, out_md, len(final_markdown))

        # Ghi metadata JSON
        meta = {
            **result.summary(),
            "layout":           layout,
            "references_page":  doc_metadata.get("references_page"),
            "section_map":      {str(k): v for k, v in doc_metadata["section_map"].items()},
        }
        out_meta.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    except Exception as exc:
        log.error("[%s] CRITICAL ERROR: %s", doc_name, exc, exc_info=True)

    elapsed = time.perf_counter() - t_start
    log.info("[%s] Done in %.1f seconds.", doc_name, elapsed)
    log.info("  Stats: %s", result.summary())
    return result


# ─── Main orchestrator ────────────────────────────────────────────────────────

def run_pipeline(
    input_dir: Path,
    output_dir: Path = OUTPUT_DIR,
    skip_ocr: bool = False,
    workers: int = CPU_PDF_WORKERS,
    file_filter: str | None = None,
) -> list[DocumentResult]:
    """
    Chạy pipeline cho tất cả PDF trong input_dir.

    Args:
        input_dir:   Thư mục chứa các file PDF.
        output_dir:  Thư mục xuất kết quả Markdown.
        skip_ocr:    Bỏ qua Ollama OCR (offline mode).
        workers:     Số process CPU xử lý song song.
        file_filter: Nếu set, chỉ xử lý file có tên chứa chuỗi này.

    Returns:
        Danh sách DocumentResult cho tất cả file đã xử lý.
    """
    t_total = time.perf_counter()

    # Tìm file PDF
    pdf_files = sorted(input_dir.glob("*.pdf"))
    if file_filter:
        pdf_files = [f for f in pdf_files if file_filter.lower() in f.name.lower()]

    if not pdf_files:
        log.warning("No PDF files found in %s", input_dir)
        return []

    log.info("Total PDF files: %d", len(pdf_files))
    for f in pdf_files:
        log.info("  - %s (%.1f MB)", f.name, f.stat().st_size / 1024**2)

    # Check Ollama health before starting
    if not skip_ocr:
        if not check_ollama_health():
            log.warning(
                "Ollama is unavailable or model not pulled. "
                "Pipeline will use placeholders for IMAGE/MATH blocks. "
                "To enable OCR:\n"
                "  1. Install Ollama: https://ollama.com\n"
                "  2. Pull model: ollama pull qwen2-vl:7b-q4_K_M\n"
                "  3. Start server: ollama serve"
            )
            skip_ocr = True  # Auto-fallback to offline mode

    output_dir.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    all_results: list[DocumentResult] = []

    # ── Xử lý song song nhiều file PDF ────────────────────────────────────────
    # Lưu ý: mỗi worker process có Semaphore độc lập, nhưng Ollama server
    # chỉ có 1 → các request vẫn được tuần tự hóa ở phía server.
    # Vì vậy CPU_PDF_WORKERS chủ yếu giúp song song hóa phần RENDER + DETECT (CPU-bound).
    effective_workers = min(workers, len(pdf_files))

    if effective_workers == 1 or len(pdf_files) == 1:
        # Chạy trong process hiện tại để dễ debug
        for pdf_path in pdf_files:
            r = process_document(pdf_path, output_dir, skip_ocr)
            all_results.append(r)
    else:
        with ProcessPoolExecutor(max_workers=effective_workers) as executor:
            futures = {
                executor.submit(process_document, pdf_path, output_dir, skip_ocr): pdf_path
                for pdf_path in pdf_files
            }
            for future in as_completed(futures):
                pdf_path = futures[future]
                try:
                    r = future.result()
                    all_results.append(r)
                except Exception as exc:
                    log.error("Worker process lỗi cho %s: %s", pdf_path.name, exc)

    # ── Tổng kết ───────────────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - t_total
    total_pages   = sum(len(r.pages) for r in all_results)
    total_blocks  = sum(r.total_blocks for r in all_results)
    total_ocr     = sum(r.image_blocks + r.math_blocks for r in all_results)

    log.info("=" * 60)
    log.info("PIPELINE COMPLETE")
    log.info("  Time elapsed:  %.1f seconds", total_elapsed)
    log.info("  Files: %d | Pages: %d | Blocks: %d", len(all_results), total_pages, total_blocks)
    log.info("  OCR blocks (image+math): %d", total_ocr)
    log.info("  Output directory: %s", output_dir)
    log.info("=" * 60)

    # Ghi báo cáo tổng hợp
    summary_path = output_dir / "pipeline_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "total_files":    len(all_results),
                "total_pages":    total_pages,
                "total_blocks":   total_blocks,
                "ocr_blocks":     total_ocr,
                "elapsed_sec":    round(total_elapsed, 2),
                "documents":      [r.summary() for r in all_results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return all_results
