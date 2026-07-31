# PDF → Markdown Hybrid Pipeline

Pipeline chuyển đổi PDF thành Markdown bằng cách **phân loại từng vùng nội dung** và dùng đúng công cụ cho từng loại:

| Loại block | Công cụ | Thiết bị |
|---|---|---|
| Text thuần | PyMuPDF `.get_text()` | CPU (< 0.001s/block) |
| Bảng biểu | PyMuPDF `.find_tables()` | CPU (< 0.01s/block) |
| Hình ảnh / Đồ thị | Ollama **Qwen2-VL 7B** | GPU RTX 2080 Ti |
| Công thức toán | Ollama **Qwen2-VL 7B** | GPU RTX 2080 Ti |

## Cài đặt

### 1. Cài Ollama

Tải từ [ollama.com](https://ollama.com) và cài đặt.

### 2. Pull model Qwen2-VL (QUAN TRỌNG: dùng bản q4_K_M)

```bash
# Model qwen2-vl:7b mặc định trên Ollama đã được quantized 4-bit (~4.5 GB VRAM)
ollama pull qwen2-vl:7b
```

### 3. Khởi động Ollama với cấu hình chống OOM

```bash
# Thiết lập biến môi trường TRƯỚC khi chạy ollama serve
set OLLAMA_FLASH_ATTENTION=1       # Tiết kiệm thêm ~40% VRAM KV cache
set OLLAMA_MAX_LOADED_MODELS=1     # Chỉ load 1 model — tránh double VRAM
set CUDA_VISIBLE_DEVICES=0         # Ghim vào GPU index 0

# Khởi động server
ollama serve
```

### 4. Cài Python dependencies (đã có sẵn trong môi trường)

```bash
pip install PyMuPDF Pillow requests
```

---

## Chạy pipeline

```bash
# Dry-run: chỉ text + bảng, không OCR (test nhanh, không cần Ollama)
python -m data_processing.run --skip-ocr

# Chạy 1 file nhỏ (test OCR)
python -m data_processing.run --file "GAN"

# Chạy tất cả 8 file PDF
python -m data_processing.run

# Tùy chỉnh đường dẫn
python -m data_processing.run --input ./data --output ./output --workers 2
```

---

## Cấu trúc thư mục

```
data_processing/
├── config.py          # Cấu hình tập trung (Ollama, DPI, thresholds)
├── models.py          # Dataclass: DocumentBlock, PageResult, DocumentResult
├── layout_detector.py # Phân loại layout, segment block, sort Reading Order
├── vision_client.py   # Ollama HTTP client (resize ảnh, retry, prompts)
├── ocr_worker.py      # Worker OCR với Semaphore chống OOM
├── page_processor.py  # Orchestrate 1 trang (segment → dispatch → reassemble)
├── postprocessor.py   # Sửa hyphenation, lọc header/footer, detect References
├── pipeline.py        # Pipeline chính (ProcessPoolExecutor cho nhiều file)
└── run.py             # CLI entry point
```

---

## Chiến lược chống OOM trên RTX 2080 Ti (11 GB VRAM)

### Budget VRAM ước tính

| Thành phần | VRAM |
|---|---|
| Model weights (q4_K_M) | ~4.5 GB |
| KV Cache (num_ctx=2048 + Flash Attention) | ~0.3 GB |
| Image tokens (ảnh ≤ 896px) | ~0.8 GB |
| CUDA runtime + OS overhead | ~0.5 GB |
| **Tổng** | **~6.1 GB** ✅ |

### Các điều chỉnh trong `config.py`

```python
QWEN2_VL_MODEL      = "qwen2-vl:7b-q4_K_M"  # INT4, không phải FP16
OLLAMA_OPTIONS = {
    "num_ctx":     2048,   # Giới hạn context (default là 4096 → tốn thêm 0.5 GB)
    "num_gpu":     -1,     # Offload tất cả layers lên GPU
    "temperature": 0.1,    # Ổn định output OCR
}
OCR_CONCURRENT_REQUESTS = 1   # Tuyệt đối KHÔNG gửi 2 request song song
OCR_MAX_IMAGE_SIZE      = 896 # px — giới hạn kích thước ảnh crop
```

### Nếu vẫn bị OOM

Chỉnh các thông số sau trong `config.py`:

```python
# Giảm ảnh nhỏ hơn (ít patch → ít VRAM)
OCR_MAX_IMAGE_SIZE = 672  # thay vì 896

# Hạ context length
OLLAMA_OPTIONS["num_ctx"] = 1024  # thay vì 2048

# Chỉ offload 28 trong 32 layers lên GPU (giữ lại ~1 GB VRAM)
OLLAMA_OPTIONS["num_gpu"] = 28  # thay vì -1
```

---

## Output

Sau khi chạy, thư mục `output/` chứa:

```
output/
├── Generative-Adversarial-Nets (GAN).md       # Markdown hoàn chỉnh
├── Generative-Adversarial-Nets (GAN)_metadata.json
├── Attention is all you need.md
├── ...
└── pipeline_summary.json   # Thống kê toàn bộ pipeline
```

### Format file Markdown

```markdown
---
title: "Generative-Adversarial-Nets (GAN)"
source: "Generative-Adversarial-Nets (GAN).pdf"
pages: 9
layout: "1-column"
---

<!-- page 1 -->

Generative Adversarial Nets
Ian J. Goodfellow, ...

Abstract
We propose a new framework...

<!-- page 3 -->

...

| Metric | MNIST | TFD |
|---|---|---|
| DBN | 138 ± 2 | 1909 ± 66 |

<!-- page 4 -->

> [Figure: Generator and discriminator architecture showing...]

$$ \min_G \max_D V(D,G) = \mathbb{E}_{x \sim p_{data}}[\log D(x)] + ... $$
```
