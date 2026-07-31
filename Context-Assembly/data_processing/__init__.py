"""
data_processing — Hybrid PDF → Markdown Pipeline

Modules:
    config          : Cấu hình tập trung (Ollama, DPI, VRAM, paths)
    models          : Dataclasses (DocumentBlock, PageResult, DocumentResult)
    layout_detector : Phân loại layout, phân đoạn block, sắp xếp Reading Order
    vision_client   : Ollama Qwen2-VL HTTP client (resize ảnh, retry)
    ocr_worker      : Worker OCR với Semaphore chống OOM
    page_processor  : Điều phối xử lý 1 trang
    postprocessor   : Sửa hyphenation, lọc header/footer, detect References
    pipeline        : Điều phối toàn bộ pipeline
    run             : CLI entry point
"""
