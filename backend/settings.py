import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or str(default))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or str(default))
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


@dataclass(frozen=True)
class RagSettings:
    default_top_k: int
    max_top_k: int
    retrieval_fanout_multiplier: int
    retrieval_min_candidates: int
    max_distance: float
    relax_distance_delta: float
    relax_distance_cap: float
    overlap_weight: float


@dataclass(frozen=True)
class ChunkingSettings:
    chunk_size: int
    chunk_overlap: int


@dataclass(frozen=True)
class PdfHybridSettings:
    text_min_chars: int
    image_min_count: int
    max_vision_pages: int
    force_vision: bool
    sample_first_pages: int
    sample_force_vision: bool
    sample_disable_gain_ratio: float
    sample_enable_gain_ratio: float
    sample_text_min_chars_multiplier: float
    sample_struct_desc_min_chars: int
    mixed_image_text_min_chars: int
    mixed_image_text_multiplier: float
    img_area_ratio_icon_max: float
    img_area_ratio_large_min: float
    mixed_image_text_large_img_area_min: float
    drawings_min_count: int


@dataclass(frozen=True)
class AppSettings:
    rag: RagSettings
    chunking: ChunkingSettings
    pdf_hybrid: PdfHybridSettings


def get_settings() -> AppSettings:
    return AppSettings(
        rag=RagSettings(
            default_top_k=max(1, _env_int("RAG_DEFAULT_TOP_K", 4)),
            max_top_k=max(1, _env_int("RAG_MAX_TOP_K", 10)),
            retrieval_fanout_multiplier=max(1, _env_int("RAG_RETRIEVAL_FANOUT_MULTIPLIER", 10)),
            retrieval_min_candidates=max(1, _env_int("RAG_RETRIEVAL_MIN_CANDIDATES", 20)),
            max_distance=max(0.0, _env_float("RAG_MAX_DISTANCE", 0.75)),
            relax_distance_delta=max(0.0, _env_float("RAG_RELAX_DISTANCE_DELTA", 0.15)),
            relax_distance_cap=max(0.0, _env_float("RAG_RELAX_DISTANCE_CAP", 0.95)),
            overlap_weight=max(0.0, _env_float("RAG_OVERLAP_WEIGHT", 0.12)),
        ),
        chunking=ChunkingSettings(
            chunk_size=max(200, _env_int("RAG_CHUNK_SIZE", 2400)),
            chunk_overlap=max(0, _env_int("RAG_CHUNK_OVERLAP", 250)),
        ),
        pdf_hybrid=PdfHybridSettings(
            text_min_chars=max(0, _env_int("PDF_HYBRID_TEXT_MIN_CHARS", 450)),
            image_min_count=max(0, _env_int("PDF_HYBRID_IMAGE_MIN_COUNT", 1)),
            max_vision_pages=max(0, _env_int("PDF_HYBRID_MAX_VISION_PAGES", 10)),
            force_vision=_env_bool("PDF_HYBRID_FORCE_VISION", False),
            sample_first_pages=max(0, _env_int("PDF_HYBRID_SAMPLE_FIRST_PAGES", 2)),
            sample_force_vision=_env_bool("PDF_HYBRID_SAMPLE_FORCE_VISION", True),
            sample_disable_gain_ratio=_env_float("PDF_HYBRID_SAMPLE_DISABLE_GAIN_RATIO", 1.08),
            sample_enable_gain_ratio=_env_float("PDF_HYBRID_SAMPLE_ENABLE_GAIN_RATIO", 1.25),
            sample_text_min_chars_multiplier=max(1.0, _env_float("PDF_HYBRID_SAMPLE_TEXT_MIN_CHARS_MULTIPLIER", 1.5)),
            sample_struct_desc_min_chars=max(0, _env_int("PDF_HYBRID_SAMPLE_STRUCT_DESC_MIN_CHARS", 120)),
            mixed_image_text_min_chars=max(0, _env_int("PDF_HYBRID_MIXED_IMAGE_TEXT_MIN_CHARS", 1200)),
            mixed_image_text_multiplier=max(1.0, _env_float("PDF_HYBRID_MIXED_IMAGE_TEXT_MULTIPLIER", 3.0)),
            img_area_ratio_icon_max=max(0.0, min(_env_float("PDF_HYBRID_IMG_AREA_RATIO_ICON_MAX", 0.03), 1.0)),
            img_area_ratio_large_min=max(0.0, min(_env_float("PDF_HYBRID_IMG_AREA_RATIO_LARGE_MIN", 0.18), 1.0)),
            mixed_image_text_large_img_area_min=max(0.0, min(_env_float("PDF_HYBRID_MIXED_IMAGE_TEXT_LARGE_IMG_AREA_MIN", 0.18), 1.0)),
            drawings_min_count=max(0, _env_int("PDF_HYBRID_DRAWINGS_MIN_COUNT", 15)),
        ),
    )

