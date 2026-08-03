"""
Main Pipeline — PDF → Markdown
Quét toàn bộ PDF trong thư mục data/, xử lý và lưu vào output/

Chạy:
    python pdf2markdown/run_pipeline.py
    python pdf2markdown/run_pipeline.py --dry-run          # Chỉ liệt kê file
    python pdf2markdown/run_pipeline.py --file "Deep.pdf"  # Chỉ 1 file
    python pdf2markdown/run_pipeline.py --resume           # Bỏ qua file đã xong
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from datetime import datetime

# Thêm thư mục pdf2markdown vào sys.path
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    DATA_DIR,
    LOG_FILE,
    LOG_LEVEL,
    OUTPUT_DIR,
    SKIP_FILES,
    TEMP_DIR,
)
from gpu_manager import (
    clear_vram,
    get_device,
    get_vram_stats,
    log_vram,
    set_gpu_memory_fraction,
)
from mineru_processor import process_pdf


# ─── Logging Setup ────────────────────────────────────────────────────────────

def setup_logging(level: str = LOG_LEVEL) -> None:
    """Cấu hình logging: console + file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    fmt = "%(asctime)s | %(levelname)-8s | %(message)s"
    datefmt = "%H:%M:%S"

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ]

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
        force=True,
    )

    # Giảm noise từ các thư viện bên ngoài
    for noisy_lib in ["PIL", "fitz", "urllib3", "httpx"]:
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def collect_pdf_files(data_dir: Path, skip: list[str] = None) -> list[Path]:
    """Quét toàn bộ file PDF trong thư mục data (không đệ quy con)."""
    skip = skip or []
    pdfs = sorted(
        p for p in data_dir.glob("*.pdf")
        if p.name not in skip
    )
    return pdfs


def already_done(pdf_path: Path, output_dir: Path) -> bool:
    """Kiểm tra xem file đã được convert chưa."""
    expected_md = output_dir / pdf_path.stem / f"{pdf_path.stem}.md"
    return expected_md.exists() and expected_md.stat().st_size > 0


def print_summary(results: dict) -> None:
    """In tóm tắt kết quả pipeline."""
    success = [k for k, v in results.items() if v == "success"]
    skipped = [k for k, v in results.items() if v == "skipped"]
    failed  = [k for k, v in results.items() if v == "failed"]

    logger.info("=" * 60)
    logger.info("📊 KẾT QUẢ PIPELINE")
    logger.info("=" * 60)
    logger.info(f"  ✅ Thành công : {len(success)} file")
    logger.info(f"  ⏭️  Đã bỏ qua : {len(skipped)} file")
    logger.info(f"  ❌ Thất bại  : {len(failed)} file")

    if failed:
        logger.info("\n  Các file thất bại:")
        for f in failed:
            logger.info(f"    • {f}")

    logger.info("=" * 60)


# ─── Main Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    data_dir: Path,
    output_dir: Path,
    dry_run:  bool = False,
    resume:   bool = False,
    target_file: str = None,
) -> None:
    """
    Pipeline chính:
    1. Quét PDF trong data_dir
    2. Với mỗi file: tự động chọn normal/chunked processing
    3. Lưu markdown vào output_dir/<pdf_stem>/<pdf_stem>.md
    """
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("🚀 BẮT ĐẦU PIPELINE PDF → MARKDOWN")
    logger.info(f"   Input  : {data_dir}")
    logger.info(f"   Output : {output_dir}")
    logger.info(f"   Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Kiểm tra GPU
    device = get_device()
    vram = get_vram_stats()
    logger.info(f"GPU VRAM: {vram['total']} GB total, {vram['free']} GB free")

    # Giới hạn VRAM sử dụng
    set_gpu_memory_fraction(0.90)

    # Tạo thư mục output và temp
    output_dir.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # Thu thập file PDF
    if target_file:
        # Chỉ xử lý 1 file
        pdf_files = [data_dir / target_file]
        if not pdf_files[0].exists():
            logger.error(f"Không tìm thấy file: {pdf_files[0]}")
            return
    else:
        pdf_files = collect_pdf_files(data_dir, skip=SKIP_FILES)

    if not pdf_files:
        logger.warning(f"Không tìm thấy file PDF nào trong {data_dir}")
        return

    logger.info(f"\nTìm thấy {len(pdf_files)} file PDF:")
    for i, p in enumerate(pdf_files, 1):
        size_mb = p.stat().st_size / 1e6
        logger.info(f"  {i:2d}. {p.name:<55} ({size_mb:6.1f} MB)")

    if dry_run:
        logger.info("\n[DRY RUN] Không thực sự xử lý file.")
        return

    # Xử lý từng file
    results: dict[str, str] = {}

    for i, pdf_path in enumerate(pdf_files, start=1):
        logger.info(f"\n{'─' * 60}")
        logger.info(f"[{i}/{len(pdf_files)}] {pdf_path.name}")
        logger.info(f"{'─' * 60}")

        # Bỏ qua nếu đã xong (resume mode)
        if resume and already_done(pdf_path, output_dir):
            logger.info(f"⏭️  Đã convert trước đó, bỏ qua.")
            results[pdf_path.name] = "skipped"
            continue

        file_start = time.time()

        try:
            md_path = process_pdf(pdf_path, output_dir)

            elapsed = time.time() - file_start
            if md_path and md_path.exists():
                size_kb = md_path.stat().st_size / 1e3
                logger.info(
                    f"✅ Hoàn thành trong {elapsed:.1f}s → "
                    f"{md_path.relative_to(output_dir)} ({size_kb:.1f} KB)"
                )
                results[pdf_path.name] = "success"
            else:
                logger.error(f"❌ Thất bại sau {elapsed:.1f}s")
                results[pdf_path.name] = "failed"

        except Exception as e:
            elapsed = time.time() - file_start
            logger.error(
                f"❌ Lỗi không xử lý được sau {elapsed:.1f}s: {e}",
                exc_info=True,
            )
            results[pdf_path.name] = "failed"

        finally:
            # Luôn clear VRAM giữa các file
            clear_vram(delay=1.0)
            log_vram(prefix="[Between files] ")

    # Tổng kết
    total_elapsed = time.time() - start_time
    logger.info(f"\nTổng thời gian: {total_elapsed/60:.1f} phút")
    print_summary(results)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pipeline chuyển đổi PDF → Markdown dùng MinerU",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python pdf2markdown/run_pipeline.py                           # Chạy toàn bộ
  python pdf2markdown/run_pipeline.py --dry-run                 # Liệt kê file
  python pdf2markdown/run_pipeline.py --resume                  # Bỏ qua file đã xong
  python pdf2markdown/run_pipeline.py --file "DeepLearning.pdf" # Chỉ 1 file
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ liệt kê file, không xử lý",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Bỏ qua file đã convert trước đó",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        metavar="FILENAME",
        help="Chỉ xử lý 1 file cụ thể (tên file, không cần đường dẫn đầy đủ)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Mức độ log (mặc định: INFO)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.log_level)

    run_pipeline(
        data_dir=DATA_DIR,
        output_dir=OUTPUT_DIR,
        dry_run=args.dry_run,
        resume=args.resume,
        target_file=args.file,
    )
