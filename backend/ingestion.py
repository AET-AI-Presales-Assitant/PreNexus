import os
import uuid
from typing import List, Literal, Any, Optional

from dotenv import load_dotenv, find_dotenv
from pydantic import BaseModel, Field

# LangChain Imports
from langchain_community.document_loaders import Docx2txtLoader, UnstructuredExcelLoader, TextLoader, UnstructuredPowerPointLoader
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_classic.retrievers import MultiVectorRetriever
from langchain_core.stores import ByteStore
from langchain_core.documents import Document

import fitz  # PyMuPDF
import base64
import json
import re
import unicodedata
import time
from typing import Iterator, Sequence, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_exception

from langchain_text_splitters import RecursiveCharacterTextSplitter
from .settings import get_settings
from .logger import get_logger, set_job_id, set_step

log = get_logger("ingestion")

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

load_dotenv(find_dotenv(usecwd=True) or "", override=False)

def _is_retryable_exception(e: Exception) -> bool:
    msg = str(e or "").lower()
    return ("resource_exhausted" in msg) or ("429" in msg) or ("rate limit" in msg) or ("quota" in msg)

class _ThrottledEmbeddings:
    def __init__(self, inner, batch_size: int = 8):
        self.inner = inner
        self.batch_size = max(1, int(batch_size))

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_exception),
        reraise=True
    )
    def _call_with_retry(self, fn):
        return fn()

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
    pdf_cfg = get_settings().pdf_hybrid

    text_min_chars = pdf_cfg.text_min_chars
    image_min_count = pdf_cfg.image_min_count
    max_vision_pages = pdf_cfg.max_vision_pages
    force_vision = pdf_cfg.force_vision
    drawings_min_count = pdf_cfg.drawings_min_count
    vision_pages_used = 0
    import concurrent.futures

    def _process_page(page_num: int):
        nonlocal vision_pages_used
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

        # Giả định luôn luôn dùng vision nếu thỏa mãn điều kiện cơ bản (bỏ qua logic sampling phức tạp cũ)
        image_trigger = (img_count >= image_min_count) and (img_count > 0)
        has_visual = (img_count > 0) or (drawings_count >= drawings_min_count)
        
        use_vision = False
        if force_vision or has_visual or (img_count > 0 and text_compact_len < text_min_chars):
            use_vision = True
            
        if use_vision and max_vision_pages == 0:
            use_vision = False

        vision_text_raw = ""
        vision_text_clean = ""
        vision_obj: Optional[dict] = None
        
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
        
        if use_vision:
            try:
                local_vision_llm = llm
                pix = fitz_page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_bytes = pix.tobytes("png")
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                @retry(
                    stop=stop_after_attempt(5),
                    wait=wait_exponential(multiplier=1, min=1, max=10),
                    retry=retry_if_exception(_is_retryable_exception),
                    reraise=True
                )
                def invoke_vision_summary():
                    return local_vision_llm.invoke(
                        [
                            {"role": "user", "content": [
                                {"type": "text", "text": vision_prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
                            ]}
                        ]
                    )

                vision_msg = invoke_vision_summary()
                vision_text_raw = _coerce_vision_content_to_text(vision_msg.content)
                vision_text_clean = _strip_code_fences(vision_text_raw)
                vision_obj = _try_parse_json(vision_text_clean)
            except Exception as e:
                set_step("vision")
                log.exception("vision_api_failed", extra={"page": page_num + 1})
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

        extracted_best = vision_ocr_text
        if not extracted_best:
            extracted_best = vision_full_description if has_visual else text_norm

        combined_content = f"--- PAGE {page_num + 1} ---\n\n"
        combined_content += f"[Extracted Text]:\n{extracted_best}\n\n"
        if vision_full_description:
            combined_content += f"[Vision Full Description]:\n{vision_full_description}\n\n"
        combined_content += "[Vision JSON]:\n"
        combined_content += f"{vision_json_text or vision_text_clean or vision_text_raw}\n"

        return Document(
            page_content=combined_content,
            metadata={"source": file_path, "page": page_num + 1}
        )

    # Chạy song song quá trình OCR các trang (tối đa 5-10 trang cùng lúc)
    MAX_CONCURRENT_PAGES = int(os.getenv("VISION_CONCURRENCY", "5"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_PAGES) as executor:
        future_to_page = {executor.submit(_process_page, page_num): page_num for page_num in range(page_count)}
        
        results = [None] * page_count
        for future in concurrent.futures.as_completed(future_to_page):
            page_num = future_to_page[future]
            try:
                doc = future.result()
                results[page_num] = doc
            except Exception as exc:
                log.exception("page_processing_failed", extra={"page": page_num, "error": str(exc)})
                
        # Lọc ra các trang hợp lệ và theo đúng thứ tự
        for doc in results:
            if doc is not None:
                docs.append(doc)
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
    elif ext == '.pptx':
        loader = UnstructuredPowerPointLoader(file_path)
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

class BatchContextualChunkClassification(BaseModel):
    results: List[ChunkClassification] = Field(description="A list of classifications, exactly matching the order and number of the input chunks.")



class KnowledgePipeline:
    def __init__(self, api_key: str):
        settings = get_settings()
        os.environ["GEMINI_API_KEY"] = api_key
        self.llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0)
        self.embeddings = _ThrottledEmbeddings(GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001"))

        persist_dir = (os.getenv("CHROMA_PERSIST_DIR") or "").strip()
        if not persist_dir:
            persist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "chroma_data"))
        os.makedirs(persist_dir, exist_ok=True)

        self.vectorstore = Chroma(
            collection_name="presales_summaries",
            embedding_function=self.embeddings,
            persist_directory=persist_dir,
        )

        self.memory_store = Chroma(
            collection_name="conversation_memories",
            embedding_function=self.embeddings,
            persist_directory=persist_dir,
        )

        self.store = LocalFileStore(os.path.join(persist_dir, "bytestore"))
        self.id_key = "doc_id"
        
        self.retriever = MultiVectorRetriever(
            vectorstore=self.vectorstore,
            byte_store=self.store,
            id_key=self.id_key,
        )
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunking.chunk_size,
            chunk_overlap=settings.chunking.chunk_overlap,
        )

    def process_and_ingest(self, file_path: str, role: str = "Employee", job_id: Optional[str] = None) -> dict:
        if job_id:
            set_job_id(str(job_id))
        set_step("read_file")
        log.info("ingest_read_file", extra={"file_path": file_path, "role": role})
        docs = load_file(file_path, self.llm)
        
        # Lấy nội dung xem trước để tạo Document Summary (không lưu toàn bộ văn bản vào một biến lớn)
        preview_text = ""
        preview_chars_collected = 0
        for d in docs:
            if preview_chars_collected >= 30000:
                break
            content_len = len(d.page_content)
            preview_text += d.page_content + "\n\n"
            preview_chars_collected += content_len
        
        set_step("chunking")
        log.info("ingest_chunking_start")
        # Thay vì truyền chuỗi lớn `full_text`, truyền thẳng danh sách các Document để tối ưu bộ nhớ
        chunks = self.text_splitter.split_documents(docs)
        log.info("ingest_chunking_done", extra={"num_chunks_total": len(chunks)})
        
        set_step("document_summary")
        log.info("ingest_document_summary_start")
        document_summary = ""
        try:
            summary_preview = preview_text[:10000]
            if summary_preview.strip():
                @retry(
                    stop=stop_after_attempt(5),
                    wait=wait_exponential(multiplier=1, min=1, max=10),
                    retry=retry_if_exception(_is_retryable_exception),
                    reraise=True
                )
                def invoke_doc_summary():
                    doc_summary_prompt = f"""You are an expert summarizer. Please read the following beginning of a document and provide a concise 1-2 sentence overall summary of what this document is about.
                    Do not include secrets/PII. 
                    
                    DOCUMENT PREVIEW:
                    {summary_preview}
                    """
                    return self.llm.invoke(doc_summary_prompt)

                doc_summary_response = invoke_doc_summary()
                document_summary = str(doc_summary_response.content).strip()
                log.info("ingest_document_summary_done", extra={"summary": document_summary})
                
                # CHÚ Ý: KHÔNG Gắn Ngữ cảnh Toàn cục vào đầu mỗi chunk ở đây.
                # Việc gắn vào đây sẽ khiến prompt bị nhiễu, LLM sẽ lặp lại cùng một câu trả lời cho các chunk.
        except Exception as e:
            log.warning("ingest_document_summary_failed", extra={"error": str(e)})
        
        set_step("metadata_llm")
        log.info("ingest_metadata_llm_start")
        structured_llm = self.llm.with_structured_output(BatchContextualChunkClassification)
        
        doc_ids = [str(uuid.uuid4()) for _ in chunks]
        created_at_ms = int(time.time() * 1000)
        summary_docs = []
        summary_ids = []
        errors = []
        
        batch_size = 20
        
        @retry(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception(_is_retryable_exception),
            reraise=True
        )
        def invoke_batch_classification(prompt_text):
            return structured_llm.invoke(prompt_text)
        
        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i:i + batch_size]
            batch_doc_ids = doc_ids[i:i + batch_size]
            try:
                set_step("metadata_llm_batch")
                
                batch_text = ""
                for j, chunk in enumerate(batch_chunks):
                    batch_text += f"--- CHUNK {j} ---\n{chunk.page_content}\n\n"
                
                # Cung cấp bối cảnh gốc dựa trên preview_text thay vì full_text để tránh tràn RAM
                document_context_full = preview_text[:30000]
                
                prompt_text = f"""Analyze the following chunks of text for internal knowledge base ingestion.
                    
                    You are given the full document as context to understand what these chunks mean in the bigger picture.
                    
                    FULL DOCUMENT CONTEXT (or beginning part):
                    {document_context_full}
                    
                    ---
                    
                    Rules:
                    - Follow the schema strictly. Return a list of classifications exactly matching the number of chunks ({len(batch_chunks)}).
                    - Order of the results MUST match the order of the input chunks.
                    - Do not include secrets/PII (API keys, passwords, tokens, personal emails/phones); replace with "[REDACTED]".
                    - The 'summary' field MUST be specific to the unique content of THIS specific chunk.
                    - Explain how this specific information relates to the document context, DO NOT just summarize the whole document again.
                    - CRITICAL: DO NOT return the same summary for different chunks. Each chunk must have its own distinct summary based on its content.

                    CHUNKS TO ANALYZE:
                    {batch_text}"""
                
                analysis_batch: BatchContextualChunkClassification = invoke_batch_classification(prompt_text)
                
                if not analysis_batch or not hasattr(analysis_batch, "results") or not analysis_batch.results:
                    log.warning("ingest_llm_empty_analysis_batch", extra={"batch_start_index": i})
                    continue

                for j, chunk in enumerate(batch_chunks):
                    if j >= len(analysis_batch.results):
                        log.warning("ingest_llm_missing_results_in_batch", extra={"batch_start_index": i, "chunk_index_in_batch": j})
                        break
                        
                    analysis = analysis_batch.results[j]
                    doc_id = batch_doc_ids[j]

                    chunk.metadata = {
                        "source": file_path,
                        "category": analysis.category,
                        "tags": ", ".join(analysis.tags) if hasattr(analysis, "tags") else "",
                        "chunk_title": analysis.title if hasattr(analysis, "title") else "",
                        "role": role,
                        "createdAt": created_at_ms,
                        self.id_key: doc_id
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

                    display_content = ""
                    if document_summary:
                        display_content += f"[Document Context: {document_summary}]\n\n"
                    display_content += f"{chunk_title}\n{hashtags}\n\n{summary_text}".strip()
                    if key_points_text:
                        display_content += f"\n\nKey points:\n{key_points_text}"

                    summary_doc = Document(
                        page_content=display_content,
                        metadata={
                            self.id_key: doc_id,
                            "category": analysis.category,
                            "tags": ", ".join(tags),
                            "chunk_title": chunk_title,
                            "source": file_path,
                            "role": role,
                            "createdAt": created_at_ms
                        }
                    )
                    summary_docs.append(summary_doc)
                    summary_ids.append(doc_id)

            except Exception as e:
                log.exception("ingest_batch_failed", extra={"batch_start_index": i})
                errors.append(str(e))

        # Chỉ gắn Ngữ cảnh Toàn cục vào đầu các chunk SAU KHI đã chạy xong LLM metadata 
        # (Để lưu vào ByteStore và trả về trong Document Viewer)
        if document_summary:
            for c in chunks:
                if not c.page_content.startswith("[Document Context:"):
                    c.page_content = f"[Document Context: {document_summary}]\n\n{c.page_content}"

        set_step("save_chroma")
        log.info("ingest_save_chroma_start")
        # Lưu Full Text vào ByteStore
        self.retriever.docstore.mset(list(zip(doc_ids, chunks)))
        
        # Lưu Summary vào Vector DB (Chroma)
        if summary_docs:
            self.vectorstore.add_documents(summary_docs, ids=summary_ids)
            
        set_step("done")
        log.info("ingest_done", extra={"num_chunks_total": len(chunks), "num_chunks_success": len(summary_ids)})
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
        set_step("query")
        log.info("retriever_query", extra={"question": question})
        results = self.retriever.invoke(question)
        return results

if __name__ == "__main__":
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY/GOOGLE_API_KEY in environment.")
    pipeline = KnowledgePipeline(api_key=api_key)
