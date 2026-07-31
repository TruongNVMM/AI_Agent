"""
config.py — Cấu hình trung tâm cho toàn bộ pipeline.

Chiến lược chống OOM trên RTX 2080 Ti (11 GB VRAM):
─────────────────────────────────────────────────────
Model:  qwen2-vl:7b-q4_K_M  → ~4.5 GB VRAM (quantized INT4)
KV cache:  num_ctx=2048      → ~0.5 GB VRAM
Hình ảnh:  resize ≤ 896 px  → ~1.0 GB VRAM/batch
GPU buffer overhead:          ~0.5 GB
                               ───────
Tổng ước tính:                ~6.5 GB  (còn dư ~4.5 GB cho OS)

Biến môi trường Ollama khuyến nghị (đặt trước khi chạy ollama serve):
  OLLAMA_FLASH_ATTENTION=1        # giảm VRAM KV cache lên tới 40%
  OLLAMA_MAX_LOADED_MODELS=1      # chỉ 1 model cùng lúc, tránh double-load
  CUDA_VISIBLE_DEVICES=0          # ghim vào GPU index 0
"""

from __future__ import annotations

from pathlib import Path

# ─── Đường dẫn ──────────────────────────────────────────────────────────────
ROOT_DIR    = Path(__file__).resolve().parent.parent
DATA_DIR    = ROOT_DIR / "data"
OUTPUT_DIR  = ROOT_DIR / "output"
IMAGE_DIR   = OUTPUT_DIR / "images"   # thư mục lưu ảnh crop trung gian

# ─── Ollama ─────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL    = "http://localhost:11434"

# Dùng bản 4-bit quantized: ~4.5 GB VRAM, ít hơn 3x so với FP16 (~14 GB).
# Kéo về bằng: ollama pull qwen2-vl:7b-q4_K_M
QWEN2_VL_MODEL     = "qwen2-vl:7b-q4_K_M"

# Cấu hình inference cho Ollama (gửi kèm mỗi request trong field "options")
OLLAMA_OPTIONS: dict = {
    # Độ dài context text (token).
    # 2048 → ~0.5 GB VRAM; tăng lên 4096 → ~1 GB (cẩn thận OOM).
    "num_ctx": 2048,

    # Số GPU layer offload. -1 = tất cả lên GPU (RTX 2080 Ti đủ cho q4_K_M).
    # Nếu OOM, hạ xuống 28 (offload 28/36 layers) để lưu 1-2 GB VRAM.
    "num_gpu": -1,

    # Số thread CPU dùng cho các layer không offload lên GPU.
    "num_thread": 4,

    # Giảm randomness — với OCR/mô tả ảnh thường tốt hơn khi temperature thấp.
    "temperature": 0.1,

    # Top-k sampling nhỏ để output ổn định, ít hallucination.
    "top_k": 10,

    # Không stream từng token — nhận cả response một lần cho đơn giản.
    "stream": False,
}

# Thời gian timeout (giây) cho mỗi request Ollama.
# Ảnh/đồ thị phức tạp có thể mất 20-60s trên CPU, 5-15s trên GPU.
OLLAMA_TIMEOUT_SEC = 120

# Số lần retry khi Ollama trả về lỗi (503, kết nối thất bại...).
OLLAMA_MAX_RETRIES = 3

# ─── Chống OOM: kiểm soát concurrency ───────────────────────────────────────
# SỐ request gửi Ollama đồng thời.
# Quan trọng: để 1 để tránh Ollama load 2 ảnh lớn vào VRAM cùng lúc.
# Nếu RTX 2080 Ti còn dư VRAM sau khi model load, có thể tăng lên 2.
OCR_CONCURRENT_REQUESTS = 1

# ─── Cắt và resize ảnh trước khi gửi OCR ────────────────────────────────────
# Độ phân giải render trang PDF → ảnh (DPI).
# 150 DPI: chất lượng tốt, file nhỏ. 200 DPI nếu OCR sai nhiều.
RENDER_DPI = 150

# Kích thước dài nhất (px) cho phép của ảnh crop gửi sang Qwen2-VL.
# Qwen2-VL chia ảnh thành các patch 28×28; ảnh 896×896 → 1024 patch → ~1 GB VRAM.
# KHÔNG tăng quá 1024 px trên RTX 2080 Ti để tránh OOM.
OCR_MAX_IMAGE_SIZE = 896   # px (cạnh dài nhất)

# Nếu vùng block quá nhỏ (px), bỏ qua OCR — thường là artifact PDF.
OCR_MIN_CROP_AREA = 40 * 40  # pixel^2

# ─── CPU xử lý song song ─────────────────────────────────────────────────────
# Số process Python xử lý song song các file PDF khác nhau.
# Mỗi process tốn ~200 MB RAM (PyMuPDF + PIL).
# RAM hiện tại 7 GB → đặt tối đa 4 worker.
CPU_PDF_WORKERS = 4

# ─── Layout detection ────────────────────────────────────────────────────────
# Ngưỡng (points) của vùng header/footer sẽ bị lọc bỏ.
HEADER_ZONE_PT = 48
FOOTER_ZONE_PT = 48

# Ngưỡng x-offset (points) để phân biệt cột trái/phải trong layout 2 cột.
TWO_COLUMN_GUTTER_PX = 20

# Số lượng block tối thiểu để xem là 2 cột hợp lệ (tránh nhận sai 1 cột).
TWO_COLUMN_MIN_BLOCKS_PER_COL = 3

# ─── Phân loại block ─────────────────────────────────────────────────────────
# Ký hiệu Unicode toán học — nếu block text chứa bất kỳ ký tự nào,
# sẽ được xếp vào loại 'math' để gửi OCR.
MATH_UNICODE_CHARS = set("∑∂∇√≈≠≤≥±×÷∫∏∀∃∈∉⊂⊃∪∩→⇒⟨⟩‖‹›αβγδεζηθλμπρστφψω")

# Nếu block text có tỉ lệ ký tự toán/tổng ký tự vượt ngưỡng này → 'math'.
MATH_CHAR_RATIO_THRESHOLD = 0.08

# ─── Postprocessor ───────────────────────────────────────────────────────────
# Số trang cuối tính từ References section sẽ bị đánh dấu is_references=True.
REFERENCES_LOOKBACK_PAGES = 1

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"  # DEBUG | INFO | WARNING | ERROR
