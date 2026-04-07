import os
import uuid
from typing import List, Literal, Any, Optional
from pydantic import BaseModel, Field

# LangChain Imports
from langchain_community.document_loaders import Docx2txtLoader, UnstructuredExcelLoader, TextLoader
from langchain_experimental.text_splitter import SemanticChunker
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_classic.retrievers import MultiVectorRetriever
from langchain_core.stores import InMemoryByteStore
from langchain_core.documents import Document

import fitz  # PyMuPDF
import base64
import json
import re
import unicodedata
import time
import random

try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except Exception:
    RecursiveCharacterTextSplitter = None

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

    for page_num in range(page_count):
        fitz_page = doc_fitz.load_page(page_num)
        pix = fitz_page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_bytes = pix.tobytes("png")
        img_base64 = base64.b64encode(img_bytes).decode("utf-8")

        vision_prompt = """
                You are an expert at analyzing document pages (text + layout + tables + diagrams).

                Task:
                1) Transcribe all visible text on the page into "page_ocr_text" (verbatim, keep line breaks as best as possible).
                2) Extract structured understanding of the page.

                Return ONLY a single valid JSON object (no Markdown, no ``` fences, no extra words) with this schema:
                {
                "slide_title": "string|null",
                "content_type": "diagram|table|text|mixed",
                "main_concepts": ["string"],
                "relationships": [{"from": "string", "to": "string", "relationship": "string"}],
                "key_terms": ["string"],
                "page_ocr_text": "string",
                "full_description": "string",
                "category": "skills_tech|case_study|presales|other"
                }

                Rules:
                - Do not omit small text inside boxes/tables.
                - If content is a flow/tree, describe parent → children explicitly in "full_description".
                - If unsure about a field, use null or empty list/string.
            """

        vision_text_raw = ""
        vision_text_clean = ""
        vision_obj: Optional[dict] = None
        try:
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if api_key:
                vision_llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0, api_key=api_key)
            else:
                vision_llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0)
            vision_msg = vision_llm.invoke(
                [
                    {"role": "user", "content": [
                        {"type": "text", "text": vision_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
                    ]}
                ]
            )
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

        extracted_best = vision_ocr_text
        if not extracted_best:
            extracted_best = _normalize_extracted_text(fitz_page.get_text("text") or "")

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
            You are an expert in classifying presales documents.
            Classify the following text into one of the three categories based on its main content:

            - skills_tech: skills, technology, solutions, approach tech stack mentioned in the text
            - case_study: specific projects, clients, issues, results achieved
            - presales: sales process, checklists, workflow for client engagement

            If the text does not belong to any of the above categories → return "other"
            Only return the correct category name, no explanations.
        """
    )
    title: str = Field(description="Short, human-readable title for this chunk/section (max 12 words)")
    tags: List[str] = Field(description="Important keywords (technology names, client names, business domains)")
    key_points: List[str] = Field(description="3-7 key points, each is a short sentence")
    summary: str = Field(description="1-3 sentence summary that is good for semantic search")

class KnowledgePipeline:
    def __init__(self, api_key: str):
        os.environ["GOOGLE_API_KEY"] = api_key
        self.llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite-preview", temperature=0)
        self.embeddings = _ThrottledEmbeddings(GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001"))
        
        self.vectorstore = Chroma(
            collection_name="presales_summaries",
            embedding_function=self.embeddings,
            persist_directory="./chroma_data"
        )
        
        self.store = InMemoryByteStore()
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
                    f"Analyze the following text:\n\n{chunk.page_content}"
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
        self.store.mset(list(zip(doc_ids, chunks)))
        
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
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GOOGLE_API_KEY (or GEMINI_API_KEY) in environment.")
    pipeline = KnowledgePipeline(api_key=api_key)
