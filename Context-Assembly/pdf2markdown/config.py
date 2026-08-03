"""
Cấu hình pipeline PDF → Markdown dùng MinerU
Tối ưu cho RTX 2080 Ti (11GB VRAM)
"""

import os
from pathlib import Path

# ─── Đường dẫn ───────────────────────────────────────────────────────────────
ROOT_DIR    = Path(__file__).parent.parent          # Context-Assembly/
DATA_DIR    = ROOT_DIR / "data"                     # Thư mục chứa PDF
OUTPUT_DIR  = ROOT_DIR / "output"                   # Thư mục output Markdown
TEMP_DIR    = ROOT_DIR / "pdf2markdown" / ".tmp"    # Thư mục tạm (chunk PDF)

# ─── GPU / VRAM ───────────────────────────────────────────────────────────────
DEVICE = "cuda"          # "cuda" | "cpu"
GPU_ID = 0               # GPU index (0 = GPU đầu tiên)

# Ngưỡng VRAM an toàn cho RTX 2080 Ti (11 GB)
# MinerU layout model ~3-4 GB, OCR model ~2 GB → còn ~5 GB buffer
MAX_VRAM_GB = 10.0       # Không vượt quá 10GB để tránh OOM

# ─── Ngưỡng phát hiện "sách dài" ─────────────────────────────────────────────
# File PDF vượt ngưỡng này sẽ dùng chế độ chunked processing
LARGE_BOOK_SIZE_MB   = 5.0     # File > 5 MB → coi là sách dài
LARGE_BOOK_PAGES     = 100     # Hoặc > 100 trang → sách dài

# ─── Chunked processing cho sách dài ─────────────────────────────────────────
CHUNK_SIZE_PAGES = 30          # Số trang mỗi chunk
CHUNK_OVERLAP    = 0           # Không overlap (tài liệu liên tục)
VRAM_CLEAR_DELAY = 1.0         # Giây chờ sau khi clear VRAM giữa các chunk

# ─── MinerU / magic-pdf settings ─────────────────────────────────────────────
MINERU_PARSE_METHOD  = "auto"  # "auto" | "txt" | "ocr"
# "auto" = MinerU tự chọn: dùng txt nếu có layer text, fallback OCR nếu scan

# Ngôn ngữ OCR (cho file scan không có text layer)
OCR_LANGUAGES = ["en", "vi"]   # Tiếng Anh + Tiếng Việt

# Giữ hình ảnh trong output không?
SAVE_IMAGES  = True
IMAGE_FORMAT = "png"           # "png" | "jpg"

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"             # "DEBUG" | "INFO" | "WARNING"
LOG_FILE  = ROOT_DIR / "pdf2markdown" / "pipeline.log"

# ─── Danh sách file cần bỏ qua (nếu có) ─────────────────────────────────────
SKIP_FILES: list[str] = []     # VD: ["secret.pdf"]
