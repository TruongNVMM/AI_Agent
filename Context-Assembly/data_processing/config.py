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

# Tên model chuẩn trên thư viện Ollama: "qwen2-vl:7b" (hoặc "qwen2.5vl:7b")
# Mặc định Ollama đã tự động dùng bản 4-bit quantized (Q4_K_M ~4.5 GB VRAM).
QWEN2_VL_MODEL     = "qwen2-vl:7b"

# Cấu hình inference cho Ollama (gửi kèm mỗi request trong field "options")
OLLAMA_OPTIONS: dict = {
    # Độ dài context text (token).
    # 2048 → ~0.5 GB VRAM; tăng lên 4096 → ~1 GB (cẩn thận OOM).
    "num_ctx": 2048,

    # Số GPU layer offload. -1 = tất cả lên GPU (RTX 2080 Ti đủ cho q4_K_M).
    # Nếu OOM, hạ xuống 28 (offload 28/36 layers) để lưu 1-2 GB VRAM.
    "num_gpu": -1,

    # Số thread CPU dùng cho Ollama (đã tối ưu cho CPU 12 lõi: dùng 8 threads
    # để vừa tăng tốc vừa chừa 4 lõi cho hệ điều hành và CPU PDF Workers).
    "num_thread": 8,

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
# Đã tối ưu cho CPU 12 lõi: đặt 6 workers (mỗi process tốn ~150-200 MB RAM).
# 6 workers giúp render và phân loại layout đồng thời 6 file PDF cực nhanh.
CPU_PDF_WORKERS = 6

# ─── Layout detection ────────────────────────────────────────────────────────
# Ngưỡng (points) của vùng header/footer sẽ bị lọc bỏ.
HEADER_ZONE_PT = 48
FOOTER_ZONE_PT = 48

# Ngưỡng x-offset (points) để phân biệt cột trái/phải trong layout 2 cột.
TWO_COLUMN_GUTTER_PX = 20

# Số lượng block tối thiểu để xem là 2 cột hợp lệ (tránh nhận sai 1 cột).
TWO_COLUMN_MIN_BLOCKS_PER_COL = 3

# ─── Gutter Analysis (cải tiến 2-column detection) ───────────────────────────
# Khoảng trắng dọc tối thiểu (points) để được coi là gutter giữa 2 cột.
GUTTER_MIN_WIDTH_PT = 8.0

# Gutter phải xuất hiện ở vị trí X nằm trong vùng trung tâm trang này
# (tránh nhầm lề trang thành gutter). Tỉ lệ trên chiều rộng trang.
GUTTER_CENTER_ZONE = (0.3, 0.7)  # gutter phải nằm trong 30%-70% chiều rộng

# Gutter phải có chiều cao liên tục chiếm ít nhất bao nhiêu % chiều cao trang.
GUTTER_MIN_HEIGHT_RATIO = 0.4

# ─── Heading Detection (font-based) ──────────────────────────────────────────
# Khi font size của span vượt (body_size * ratio) thì coi là heading tương ứng.
# Ví dụ: body_size=10pt, ratio=1.4 → span >= 14pt là H1.
HEADING_FONT_RATIOS: dict[int, float] = {
    1: 1.6,   # H1: >= 160% font body
    2: 1.35,  # H2: >= 135% font body
    3: 1.15,  # H3: >= 115% font body
}

# Số ký tự tối thiểu và tối đa để một span được coi là heading
# (tránh đánh dấu số trang hoặc chữ đơn lẻ là heading)
HEADING_MIN_CHARS = 3
HEADING_MAX_CHARS = 200

# ─── Math Detection (font-based) ─────────────────────────────────────────────
# Các tên font chứa ký tự này thường là font toán học LaTeX.
# PyMuPDF trả về tên font trong span["font"] hoặc span["fontname"].
MATH_FONT_SUBSTRINGS: tuple[str, ...] = (
    "CMMI",      # Computer Modern Math Italic — biến số toán học
    "CMSY",      # Computer Modern Symbol
    "CMEX",      # Computer Modern Math Extension (dấu ngoặc lớn, ký hiệu tổng)
    # CMR bị loại bỏ: là font Roman chứ thường, dùng cho cả text lẫn số trong công thức
    # → giữ lại sẽ khiến toàn bộ text bằng font LaTeX bị gán nhãn là MATH (false positive cao)
    "MSAM",      # AMS Symbol A
    "MSBM",      # AMS Symbol B (blackboard bold: ℝ, ℕ, ℤ)
    "EUFM",      # Euler Fraktur Math
    "RSFS",      # Ralph Smith Formal Script
    "CMTI",      # Computer Modern Text Italic (dùng cho biến trong một số PDF)
    "Symbol",    # Symbol font (Windows)
    "MathJax",   # MathJax fonts trong PDF từ HTML
    "STIX",      # STIX fonts
    "MathTime",  # MathTime Professional
    "Euler",     # Euler math fonts
    "LMM",       # Latin Modern Math
    "DejaVuMath",# DejaVu Math
)

# Các dấu câu/ký hiệu được phép "pass-through" giữa 2 span toán liền kề
# (không cắt đứt nhóm toán chỉ vì có 1 dấu câu font text thường giữa 2 span math)
MATH_PUNCT_CHARS: frozenset[str] = frozenset("()[]{}.,;:+=-_/*^|\\<>!?~\u2019\u2018\u201c\u201d\u00b4`")

# Khoảng cách dọc tối đa (points) giữa 2 block MATH liên tiếp để được gộp thành 1 block
# (giải quyết lỗi hàng chục [Formula block #n] rời rạc trong 1 trang)
MATH_BLOCK_MERGE_GAP_PT = 14.0

# Font monospace — dấu hiệu block là pseudocode / algorithm / code
MONO_FONT_SUBSTRINGS: tuple[str, ...] = (
    "Courier", "CourierNew", "Typewriter", "Mono", "CMTypewriter", "CMTT",
    "LMMono", "Inconsolata", "SourceCode", "FiraMono", "RobotoMono",
    "DejaVuSansMono", "UbuntuMono",
)

# Ngưỡng tối thiểu số cột của bảng để gửi OCR LaTeX tabular (thay vì Markdown)
# Bảng có ít cột thường đơn giản → Markdown OK
# Bảng có nhiều cột hoặc cụm cột phức tạp → LaTeX tabular tốt hơn
TABLE_LATEX_MIN_COLS = 5

# Tỉ lệ dồn mối monospace span để xếp là ALGORITHM block
ALGORITHM_MONO_RATIO = 0.6

# Kích thước tối đa DPI cho math block crop
MATH_CROP_DPI = 200

# Tỉ lệ tối thiểu của math span để block được xếp là MATH (thay vì TEXT)
# Giảm xuống 0.75 (từ 0.85) để bắt được block toán có một vài nhãn text xết vào
MATH_BLOCK_RATIO = 0.75

# ─── Ký hiệu Unicode toán học ────────────────────────────────────────────────
# Ký hiệu Unicode toán học trong text (backup khi không có font info).
MATH_UNICODE_CHARS = set(
    "∑∂∇√≈≠≤≥±×÷∫∏∀∃∈∉⊂⊃∪∩→⇒⟨⟩‖αβγδεζηθλμπρστφψωΑΒΓΔΕΖΗΘΛΜΠΡΣΤΦΨΩ"
    "′″‴∞∝∼≃≅≡∓⊕⊗⊥∧∨¬⊢⊨⟹⟺∘∙·⁻¹²³⁴⁰½⅓"
)

# Ngưỡng tỉ lệ ký tự toán unicode trên tổng ký tự để fallback về Unicode detection.
MATH_CHAR_RATIO_THRESHOLD = 0.05  # nâng từ 0.03 lên 0.05 để giảm false positive

# Regex nhận diện số thứ tự phương trình ở cuối dòng: (1), (12), (A.3)
# Đây là dấu hiệu mạnh cho display math block.
IMPORT_RE_EQUATION_NUM = True  # dùng trong layout_detector, tránh import vòng tròn

# Tỉ lệ chiều rộng tối thiểu của block so với page width để là full-width.
FULL_WIDTH_RATIO = 0.65  # giảm từ 0.7 xuống 0.65 để bắt thêm tiêu đề section

# ─── Postprocessor ───────────────────────────────────────────────────────────
# Số trang cuối tính từ References section sẽ bị đánh dấu is_references=True.
REFERENCES_LOOKBACK_PAGES = 1

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"  # DEBUG | INFO | WARNING | ERROR
