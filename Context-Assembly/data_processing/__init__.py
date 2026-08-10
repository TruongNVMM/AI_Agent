"""
data_processing — Hybrid PDF -> Markdown Pipeline (v2)

Modules:
    config          : Cau hinh tap trung (Ollama, DPI, VRAM, paths, heading/math font thresholds)
    models          : Dataclasses (DocumentBlock + heading_level/font_size, PageResult, DocumentResult)
    layout_detector : Gutter-analysis 2-col detection, font-based heading+math, Reading Order, crop
    text_extractor  : CPU processor: heading prefix, math-safe hyphenation, table Markdown
    markdown_utils  : Helper dinh dang Markdown (image tag, URL-encode safe paths)
    vision_client   : Ollama Qwen2-VL HTTP client (resize anh, retry, improved math prompt)
    ocr_worker      : Worker OCR voi Semaphore chong OOM
    page_processor  : Dieu phoi xu ly 1 trang (nhan gutter_x)
    postprocessor   : Sua hyphenation (math-aware), loc header/footer, font-based section map
    pipeline        : Per-page layout detection, dieu phoi toan bo pipeline
    run             : CLI entry point
"""
