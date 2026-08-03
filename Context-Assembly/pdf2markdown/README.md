# PDF → Markdown Pipeline với MinerU

Pipeline chuyển đổi toàn bộ file PDF trong thư mục `data/` sang Markdown,
tối ưu cho **RTX 2080 Ti (11GB VRAM)**.

## Cấu trúc thư mục

```
Context-Assembly/
├── data/                          ← PDF đầu vào
│   ├── DeepLearning.pdf           (12 MB — sách dài)
│   ├── Machine Learning Yearning.pdf (7 MB — sách dài)
│   └── *.pdf                      (file thường)
├── output/                        ← Markdown đầu ra
│   └── <tên_pdf>/
│       ├── <tên_pdf>.md
│       └── images/
└── pdf2markdown/
    ├── config.py                  ← Cấu hình pipeline
    ├── gpu_manager.py             ← Quản lý VRAM
    ├── pdf_chunker.py             ← Chia PDF sách dài
    ├── mineru_processor.py        ← Wrapper MinerU
    ├── run_pipeline.py            ← Entry point chính
    └── .tmp/                      ← Thư mục tạm (tự tạo/xóa)
```

## Cài đặt

### 1. Cài PyTorch với CUDA (RTX 2080 Ti dùng CUDA 11.8 hoặc 12.1)

```bash
# CUDA 11.8
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# CUDA 12.1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

### 2. Cài MinerU và dependencies

```bash
pip install -r pdf2markdown/requirements.txt
```

### 3. Tải model MinerU lần đầu

```bash
python -c "from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze; print('OK')"
```

Model (~5GB) sẽ tự tải về `~/.cache/huggingface/` lần đầu chạy.

## Chạy Pipeline

```bash
# Chạy toàn bộ (từ thư mục gốc Context-Assembly/)
python pdf2markdown/run_pipeline.py

# Chỉ liệt kê file, không xử lý
python pdf2markdown/run_pipeline.py --dry-run

# Bỏ qua file đã convert (tiếp tục từ chỗ dừng)
python pdf2markdown/run_pipeline.py --resume

# Chỉ xử lý 1 file cụ thể
python pdf2markdown/run_pipeline.py --file "DeepLearning.pdf"

# Debug mode (log chi tiết)
python pdf2markdown/run_pipeline.py --log-level DEBUG
```

## Xử lý Sách Dài (Chống tràn VRAM)

Pipeline tự động phát hiện và xử lý sách dài bằng **Chunked Processing**:

```
DeepLearning.pdf (12MB, ~800 trang)
    │
    ├── Chunk 001: trang   1– 30  → .tmp/DeepLearning/chunk_001_output/
    ├── Chunk 002: trang  31– 60  → .tmp/DeepLearning/chunk_002_output/
    ├── ...                         clear VRAM sau mỗi chunk
    └── Chunk 027: trang 781–800  → .tmp/DeepLearning/chunk_027_output/
    │
    └── Merge → output/DeepLearning/DeepLearning.md
```

**Ngưỡng phát hiện sách dài** (cấu hình trong `config.py`):
- File > 5 MB, hoặc
- File > 100 trang

## Cấu hình

Chỉnh trong `pdf2markdown/config.py`:

| Tham số | Mặc định | Mô tả |
|---------|----------|-------|
| `CHUNK_SIZE_PAGES` | `30` | Số trang mỗi chunk |
| `LARGE_BOOK_SIZE_MB` | `5.0` | Ngưỡng MB để coi là sách dài |
| `LARGE_BOOK_PAGES` | `100` | Ngưỡng số trang |
| `VRAM_CLEAR_DELAY` | `1.0` | Giây chờ sau clear VRAM |
| `MINERU_PARSE_METHOD` | `"auto"` | `"auto"` / `"ocr"` / `"txt"` |
| `OCR_LANGUAGES` | `["en","vi"]` | Ngôn ngữ OCR |

## Output

```
output/
└── DeepLearning/
    ├── DeepLearning.md     ← Markdown hoàn chỉnh
    └── images/
        ├── chunk001_image-0000.png
        ├── chunk001_image-0001.png
        └── ...
```

## Theo dõi Log

```bash
# Xem log realtime
Get-Content pdf2markdown/pipeline.log -Wait    # PowerShell
tail -f pdf2markdown/pipeline.log              # Linux/macOS
```

## Ước tính thời gian

| File | Kích thước | Ước tính |
|------|-----------|---------|
| Attention Mechanism | 0.9 MB | ~1-2 phút |
| Attention is all you need | 2.2 MB | ~2-3 phút |
| Machine Learning Yearning | 7.3 MB | ~15-25 phút |
| DeepLearning.pdf | 12.6 MB | ~25-40 phút |

> Thời gian phụ thuộc vào số trang và độ phức tạp layout.

## Troubleshooting

**CUDA Out of Memory:**
```python
# Trong config.py, giảm chunk size:
CHUNK_SIZE_PAGES = 15  # giảm từ 30 xuống 15
```

**Model không load được:**
```bash
# Kiểm tra internet và thử lại
python -c "import magic_pdf; print(magic_pdf.__version__)"
```

**PaddleOCR lỗi trên Windows:**
```bash
pip install paddlepaddle-gpu==2.6.1.post120 -f https://www.paddlepaddle.org.cn/whl/windows/mkl/avx/stable.html
```
