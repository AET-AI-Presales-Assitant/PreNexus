import os
import uuid
from typing import List, Literal, Any, Optional

from dotenv import load_dotenv, find_dotenv
from pydantic import BaseModel, Field

# LangChain Imports
from langchain_community.document_loaders import Docx2txtLoader, UnstructuredExcelLoader, TextLoader
from langchain_experimental.text_splitter import SemanticChunker
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_classic.retrievers import MultiVectorRetriever
from langchain_core.stores import InMemoryByteStore, ByteStore
from langchain_core.documents import Document

import fitz  # PyMuPDF
import base64
import json
import re
import unicodedata
import time
import random
from typing import Iterator, Sequence, Tuple

class LocalFileStore(ByteStore):
    def __init__(self, root_path: str):
        self.root_path = root_path
        os.makedirs(root_path, exist_ok=True)
        
    def mget(self, keys: Sequence[str]) -> List[Optional[bytes]]:
        results = []
        for k in keys:
            p = os.path.join(self.root_path, f"{k}.bin")
            if os.path.exists(p):
                with open(p, "rb") as f:
                    results.append(f.read())
            else:
                results.append(None)
        return results

    def mset(self, key_value_pairs: Sequence[Tuple[str, bytes]]) -> None:
        for k, v in key_value_pairs:
            p = os.path.join(self.root_path, f"{k}.bin")
            with open(p, "wb") as f:
                f.write(v)

    def mdelete(self, keys: Sequence[str]) -> None:
        for k in keys:
            p = os.path.join(self.root_path, f"{k}.bin")
            if os.path.exists(p):
                os.remove(p)

    def yield_keys(self, prefix: Optional[str] = None) -> Iterator[str]:
        if not os.path.exists(self.root_path):
            return
        for f in os.listdir(self.root_path):
            if f.endswith(".bin"):
                key = f[:-4]
                if prefix is None or key.startswith(prefix):
                    yield key

try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except Exception:
    RecursiveCharacterTextSplitter = None

load_dotenv(find_dotenv(usecwd=True) or "", override=False)

class _ThrottledEmbeddings:
    def __init__(self, inner, batch_size: int = 8, max_retries: int = 5, base_sleep_s: float = 1.0):
        self.inner = inner
        self.batch_size = max(1, int(batch_size))
        self.max_retries = max(0, int(max_retries))
        self.base_sleep_s = float(base_sleep_s)

    def _is_retryable(self, e: Exception) -> bool:
        msg = str(e or "")
        m = msg.lower()
        return ("resource_exhausted" in m) or ("429" in m) or ("rate limit" in m) or ("quota" in m)

    def _sleep(self, attempt: int):
        if self.base_sleep_s <= 0:
            return
        jitter = random.random() * 0.25
        time.sleep(self.base_sleep_s * (2 ** max(0, attempt - 1)) + jitter)

    def _call_with_retry(self, fn):
        last = None
        for attempt in range(0, self.max_retries + 1):
            try:
                return fn()
            except Exception as e:
                last = e
                if attempt >= self.max_retries or not self._is_retryable(e):
                    raise
                self._sleep(attempt + 1)
        raise last  # type: ignore[misc]

    def embed_documents(self, texts: List[str]):
        out = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            res = self._call_with_retry(lambda: self.inner.embed_documents(batch))
            out.extend(res)
        return out

    def embed_query(self, text: str):
        return self._call_with_retry(lambda: self.inner.embed_query(text))

