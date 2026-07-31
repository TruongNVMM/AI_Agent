"""
run.py — CLI entry point cho pipeline tiền xử lý PDF → Markdown.

Cách sử dụng:
    # Chạy toàn bộ thư mục data/ (cần Ollama đang chạy)
    python -m data_processing.run

    # Chỉ chạy 1 file cụ thể
    python -m data_processing.run --file "GAN.pdf"

    # Dry-run (không OCR, chỉ text + table) để test nhanh
    python -m data_processing.run --skip-ocr

    # Tùy chỉnh đường dẫn
    python -m data_processing.run --input ./data --output ./output --workers 2

Thiết lập Ollama trước khi chạy (cần làm 1 lần):
    # 1. Tải Ollama từ https://ollama.com và cài đặt
    # 2. Mở terminal và pull model (model ~4.5 GB khi dùng bản q4_K_M):
    ollama pull qwen2-vl:7b-q4_K_M
    # 3. Khởi động Ollama server (sẽ tự động dùng GPU nếu có driver CUDA):
    ollama serve

Biến môi trường để tránh OOM trên RTX 2080 Ti:
    set OLLAMA_FLASH_ATTENTION=1
    set OLLAMA_MAX_LOADED_MODELS=1
    set CUDA_VISIBLE_DEVICES=0
    ollama serve
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
from pathlib import Path

# Fix Windows console UTF-8 encoding (avoid UnicodeEncodeError for Vietnamese/emoji)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Thêm project root vào sys.path khi chạy trực tiếp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_processing.config import CPU_PDF_WORKERS, DATA_DIR, LOG_LEVEL, OUTPUT_DIR
from data_processing.pipeline import run_pipeline


def setup_logging(level: str = LOG_LEVEL) -> None:
    """Cấu hình logging với format rõ ràng."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Tắt bớt log lộn xộn từ thư viện bên thứ ba
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PDF → Markdown Hybrid Pipeline (Qwen2-VL + PyMuPDF)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=DATA_DIR,
        help=f"Thư mục chứa file PDF (mặc định: {DATA_DIR})",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=OUTPUT_DIR,
        help=f"Thư mục xuất Markdown (mặc định: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="Chỉ xử lý file PDF có tên chứa chuỗi này (ví dụ: 'GAN')",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=CPU_PDF_WORKERS,
        help=f"Số process CPU song song (mặc định: {CPU_PDF_WORKERS})",
    )
    parser.add_argument(
        "--skip-ocr",
        action="store_true",
        default=False,
        help="Bỏ qua Ollama OCR — chỉ xử lý text và table (offline mode)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=LOG_LEVEL,
        help=f"Mức độ log (mặc định: {LOG_LEVEL})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    log = logging.getLogger("run")

    # Kiểm tra thư mục input
    if not args.input.exists():
        log.error("Thư mục input không tồn tại: %s", args.input)
        sys.exit(1)

    pdf_count = len(list(args.input.glob("*.pdf")))
    if pdf_count == 0:
        log.error("Không tìm thấy file PDF trong: %s", args.input)
        sys.exit(1)

    log.info("=" * 60)
    log.info("PDF -> Markdown Hybrid Pipeline")
    log.info("  Input:    %s (%d files)", args.input, pdf_count)
    log.info("  Output:   %s", args.output)
    log.info("  Workers:  %d", args.workers)
    log.info("  Skip OCR: %s", args.skip_ocr)
    if args.file:
        log.info("  Filter:   '%s'", args.file)
    log.info("=" * 60)

    if not args.skip_ocr:
        log.info(
            "Make sure Ollama is running and model is pulled:\n"
            "  > ollama pull qwen2-vl:7b-q4_K_M\n"
            "  > set OLLAMA_FLASH_ATTENTION=1 && ollama serve"
        )

    results = run_pipeline(
        input_dir=args.input,
        output_dir=args.output,
        skip_ocr=args.skip_ocr,
        workers=args.workers,
        file_filter=args.file,
    )

    if not results:
        log.warning("No results were produced.")
        sys.exit(1)

    log.info("\nPipeline complete! Output at: %s", args.output)
    for r in results:
        s = r.summary()
        log.info(
            "  [%s] %d pages | %d text | %d table | %d image | %d math",
            s["doc_name"], s["total_pages"],
            s["text_blocks"], s["table_blocks"],
            s["image_blocks"], s["math_blocks"],
        )


if __name__ == "__main__":
    main()