def _coerce_vision_content_to_text(content: Any) -> str:
    """
    - If the content is a string → use it directly.
    - If the content is a list → combine all the text (or content) into a string.
    - If it's a dict/other type → convert it to string/json to avoid crashing.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if item is None:
                continue
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t)
                    continue
                c = item.get("content")
                if isinstance(c, str) and c.strip():
                    parts.append(c)
                    continue
                parts.append(json.dumps(item, ensure_ascii=False))
                continue
            parts.append(str(item))
        return "\n".join([p for p in parts if p])
    return str(content)

def _strip_code_fences(text: str) -> str:
    """
    Remove code fences (```...```) from the text.
    """
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()

def _extract_first_json_object(text: str) -> Optional[str]:
    s = text
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == "\"":
                in_str = False
            continue
        if ch == "\"":
            in_str = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None

def _try_parse_json(text: str) -> Optional[dict]:
    t = _strip_code_fences(text)
    json_text = _extract_first_json_object(t)
    if not json_text:
        return None
    try:
        obj = json.loads(json_text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None

def _normalize_extracted_text(text: str) -> str:
    """
    - Standardize newlines to \n
    - Merge broken words in the form of some-\nthing
    - Remove trailing spaces, reduce blank lines
    """
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def _to_ascii_hashtag(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return ""
    t = unicodedata.normalize("NFKD", t)
    t = t.encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-z0-9]+", "_", t)
    t = t.strip("_")
    return t

def process_pdf_complex(file_path: str, llm, max_pages: Optional[int] = None) -> List[Document]:
    """
    Complex PDF processing:
    1. Use PyMuPDF (fitz) to convert pages into images.
    2. Use Gemini Vision to OCR visible text and describe page structure.
    4. Combine the results into a single document.
    """
    docs = []
    doc_fitz = fitz.open(file_path)

    page_count = doc_fitz.page_count
    if max_pages is not None:
        page_count = min(page_count, max_pages)

    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)) or str(default))
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

    def _env_float(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, str(default)) or str(default))
        except Exception:
            return default

    text_min_chars = max(0, _env_int("PDF_HYBRID_TEXT_MIN_CHARS", 450))
    image_min_count = max(0, _env_int("PDF_HYBRID_IMAGE_MIN_COUNT", 1))
    max_vision_pages = max(0, _env_int("PDF_HYBRID_MAX_VISION_PAGES", 10))
    force_vision = _env_bool("PDF_HYBRID_FORCE_VISION", False)
    text_min_chars_text_dense = int(text_min_chars)
    text_min_chars_image_dense = int(text_min_chars)
    text_min_chars_mixed_image_text = int(text_min_chars)

    sample_first_pages = max(0, min(_env_int("PDF_HYBRID_SAMPLE_FIRST_PAGES", 2), page_count))
    sample_force_vision = _env_bool("PDF_HYBRID_SAMPLE_FORCE_VISION", True)
    sample_disable_gain = _env_float("PDF_HYBRID_SAMPLE_DISABLE_GAIN_RATIO", 1.08)
    sample_enable_gain = _env_float("PDF_HYBRID_SAMPLE_ENABLE_GAIN_RATIO", 1.25)
    sample_text_multiplier = _env_float("PDF_HYBRID_SAMPLE_TEXT_MIN_CHARS_MULTIPLIER", 1.5)
    sample_struct_desc_min = max(0, _env_int("PDF_HYBRID_SAMPLE_STRUCT_DESC_MIN_CHARS", 120))
    mixed_image_text_compact_min = max(0, _env_int("PDF_HYBRID_MIXED_IMAGE_TEXT_MIN_CHARS", 1200))
    mixed_image_text_multiplier = max(1.0, _env_float("PDF_HYBRID_MIXED_IMAGE_TEXT_MULTIPLIER", 3.0))
    img_area_ratio_icon_max = max(0.0, min(_env_float("PDF_HYBRID_IMG_AREA_RATIO_ICON_MAX", 0.03), 1.0))
    img_area_ratio_large_min = max(0.0, min(_env_float("PDF_HYBRID_IMG_AREA_RATIO_LARGE_MIN", 0.18), 1.0))
    mixed_image_text_large_img_area_min = max(0.0, min(_env_float("PDF_HYBRID_MIXED_IMAGE_TEXT_LARGE_IMG_AREA_MIN", img_area_ratio_large_min), 1.0))
    drawings_min_count = max(0, _env_int("PDF_HYBRID_DRAWINGS_MIN_COUNT", 15))

    vision_llm = None
    vision_pages_used = 0
    sample_stats = {
        "text_dense": {"seen": 0, "gain_sum": 0.0, "struct_hits": 0},
        "image_only": {"seen": 0, "gain_sum": 0.0, "struct_hits": 0},
        "mixed_image_text": {"seen": 0, "gain_sum": 0.0, "struct_hits": 0},
    }
    sample_adjusted = False

    for page_num in range(page_count):
        fitz_page = doc_fitz.load_page(page_num)
        text_raw = ""
        try:
            text_raw = fitz_page.get_text("text") or ""
        except Exception:
            text_raw = ""
        text_norm = _normalize_extracted_text(text_raw)
        text_compact_len = len(re.sub(r"\s+", "", text_norm))
        images_full = []
        img_area_ratio = 0.0
        try:
            images_full = fitz_page.get_images(full=True) or []
        except Exception:
            images_full = []
        img_count = len(images_full)
        drawings_count = 0
        try:
            drawings_count = len(fitz_page.get_drawings() or [])
        except Exception:
            drawings_count = 0
        if img_count > 0:
            try:
                page_area = float(fitz_page.rect.width) * float(fitz_page.rect.height)
            except Exception:
                page_area = 0.0
            if page_area > 0:
                area_sum = 0.0
                seen_xrefs = set()
                for img in images_full:
                    try:
                        xref = int(img[0])
                    except Exception:
                        continue
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    try:
                        rects = fitz_page.get_image_rects(xref) or []
                    except Exception:
                        rects = []
                    for r in rects:
                        try:
                            area_sum += abs(float(r.width) * float(r.height))
                        except Exception:
                            continue
                if area_sum > 0:
                    img_area_ratio = min(1.0, max(0.0, area_sum / page_area))

        in_sample = (page_num < sample_first_pages) and (not sample_adjusted)
        image_trigger = (img_count >= image_min_count) and (img_count > 0)
        has_visual = (img_count > 0) or (drawings_count >= drawings_min_count)
        mixed_cutoff = max(int(mixed_image_text_compact_min), int(float(text_min_chars_image_dense) * float(mixed_image_text_multiplier)))
        if img_count > 0 and img_area_ratio <= img_area_ratio_icon_max:
            page_group = "text_dense"
        elif img_count > 0 and text_compact_len >= mixed_cutoff:
            page_group = "mixed_image_text"
        elif img_count > 0:
            page_group = "image_only"
        else:
            page_group = "text_dense"

        if force_vision:
            use_vision = True
        else:
            if page_group == "image_only":
                use_vision = (text_compact_len < text_min_chars_image_dense) or (image_trigger and text_compact_len < (text_min_chars_image_dense * 2))
            elif page_group == "mixed_image_text":
                use_vision = (text_compact_len < text_min_chars_mixed_image_text) or (image_trigger and img_area_ratio >= mixed_image_text_large_img_area_min)
            else:
                use_vision = (text_compact_len < text_min_chars_text_dense)
        if use_vision and max_vision_pages == 0:
            use_vision = False
        if use_vision and vision_pages_used >= max_vision_pages:
            use_vision = False
        if (not force_vision) and in_sample and sample_force_vision and max_vision_pages > 0 and vision_pages_used < max_vision_pages:
            use_vision = True
        if has_visual:
            use_vision = True

        vision_prompt = """
            You are a document page vision extraction engine. Analyze the page visually.

            OUTPUT: Return ONLY one valid JSON object (no markdown, no code fences, no extra words) with schema:
            {
            "page_number": number,
            "slide_title": "string|null",
            "content_type": "diagram|table|text|mixed",
            "language": "vi|en|other",
            "main_concepts": ["string"],
            "key_terms": ["string"],
            "relationships": [{"from":"string","to":"string","relationship":"string"}],
            "page_ocr_text": "string",
            "full_description": "string",
            "category": "skills_tech|case_study|presales|other"
            }

            RULES:
            - page_ocr_text must be verbatim from the image; preserve line breaks as much as possible.
            - Do NOT invent missing words; if unreadable, write "[UNREADABLE]".
            - Do not omit small text inside tables/boxes.
            - If the page contains charts/diagrams, describe axes/units/values and the main takeaways in full_description.
            - If the page contains Vietnamese, set language="vi" and keep Vietnamese diacritics in OCR.
            - full_description: describe layout/sections and table headers; if flow/tree, write parent -> children explicitly.
            - If unsure: use null/empty list/empty string. Never output non-JSON.
        """

        vision_text_raw = ""
        vision_text_clean = ""
        vision_obj: Optional[dict] = None
        if use_vision:
            try:
                if vision_llm is None:
                    api_key = os.getenv("GEMINI_API_KEY")
                    if api_key:
                        vision_llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0, api_key=api_key)
                    else:
                        vision_llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0)

                pix = fitz_page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_bytes = pix.tobytes("png")
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                vision_msg = vision_llm.invoke(
                    [
                        {"role": "user", "content": [
                            {"type": "text", "text": vision_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
                        ]}
                    ]
                )
                vision_pages_used += 1
                vision_text_raw = _coerce_vision_content_to_text(vision_msg.content)
                vision_text_clean = _strip_code_fences(vision_text_raw)
                vision_obj = _try_parse_json(vision_text_clean)
            except Exception as e:
                print(f"Error occurred while calling Vision API on page {page_num + 1}: {e}")
                vision_text_raw = ""
                vision_text_clean = ""
                vision_obj = None

        vision_ocr_text = ""
        vision_full_description = ""
        vision_json_text = ""
        if vision_obj:
            vision_ocr_text = _normalize_extracted_text(str(vision_obj.get("page_ocr_text") or ""))
            vision_full_description = _normalize_extracted_text(str(vision_obj.get("full_description") or ""))
            vision_obj_storage = dict(vision_obj)
            vision_obj_storage.pop("page_ocr_text", None)
            vision_json_text = json.dumps(vision_obj_storage, ensure_ascii=False)

        if in_sample:
            if vision_ocr_text:
                base = max(1, text_compact_len)
                vlen = len(re.sub(r"\s+", "", vision_ocr_text))
                if vlen > 0:
                    sample_stats[page_group]["seen"] += 1
                    sample_stats[page_group]["gain_sum"] += (float(vlen) / float(base))
                    ctype = str((vision_obj or {}).get("content_type") or "").strip().lower()
                    if ctype in {"diagram", "table", "mixed"}:
                        sample_stats[page_group]["struct_hits"] += 1
                    elif vision_full_description and len(vision_full_description) >= sample_struct_desc_min:
                        sample_stats[page_group]["struct_hits"] += 1

            if (page_num + 1) >= sample_first_pages and (not sample_adjusted):
                totals_seen = int(sample_stats["text_dense"]["seen"]) + int(sample_stats["image_only"]["seen"]) + int(sample_stats["mixed_image_text"]["seen"])
                totals_struct = int(sample_stats["text_dense"]["struct_hits"]) + int(sample_stats["image_only"]["struct_hits"]) + int(sample_stats["mixed_image_text"]["struct_hits"])
                totals_gain_sum = float(sample_stats["text_dense"]["gain_sum"]) + float(sample_stats["image_only"]["gain_sum"]) + float(sample_stats["mixed_image_text"]["gain_sum"])
                if totals_seen > 0:
                    avg_gain_all = totals_gain_sum / float(totals_seen)
                    if (avg_gain_all <= sample_disable_gain) and (totals_struct == 0):
                        max_vision_pages = vision_pages_used

                for grp, v in sample_stats.items():
                    seen = int(v["seen"])
                    if seen <= 0:
                        continue
                    avg_gain = float(v["gain_sum"]) / float(seen)
                    struct_hits = int(v["struct_hits"])
                    if grp == "text_dense":
                        if (avg_gain <= sample_disable_gain) and (struct_hits == 0):
                            text_min_chars_text_dense = max(int(float(text_min_chars_text_dense) / max(1.0, float(sample_text_multiplier))), 50)
                        elif (avg_gain >= sample_enable_gain) or (struct_hits > 0):
                            text_min_chars_text_dense = min(int(float(text_min_chars_text_dense) * float(sample_text_multiplier)), 2000)
                    elif grp == "image_only":
                        if (avg_gain <= sample_disable_gain) and (struct_hits == 0):
                            text_min_chars_image_dense = max(int(float(text_min_chars_image_dense) / max(1.0, float(sample_text_multiplier))), 80)
                        elif (avg_gain >= sample_enable_gain) or (struct_hits > 0):
                            text_min_chars_image_dense = min(int(float(text_min_chars_image_dense) * float(sample_text_multiplier)), 2000)
                    else:
                        if (avg_gain <= sample_disable_gain) and (struct_hits == 0):
                            text_min_chars_mixed_image_text = max(int(float(text_min_chars_mixed_image_text) / max(1.0, float(sample_text_multiplier))), 120)
                sample_adjusted = True

        extracted_best = vision_ocr_text
        if not extracted_best:
            extracted_best = vision_full_description if has_visual else text_norm

        combined_content = f"--- PAGE {page_num + 1} ---\n\n"
        combined_content += f"[Extracted Text]:\n{extracted_best}\n\n"
        if vision_full_description:
            combined_content += f"[Vision Full Description]:\n{vision_full_description}\n\n"
        combined_content += "[Vision JSON]:\n"
        combined_content += f"{vision_json_text or vision_text_clean or vision_text_raw}\n"

        docs.append(Document(
            page_content=combined_content,
            metadata={"source": file_path, "page": page_num + 1}
        ))
    doc_fitz.close()
    return docs

# 1. Document Loader Factory
def load_file(file_path: str, llm=None) -> List[Document]:
    ext = os.path.splitext(file_path)[-1].lower()
    if ext == '.pdf':
        if llm is None:
            raise ValueError("Provide an LLM instance for complex PDF processing.")
        return process_pdf_complex(file_path, llm)
    elif ext == '.docx':
        loader = Docx2txtLoader(file_path)
    elif ext in ['.xlsx', '.xls']:
        loader = UnstructuredExcelLoader(file_path)
    elif ext == '.txt':
        loader = TextLoader(file_path, encoding='utf-8')
    else:
        raise ValueError(f"File format not supported: {ext}")
    return loader.load()

# 2. Schema định nghĩa metadata cho LLM trích xuất
class ChunkClassification(BaseModel):
    category: Literal["skills_tech", "case_study", "presales", "other"] = Field(
        description="""
            You are an expert at classifying and summarizing internal presales knowledge chunks.

            Choose category:
            - skills_tech: capabilities, tech stack, architecture, approaches, solutions.
            - case_study: specific projects/clients, problem, approach, outcomes, metrics.
            - presales: sales workflow, checklists, discovery questions, delivery process.
            - other: everything else.

            Rules:
            - Output ONLY the category value (no explanation).
            - If the chunk is Vietnamese, keep Vietnamese terms and diacritics.
            - Do not include secrets/PII in title/tags/summary; replace with "[REDACTED]".
        """
    )
    title: str = Field(description="Short, human-readable title for this chunk/section (max 12 words)")
    tags: List[str] = Field(description="Important keywords (technology names, client names, business domains)")
    key_points: List[str] = Field(description="3-7 key points, each is a short sentence")
    summary: str = Field(description="1-3 sentence summary that is good for semantic search")

class KnowledgePipeline:
    def __init__(self, api_key: str):
        os.environ["GEMINI_API_KEY"] = api_key
        self.llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0)
        self.embeddings = _ThrottledEmbeddings(GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001"))
        
        self.vectorstore = Chroma(
            collection_name="presales_summaries",
            embedding_function=self.embeddings,
            persist_directory="./chroma_data"
        )

        self.memory_store = Chroma(
            collection_name="conversation_memories",
            embedding_function=self.embeddings,
            persist_directory="./chroma_data"
        )
        
        self.store = LocalFileStore("./chroma_data/bytestore")
        self.id_key = "doc_id"
        
        self.retriever = MultiVectorRetriever(
            vectorstore=self.vectorstore,
            byte_store=self.store,
            id_key=self.id_key,
        )
        
        if RecursiveCharacterTextSplitter is not None:
            self.text_splitter = RecursiveCharacterTextSplitter(chunk_size=2400, chunk_overlap=250)
        else:
            self.text_splitter = SemanticChunker(self.embeddings, breakpoint_threshold_type="percentile")

    def process_and_ingest(self, file_path: str, role: str = "Employee") -> dict:
        print(f"1. Reading file: {file_path}...")
        docs = load_file(file_path, self.llm)
        
        # Combine all page contents into one full text for better semantic chunking.
        full_text = "\n\n".join([d.page_content for d in docs])
        
        print("2. Performing Chunking...")
        chunks = self.text_splitter.create_documents([full_text])
        print(f"   -> Successfully split into {len(chunks)} chunks.")
        
        print("3. Extracting Metadata & Generating Summary with LLM...")
        structured_llm = self.llm.with_structured_output(ChunkClassification)
        
        doc_ids = [str(uuid.uuid4()) for _ in chunks]
        created_at_ms = int(time.time() * 1000)
        summary_docs = []
        summary_ids = []
        errors = []
        
        for i, chunk in enumerate(chunks):
            try:
                analysis: ChunkClassification = structured_llm.invoke(
                    f"""Analyze the following text for internal knowledge base ingestion.
                    Rules:
                    - Follow the schema strictly.
                    - Do not include secrets/PII (API keys, passwords, tokens, personal emails/phones); replace with "[REDACTED]".

                    TEXT:
                    {chunk.page_content}"""
                )
                
                # Check if analysis is None or missing attributes
                if not analysis:
                    print(f"   ! LLM returned empty analysis for chunk {i+1}")
                    continue

                chunk.metadata = {
                    "source": file_path,
                    "category": analysis.category,
                    "tags": ", ".join(analysis.tags) if hasattr(analysis, "tags") else "",
                    "chunk_title": analysis.title if hasattr(analysis, "title") else "",
                    "role": role,
                    "createdAt": created_at_ms,
                    self.id_key: doc_ids[i]
                }

                tags = analysis.tags if hasattr(analysis, "tags") and isinstance(analysis.tags, list) else []
                tag_tokens = []
                for t in tags:
                    ht = _to_ascii_hashtag(str(t))
                    if ht:
                        tag_tokens.append(f"#{ht}")
                if analysis.category:
                    tag_tokens.append(f"#{_to_ascii_hashtag(str(analysis.category))}")
                hashtags = " ".join(dict.fromkeys(tag_tokens))

                key_points = analysis.key_points if hasattr(analysis, "key_points") and isinstance(analysis.key_points, list) else []
                key_points_text = "\n".join([f"- {str(p).strip()}" for p in key_points if str(p).strip()])

                chunk_title = analysis.title.strip() if hasattr(analysis, "title") and isinstance(analysis.title, str) else ""
                if not chunk_title:
                    chunk_title = os.path.basename(file_path)

                summary_text = analysis.summary.strip() if hasattr(analysis, "summary") and isinstance(analysis.summary, str) else ""
                if not summary_text:
                    summary_text = (chunk.page_content or "")[:400]

                display_content = f"{chunk_title}\n{hashtags}\n\n{summary_text}".strip()
                if key_points_text:
                    display_content += f"\n\nKey points:\n{key_points_text}"

                summary_doc = Document(
                    page_content=display_content,
                    metadata={
                        self.id_key: doc_ids[i],
                        "category": analysis.category,
                        "tags": ", ".join(tags),
                        "chunk_title": chunk_title,
                        "source": file_path,
                        "role": role,
                        "createdAt": created_at_ms
                    }
                )
                summary_docs.append(summary_doc)
                summary_ids.append(doc_ids[i])

            except Exception as e:
                print(f"   ! Error occurred while processing chunk {i+1}: {e}")
                errors.append(str(e))
                
        print("4. Saving to Multi-Vector Store (Chroma)...")
        # Lưu Full Text vào ByteStore
        self.retriever.docstore.mset(list(zip(doc_ids, chunks)))
        
        # Lưu Summary vào Vector DB (Chroma)
        if summary_docs:
            self.vectorstore.add_documents(summary_docs, ids=summary_ids)
            
        print("Complete Ingestion!\n")
        return {
            "file_path": file_path,
            "createdAt": created_at_ms,
            "num_chunks_total": len(chunks),
            "num_chunks_success": len(summary_ids),
            "num_summary_docs": len(summary_ids),
            "num_chunk_docs": 0,
            "vector_ids": list(summary_ids),
            "chunk_ids": [],
            "errors": errors[:10],
            "embedding_model": "models/gemini-embedding-001"
        }
        
    def query(self, question: str) -> List[Document]:
        """Search for relevant documents based on the question."""
        print(f"Searching for: '{question}'...")
        results = self.retriever.invoke(question)
        return results

if __name__ == "__main__":
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY/GOOGLE_API_KEY in environment.")
    pipeline = KnowledgePipeline(api_key=api_key)
