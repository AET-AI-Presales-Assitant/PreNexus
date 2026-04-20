import os
import shutil
import threading
import asyncio
from typing import List, Optional
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Request
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc, inspect, text
from pydantic import BaseModel
from datetime import datetime, timedelta
import time
import uuid
import json
import traceback
import queue

from .database import engine, get_db
from . import models
from .settings import get_settings
from .logger import configure_logging, get_logger, new_request_id, set_job_id, set_request_id, set_session_id, set_step
from .agents.common import detect_language, i18n, normalize_for_match, role_level, tokenize

# Import pipeline
from .ingestion import KnowledgePipeline
from .agents.chat_workflow import stream_chat_sse, stream_error_sse

load_dotenv()

configure_logging(os.getenv("LOG_LEVEL", "INFO"))
log = get_logger("main")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline_lock = threading.Lock()
pipeline_init_error = None
pipeline = None

ingest_queue = queue.Queue()

def _ingest_worker():
    while True:
        job_id = ingest_queue.get()
        if job_id is None:
            break
        try:
            _run_ingest_job(job_id)
        except Exception as e:
            log.exception("ingest_worker_error", extra={"error": str(e)})
        finally:
            ingest_queue.task_done()

# Khởi tạo 4 workers xử lý song song
NUM_WORKERS = int(os.getenv("INGEST_NUM_WORKERS", "4"))
for _ in range(NUM_WORKERS):
    threading.Thread(target=_ingest_worker, daemon=True).start()

def _run_ingest_job(job_id: str):
    set_job_id(job_id)
    set_step("ingest_job_run")
    db_local = next(get_db())
    try:
        j = db_local.query(models.IngestJob).filter(models.IngestJob.id == job_id).first()
        if not j:
            return
        j.status = "processing"
        j.started_at = datetime.utcnow()
        j.error = None
        j.errors_json = None
        j.vector_ids_json = None
        j.chunk_ids_json = None
        j.num_chunks_total = None
        j.num_chunks_success = None
        j.num_summary_docs = None
        j.num_chunk_docs = None
        j.num_embeddings = None
        j.embedding_model = None
        db_local.commit()

        if not _init_pipeline_if_needed(force=False):
            raise RuntimeError(f"Pipeline not initialized: {pipeline_init_error or 'Unknown initialization error'}")

        get_logger("ingest").info("ingest_job_start", extra={"job_id": job_id, "file_path": j.file_path, "role": j.role})
        result = pipeline.process_and_ingest(j.file_path, j.role, job_id=str(job_id))
        vector_ids = result.get("vector_ids") if isinstance(result, dict) else []
        chunk_ids = result.get("chunk_ids") if isinstance(result, dict) else []
        errors = result.get("errors") if isinstance(result, dict) else []

        j.status = "success"
        j.finished_at = datetime.utcnow()
        j.num_chunks_total = int(result.get("num_chunks_total") or 0) if isinstance(result, dict) else None
        j.num_chunks_success = int(result.get("num_chunks_success") or 0) if isinstance(result, dict) else None
        j.num_summary_docs = int(result.get("num_summary_docs") or 0) if isinstance(result, dict) else None
        j.num_chunk_docs = int(result.get("num_chunk_docs") or 0) if isinstance(result, dict) else None
        j.num_embeddings = (j.num_summary_docs or 0) + (j.num_chunk_docs or 0)
        j.embedding_model = str(result.get("embedding_model") or "") if isinstance(result, dict) else None
        j.vector_ids_json = json.dumps(vector_ids or [])
        j.chunk_ids_json = json.dumps(chunk_ids or [])
        j.errors_json = json.dumps(errors or [])
        db_local.commit()
        get_logger("ingest").info("ingest_job_success", extra={"job_id": job_id, "num_chunks_total": j.num_chunks_total, "num_chunks_success": j.num_chunks_success, "num_embeddings": j.num_embeddings})
        
        # Dọn dẹp file vật lý sau khi xử lý thành công
        try:
            if os.path.exists(j.file_path):
                os.remove(j.file_path)
                get_logger("ingest").info("ingest_job_cleanup_success", extra={"job_id": job_id, "file_path": j.file_path})
        except Exception as cleanup_err:
            get_logger("ingest").warning("ingest_job_cleanup_failed", extra={"job_id": job_id, "file_path": j.file_path, "error": str(cleanup_err)})

    except Exception as e:
        get_logger("ingest").exception("ingest_job_failed", extra={"job_id": job_id})
        try:
            j = db_local.query(models.IngestJob).filter(models.IngestJob.id == job_id).first()
            if j:
                j.status = "error"
                j.finished_at = datetime.utcnow()
                j.error = f"{type(e).__name__}: {e}"
                j.errors_json = json.dumps([
                    {"pipeline_none": pipeline is None, "pipeline_init_error": pipeline_init_error},
                    traceback.format_exc(limit=12),
                ], ensure_ascii=False)
                db_local.commit()
        except Exception:
            pass
    finally:
        db_local.close()

def _get_api_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()

def _refresh_env_from_dotenv():
    try:
        p = find_dotenv(usecwd=True) or ""
        load_dotenv(p, override=False)
    except Exception:
        pass

def _init_pipeline_if_needed(force: bool = False):
    global pipeline, pipeline_init_error
    with pipeline_lock:
        if pipeline is not None and not force:
            return pipeline
        _refresh_env_from_dotenv()
        api_key = _get_api_key()
        if not api_key:
            pipeline = None
            pipeline_init_error = "Missing GEMINI_API_KEY/GOOGLE_API_KEY. Set it in environment or .env and restart backend."
            return None
        try:
            pipeline = KnowledgePipeline(api_key=api_key)
            pipeline_init_error = None
            return pipeline
        except Exception as e:
            pipeline = None
            pipeline_init_error = f"{type(e).__name__}: {e}"
            log.warning("pipeline_init_failed", extra={"error": pipeline_init_error})
            return None

# Seed Admin User
def seed_admin(db: Session):
    admin = db.query(models.User).filter(models.User.username == "admin").first()
    if not admin:
        new_admin = models.User(
            username="admin",
            password="admin123",
            role="SuperManager",
            name="System Admin"
        )
        db.add(new_admin)
        db.commit()
        log.info("admin_seeded", extra={"username": "admin"})
        return
    if admin.role != "SuperManager":
        admin.role = "SuperManager"
        db.commit()

@app.on_event("startup")
def startup_event():
    models.Base.metadata.create_all(bind=engine)
    db = next(get_db())
    seed_admin(db)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    rid = (request.headers.get("x-request-id") or request.headers.get("x-request_id") or "").strip() or new_request_id()
    set_request_id(rid)
    set_session_id(None)
    set_job_id(None)
    set_step(None)

    started = time.time()
    http_log = get_logger("http")
    http_log.info("request_start", extra={"method": request.method, "path": request.url.path})
    resp = None
    try:
        resp = await call_next(request)
        resp.headers["X-Request-ID"] = rid
        return resp
    except Exception:
        http_log.exception("request_error", extra={"method": request.method, "path": request.url.path})
        raise
    finally:
        dur_ms = int((time.time() - started) * 1000)
        status_code = getattr(resp, "status_code", None) if resp is not None else None
        http_log.info("request_end", extra={"method": request.method, "path": request.url.path, "status_code": status_code, "duration_ms": dur_ms})

# --- Pydantic Schemas ---
class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    name: str

class SessionCreateRequest(BaseModel):
    userId: str
    title: Optional[str] = 'New Conversation'

class MessageCreateRequest(BaseModel):
    sessionId: str
    role: str
    content: str

class SessionUpdateRequest(BaseModel):
    title: str

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    userId: Optional[str] = None
    userRole: Optional[str] = None
    sessionId: Optional[str] = None
    topK: int = 4
    history: Optional[List[ChatMessage]] = None

class AnalyzeGapsRequest(BaseModel):
    queries: List[str]

class GapAnalysisInterest(BaseModel):
    topic: str
    reason: str

class GapAnalysisGap(BaseModel):
    question: str
    suggestion: str

class GapAnalysisResponse(BaseModel):
    topInterests: List[GapAnalysisInterest]
    knowledgeGaps: List[GapAnalysisGap]

class FeedbackCreateRequest(BaseModel):
    userId: str
    sessionId: str
    messageId: str
    kind: str
    value: Optional[int] = None
    note: Optional[str] = None
    citations: Optional[list] = None
    metadata: Optional[dict] = None

class AdminUserCreateRequest(BaseModel):
    username: str
    password: str
    name: str
    role: str

class AdminUserUpdateRequest(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None

# --- Endpoints ---

def to_dict(obj):
    if not obj:
        return None
    d = {}
    for attr in inspect(obj).mapper.column_attrs:
        val = getattr(obj, attr.key)
        if isinstance(val, datetime):
            d[attr.key] = val.isoformat()
        elif isinstance(val, uuid.UUID):
            d[attr.key] = str(val)
        else:
            d[attr.key] = val
    
    # Map snake_case database columns back to camelCase for frontend
    if 'created_at' in d:
        d['createdAt'] = d.pop('created_at')
    if 'user_id' in d:
        d['userId'] = d.pop('user_id')
    if 'session_id' in d:
        d['sessionId'] = d.pop('session_id')
    if 'parent_job_id' in d:
        d['parentJobId'] = d.pop('parent_job_id')
    if 'file_name' in d:
        d['fileName'] = d.pop('file_name')
    if 'file_path' in d:
        d['filePath'] = d.pop('file_path')
    if 'started_at' in d:
        d['startedAt'] = d.pop('started_at')
    if 'finished_at' in d:
        d['finishedAt'] = d.pop('finished_at')
    if 'rolled_back_at' in d:
        d['rolledBackAt'] = d.pop('rolled_back_at')
    if 'num_chunks_total' in d:
        d['numChunksTotal'] = d.pop('num_chunks_total')
    if 'num_chunks_success' in d:
        d['numChunksSuccess'] = d.pop('num_chunks_success')
    if 'num_summary_docs' in d:
        d['numSummaryDocs'] = d.pop('num_summary_docs')
    if 'num_chunk_docs' in d:
        d['numChunkDocs'] = d.pop('num_chunk_docs')
    if 'num_embeddings' in d:
        d['numEmbeddings'] = d.pop('num_embeddings')
    if 'embedding_model' in d:
        d['embeddingModel'] = d.pop('embedding_model')
    if 'errors_json' in d:
        d['errors'] = d.pop('errors_json')
    if 'vector_ids_json' in d:
        d['vectorIds'] = d.pop('vector_ids_json')
    if 'chunk_ids_json' in d:
        d['chunkIds'] = d.pop('chunk_ids_json')
    if 'citations_json' in d:
        d['citations'] = d.pop('citations_json')
    if 'used_docs_json' in d:
        d['usedDocs'] = d.pop('used_docs_json')
    return d

def _safe_json_load(s: str):
    try:
        return json.loads(s) if isinstance(s, str) and s.strip() else None
    except Exception:
        return None

def ingest_job_to_dict(job: models.IngestJob):
    d = to_dict(job) or {}
    d["errors"] = _safe_json_load(d.get("errors")) or []
    d["vectorIds"] = _safe_json_load(d.get("vectorIds")) or []
    d["chunkIds"] = _safe_json_load(d.get("chunkIds")) or []
    return d

def message_to_dict(msg: models.Message):
    d = to_dict(msg) or {}
    d["citations"] = _safe_json_load(d.get("citations")) or []
    d["usedDocs"] = _safe_json_load(d.get("usedDocs")) or []
    return d


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        x = float(a[i])
        y = float(b[i])
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


def _jaccard_tokens(a: List[str], b: List[str]) -> float:
    sa = set(a or [])
    sb = set(b or [])
    if not sa and not sb:
        return 0.0
    inter = len(sa.intersection(sb))
    uni = len(sa.union(sb))
    return float(inter) / float(uni) if uni > 0 else 0.0


def _find_cached_answer(db: Session, query: str, lang: str, user_role: str, pipeline_obj: Optional[KnowledgePipeline]):
    enabled = str(os.getenv("ANSWER_CACHE_ENABLED", "1") or "1").strip().lower() not in {"0", "false", "no", "off"}
    if not enabled:
        return None

    q = (query or "").strip()
    if not q:
        return None

    q_norm = normalize_for_match(q)
    q_tokens = tokenize(q)
    role_lvl = role_level(user_role)
    no_data_norm = normalize_for_match((i18n(lang or "vi") or {}).get("no_internal_data") or "")

    allowed_roles = []
    for r in ["Employee", "Lead", "Manager", "SuperManager"]:
        if role_lvl >= role_level(r):
            allowed_roles.append(r)

    max_age_days = int(float(os.getenv("ANSWER_CACHE_MAX_AGE_DAYS", "90") or "90"))
    cutoff = datetime.min if max_age_days <= 0 else (datetime.utcnow() - timedelta(days=max_age_days))

    best = None
    best_score = 0.0
    best_method = ""

    if q_norm:
        exacts = (
            db.query(models.CachedAnswer)
            .filter(models.CachedAnswer.lang == (lang or "vi"))
            .filter(models.CachedAnswer.query_norm == q_norm)
            .filter(models.CachedAnswer.min_role.in_(allowed_roles))
            .filter(models.CachedAnswer.created_at >= cutoff)
            .order_by(models.CachedAnswer.created_at.desc())
            .all()
        )
        if exacts:
            best = exacts[0]
            best_score = 1.0
            best_method = "exact"
            ans_text = str(getattr(best, "answer_text", "") or "")
            if no_data_norm and normalize_for_match(ans_text) == no_data_norm:
                return None
            return {"cache": best, "score": best_score, "method": best_method}

    candidate_limit = int(float(os.getenv("ANSWER_CACHE_CANDIDATE_LIMIT", "400") or "400"))
    candidates = (
        db.query(models.CachedAnswer)
        .filter(models.CachedAnswer.lang == (lang or "vi"))
        .filter(models.CachedAnswer.min_role.in_(allowed_roles))
        .filter(models.CachedAnswer.created_at >= cutoff)
        .order_by(models.CachedAnswer.created_at.desc())
        .limit(max(50, min(candidate_limit, 2000)))
        .all()
    )

    emb_query = None
    if pipeline_obj is not None:
        try:
            emb_query = pipeline_obj.embeddings.embed_query(q)
        except Exception:
            emb_query = None

    min_cos = float(os.getenv("ANSWER_CACHE_MIN_COS", "0.88") or "0.88")
    min_jacc = float(os.getenv("ANSWER_CACHE_MIN_JACCARD", "0.78") or "0.78")

    for c in candidates:
        c_norm = str(getattr(c, "query_norm", "") or "")
        if emb_query is not None:
            emb_json = getattr(c, "query_embedding_json", None)
            if isinstance(emb_json, str) and emb_json.strip():
                try:
                    emb_c = json.loads(emb_json)
                    if isinstance(emb_c, list) and emb_c:
                        s = _cosine_similarity(emb_query, emb_c)
                        if s >= min_cos and s > best_score:
                            best = c
                            best_score = s
                            best_method = "cosine"
                except Exception:
                    pass

        c_tokens = tokenize(str(getattr(c, "query_text", "") or "")) if getattr(c, "query_text", None) else tokenize(c_norm)
        s2 = _jaccard_tokens(q_tokens, c_tokens)
        if s2 >= min_jacc and s2 > best_score:
            best = c
            best_score = s2
            best_method = "jaccard"

    if best is None:
        return None
    ans_text = str(getattr(best, "answer_text", "") or "")
    if no_data_norm and normalize_for_match(ans_text) == no_data_norm:
        return None
    return {"cache": best, "score": best_score, "method": best_method}

@app.post("/api/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    try:
        set_step("login")
        user = db.query(models.User).filter(
            models.User.username == req.username,
            models.User.password == req.password
        ).first()
        if user:
            user_dict = to_dict(user)
            user_dict.pop('password', None)
            return {"success": True, "user": user_dict}
        else:
            # Instead of throwing HTTPException, return success: False as the frontend expects this JSON structure
            return {"success": False, "message": "Invalid credentials"}
    except Exception as e:
        get_logger("auth").exception("login_failed", extra={"username": req.username})
        return {"success": False, "message": "Internal Server Error"}

@app.post("/api/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    try:
        set_step("register")
        existing = db.query(models.User).filter(models.User.username == req.username).first()
        if existing:
            return {"success": False, "message": "Username already exists"}
        
        new_user = models.User(
            username=req.username,
            password=req.password,
            name=req.name,
            role="Employee"
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        user_dict = to_dict(new_user)
        user_dict.pop('password', None)
        return {"success": True, "user": user_dict}
    except Exception as e:
        get_logger("auth").exception("register_failed", extra={"username": req.username})
        return {"success": False, "message": "Internal Server Error"}

@app.get("/api/sessions")
def get_sessions(userId: str, db: Session = Depends(get_db)):
    try:
        set_step("get_sessions")
        set_session_id(None)
        sessions = db.query(models.Session).filter(models.Session.user_id == userId).order_by(desc(models.Session.created_at)).all()
        return {"success": True, "sessions": [to_dict(s) for s in sessions]}
    except Exception as e:
        get_logger("sessions").exception("get_sessions_failed", extra={"userId": userId})
        return {"success": False, "message": str(e)}

@app.post("/api/sessions")
def create_session(req: SessionCreateRequest, db: Session = Depends(get_db)):
    set_step("create_session")
    new_session = models.Session(
        user_id=req.userId,
        title=req.title
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return {"success": True, "session": to_dict(new_session)}

@app.get("/api/sessions/{session_id}/messages")
def get_messages(session_id: str, db: Session = Depends(get_db)):
    set_step("get_messages")
    set_session_id(session_id)
    try:
        try:
            uuid.UUID(session_id)
        except ValueError:
            return {"success": False, "error": "Invalid session ID format", "messages": []}

        messages = db.query(models.Message).filter(models.Message.session_id == session_id).order_by(models.Message.created_at).all()
        
        msg_ids = [m.id for m in messages]
        feedbacks = db.query(models.Feedback).filter(
            models.Feedback.message_id.in_(msg_ids),
            models.Feedback.kind == "thumbs"
        ).order_by(models.Feedback.created_at.asc()).all()
        
        thumb_map = {str(f.message_id): int(f.value) for f in feedbacks if f.value is not None}
        
        res_msgs = []
        for m in messages:
            md = message_to_dict(m)
            if str(m.id) in thumb_map:
                md["thumb"] = thumb_map[str(m.id)]
            res_msgs.append(md)

        return {"success": True, "messages": res_msgs}
    except Exception as e:
        log.error(f"Error get_messages: {e}")
        return {"success": False, "messages": []}

@app.post("/api/messages")
def create_message(req: MessageCreateRequest, db: Session = Depends(get_db)):
    set_step("create_message")
    set_session_id(req.sessionId)
    new_msg = models.Message(
        session_id=req.sessionId,
        role=req.role,
        content=req.content
    )
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)
    return {"success": True, "message": message_to_dict(new_msg)}

@app.post("/api/feedback")
def create_feedback(req: FeedbackCreateRequest, db: Session = Depends(get_db)):
    try:
        set_step("create_feedback")
        set_session_id(req.sessionId)
        fb = models.Feedback(
            user_id=req.userId,
            session_id=req.sessionId,
            message_id=req.messageId,
            kind=(req.kind or "thumbs"),
            value=req.value,
            note=req.note,
            citations_json=json.dumps(req.citations, ensure_ascii=False) if req.citations is not None else None,
            metadata_json=json.dumps(req.metadata, ensure_ascii=False) if req.metadata is not None else None,
        )
        db.add(fb)
        db.commit()
        kind = str(req.kind or "thumbs")
        if kind == "thumbs" and int(req.value or 0) == 1:
            cached_id = None
            if isinstance(req.metadata, dict):
                cached_id = req.metadata.get("cachedAnswerId") or req.metadata.get("cacheId")
            if cached_id:
                cid = None
                try:
                    cid = uuid.UUID(str(cached_id))
                except Exception:
                    cid = str(cached_id)
                ca = db.query(models.CachedAnswer).filter(models.CachedAnswer.id == cid).first()
                if ca:
                    ca.use_count = int(getattr(ca, "use_count", 0) or 0) + 1
                    ca.last_used_at = datetime.utcnow()
                    db.commit()
            else:
                require_citations = str(os.getenv("ANSWER_CACHE_REQUIRE_CITATIONS", "1") or "1").strip().lower() not in {"0", "false", "no", "off"}
                has_citations = False
                if isinstance(req.metadata, dict) and req.metadata.get("hasCitations") is True:
                    has_citations = True
                if isinstance(req.citations, list) and len(req.citations) > 0:
                    has_citations = True
                if (not require_citations) or has_citations:
                    agent_msg = db.query(models.Message).filter(models.Message.id == req.messageId).first()
                    if agent_msg and agent_msg.session_id:
                        prev_user = (
                            db.query(models.Message)
                            .filter(models.Message.session_id == agent_msg.session_id)
                            .filter(models.Message.role == "user")
                            .filter(models.Message.created_at <= agent_msg.created_at)
                            .order_by(models.Message.created_at.desc())
                            .first()
                        )
                        query_text = (prev_user.content or "").strip() if prev_user else ""
                        if query_text:
                            user_role = _get_user_role(db, req.userId, "Employee")
                            lang = detect_language(query_text)
                            q_norm = normalize_for_match(query_text)
                            emb_json = None
                            p = _init_pipeline_if_needed(force=False)
                            if p is not None:
                                try:
                                    emb = p.embeddings.embed_query(query_text)
                                    emb_json = json.dumps(emb)
                                except Exception:
                                    emb_json = None

                            db.query(models.CachedAnswer).filter(models.CachedAnswer.lang == lang).filter(models.CachedAnswer.query_norm == q_norm).filter(models.CachedAnswer.min_role == user_role).delete(synchronize_session=False)
                            existing = db.query(models.CachedAnswer).filter(models.CachedAnswer.message_id == req.messageId).first()
                            if existing is None:
                                ca = models.CachedAnswer(
                                    query_text=query_text,
                                    query_norm=q_norm,
                                    query_embedding_json=emb_json,
                                    answer_text=agent_msg.content or "",
                                    citations_json=getattr(agent_msg, "citations_json", None),
                                    used_docs_json=getattr(agent_msg, "used_docs_json", None),
                                    lang=lang,
                                    min_role=user_role,
                                    message_id=req.messageId,
                                    last_used_at=datetime.utcnow(),
                                    use_count=1,
                                )
                                db.add(ca)
                            db.commit()
        if kind == "thumbs" and int(req.value or 0) == -1:
            cached_id = None
            if isinstance(req.metadata, dict):
                cached_id = req.metadata.get("cachedAnswerId") or req.metadata.get("cacheId")
            if cached_id:
                cid = None
                try:
                    cid = uuid.UUID(str(cached_id))
                except Exception:
                    cid = str(cached_id)
                db.query(models.CachedAnswer).filter(models.CachedAnswer.id == cid).delete(synchronize_session=False)
                db.commit()
            else:
                db.query(models.CachedAnswer).filter(models.CachedAnswer.message_id == req.messageId).delete(synchronize_session=False)
                db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        get_logger("feedback").exception("create_feedback_failed", extra={"userId": req.userId, "sessionId": req.sessionId, "messageId": req.messageId, "kind": req.kind})
        return {"success": False, "message": str(e)}

def _role_level(role: str) -> int:
    r = (role or "").strip()
    if r.lower() == "admin":
        r = "SuperManager"
    levels = {"Employee": 1, "Lead": 2, "Manager": 3, "SuperManager": 4}
    return levels.get(r, 0)

def _normalize_role_value(role: Optional[str]) -> Optional[str]:
    if role is None:
        return None
    r = str(role).strip()
    if not r:
        return None
    rl = r.lower().replace("_", "").replace(" ", "")
    if rl == "admin" or rl == "supermanager" or rl == "supermanager":
        return "SuperManager"
    if rl == "employee":
        return "Employee"
    if rl == "lead":
        return "Lead"
    if rl == "manager":
        return "Manager"
    return None

def _get_user_role(db: Session, user_id: Optional[str], fallback_role: str) -> str:
    if user_id:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if user and user.role:
            return _normalize_role_value(user.role) or user.role
    return _normalize_role_value(fallback_role) or fallback_role

@app.post("/api/chat")
async def chat(req: ChatRequest, db: Session = Depends(get_db)):
    set_step("chat")
    set_session_id(str(req.sessionId) if getattr(req, "sessionId", None) else None)
    query = (req.message or "").strip()
    if not query:
        return StreamingResponse(
            stream_error_sse("Decomposition", "Empty message", "Empty message"),
            media_type="text/event-stream"
        )

    user_role = _get_user_role(db, req.userId, req.userRole or "Employee")
    lang = detect_language(query)
    rag_cfg = get_settings().rag
    top_k = max(1, min(int(req.topK or rag_cfg.default_top_k), rag_cfg.max_top_k))
    get_logger("chat").info("chat_request", extra={"userId": req.userId, "sessionId": req.sessionId, "userRole": user_role, "topK": top_k})

    def _build_cached_stream(answer_text: str, citations: list, used_docs: list, agent_message_id: Optional[str], cache_id: str):
        async def _gen_cached():
            def _yield_event(event_type: str, data: dict):
                payload = {"type": event_type, **(data or {})}
                return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            yield _yield_event("trace", {"step": "Decomposition", "details": "QA: cache hit." if lang == "en" else "QA: dùng kết quả từ cache.", "status": "success"})
            yield _yield_event("trace", {"step": "Delegation", "details": "Skipped retrieval (cache)." if lang == "en" else "Bỏ qua retrieval (cache).", "status": "success"})
            yield _yield_event("trace", {"step": "Synthesis", "details": "Skipped synthesis (cache)." if lang == "en" else "Bỏ qua synthesis (cache).", "status": "success"})
            yield _yield_event("answer_start", {})
            yield _yield_event("chunk", {"content": answer_text or ""})
            yield _yield_event("done", {"citations": citations or [], "used_docs": used_docs or [], "answer": answer_text or "", "agentMessageId": agent_message_id, "cacheHit": True, "cacheId": cache_id})

        return _gen_cached()

    pre_hit = None
    try:
        pre_hit = _find_cached_answer(db, query, lang, user_role, None)
    except Exception:
        pre_hit = None
    if pre_hit and pre_hit.get("cache"):
        ca = pre_hit["cache"]
        citations = []
        used_docs = []
        try:
            if isinstance(getattr(ca, "citations_json", None), str) and ca.citations_json:
                citations = json.loads(ca.citations_json) or []
            if isinstance(getattr(ca, "used_docs_json", None), str) and ca.used_docs_json:
                used_docs = json.loads(ca.used_docs_json) or []
        except Exception:
            pass
        agent_message_id = None
        try:
            if getattr(req, "sessionId", None):
                new_msg = models.Message(
                    session_id=req.sessionId, 
                    role="agent", 
                    content=getattr(ca, "answer_text", "") or "",
                    citations_json=getattr(ca, "citations_json", None),
                    used_docs_json=getattr(ca, "used_docs_json", None)
                )
                db.add(new_msg)
                db.commit()
                db.refresh(new_msg)
                agent_message_id = str(new_msg.id)
        except Exception:
            db.rollback()
        try:
            ca.use_count = int(getattr(ca, "use_count", 0) or 0) + 1
            ca.last_used_at = datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
        return StreamingResponse(_build_cached_stream(getattr(ca, "answer_text", "") or "", citations, used_docs, agent_message_id, str(getattr(ca, "id"))), media_type="text/event-stream")

    async def _gen():
        def _yield_event(event_type: str, data: dict):
            payload = {"type": event_type, **(data or {})}
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        yield _yield_event("trace", {"step": "Decomposition", "details": "Đang khởi tạo pipeline..." if lang == "vi" else "Initializing pipeline...", "status": "pending"})
        ok = await asyncio.to_thread(_init_pipeline_if_needed, False)
        if not ok:
            err = pipeline_init_error or "Unknown initialization error"
            yield _yield_event("trace", {"step": "Decomposition", "details": f"Pipeline not initialized: {err}" if lang == "en" else f"Lỗi khởi tạo pipeline: {err}", "status": "error"})
            yield _yield_event("error", {"message": f"Pipeline not initialized: {err}"})
            yield _yield_event("done", {"citations": [], "used_docs": [], "answer": "", "agentMessageId": None})
            return

        try:
            db_local = next(get_db())
            try:
                hit = _find_cached_answer(db_local, query, lang, user_role, pipeline)
                if hit and hit.get("cache"):
                    ca = hit["cache"]
                    citations = []
                    used_docs = []
                    try:
                        if isinstance(getattr(ca, "citations_json", None), str) and ca.citations_json:
                            citations = json.loads(ca.citations_json) or []
                        if isinstance(getattr(ca, "used_docs_json", None), str) and ca.used_docs_json:
                            used_docs = json.loads(ca.used_docs_json) or []
                    except Exception:
                        pass
                    agent_message_id = None
                    try:
                        if getattr(req, "sessionId", None):
                            new_msg = models.Message(
                                session_id=req.sessionId, 
                                role="agent", 
                                content=getattr(ca, "answer_text", "") or "",
                                citations_json=getattr(ca, "citations_json", None),
                                used_docs_json=getattr(ca, "used_docs_json", None)
                            )
                            db_local.add(new_msg)
                            db_local.commit()
                            db_local.refresh(new_msg)
                            agent_message_id = str(new_msg.id)
                    except Exception:
                        db_local.rollback()
                    try:
                        ca.use_count = int(getattr(ca, "use_count", 0) or 0) + 1
                        ca.last_used_at = datetime.utcnow()
                        db_local.commit()
                    except Exception:
                        db_local.rollback()
                    yield _yield_event("trace", {"step": "Decomposition", "details": "QA: pipeline ready." if lang == "en" else "QA: pipeline sẵn sàng.", "status": "success"})
                    yield _yield_event("trace", {"step": "Delegation", "details": "Skipped retrieval (cache)." if lang == "en" else "Bỏ qua retrieval (cache).", "status": "success"})
                    yield _yield_event("trace", {"step": "Synthesis", "details": "Skipped synthesis (cache)." if lang == "en" else "Bỏ qua synthesis (cache).", "status": "success"})
                    yield _yield_event("answer_start", {})
                    yield _yield_event("chunk", {"content": getattr(ca, "answer_text", "") or ""})
                    yield _yield_event("done", {"citations": citations or [], "used_docs": used_docs or [], "answer": getattr(ca, "answer_text", "") or "", "agentMessageId": agent_message_id, "cacheHit": True, "cacheId": str(getattr(ca, "id"))})
                    return
            finally:
                db_local.close()
        except Exception:
            pass

        yield _yield_event("trace", {"step": "Decomposition", "details": "QA: pipeline ready." if lang == "en" else "QA: pipeline sẵn sàng.", "status": "success"})
        async for item in stream_chat_sse(pipeline, req, user_role, top_k):
            yield item

    return StreamingResponse(_gen(), media_type="text/event-stream")

@app.post("/api/admin/analyze_gaps")
def analyze_gaps(req: AnalyzeGapsRequest):
    if not _init_pipeline_if_needed(force=False):
        err = pipeline_init_error or "Unknown initialization error"
        return {"success": False, "message": f"Pipeline not initialized: {err}", "error": err}
    queries = req.queries[:100]
    prompt = f"""
        You are an AI analyst for a Presales Knowledge Base. Analyze the following user queries to provide insights for the admin.
        
        USER QUERIES:
        {chr(10).join(queries)}

        Rules:
        - topInterests: max 3 items.
        - knowledgeGaps: 2-3 items.
        - reason/suggestion must be short and actionable.
        - Do not include secrets/PII if the queries contain sensitive info.
    """
    try:
        structured_llm = pipeline.llm.with_structured_output(GapAnalysisResponse)
        analysis: GapAnalysisResponse = structured_llm.invoke(prompt)
        
        # Chuyển đổi về JSON string để Frontend có thể parse như trước
        result_json = analysis.model_dump_json()
        
        return {"success": True, "result": result_json}
    except Exception as e:
        return {"success": False, "message": "Error analyzing gaps", "error": str(e)}

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    try:
        set_step("delete_session")
        set_session_id(session_id)
        try:
            db.execute(text("DELETE FROM followup_contexts WHERE session_id = :sid"), {"sid": session_id})
        except Exception:
            db.rollback()
        db.query(models.Feedback).filter(models.Feedback.session_id == session_id).delete(synchronize_session=False)
        db.query(models.SessionMemory).filter(models.SessionMemory.session_id == session_id).delete(synchronize_session=False)
        db.query(models.UserMemory).filter(models.UserMemory.session_id == session_id).delete(synchronize_session=False)
        msg_rows = db.query(models.Message.id).filter(models.Message.session_id == session_id).all()
        msg_ids = [r[0] for r in msg_rows if r and r[0]]
        if msg_ids:
            db.query(models.CachedAnswer).filter(models.CachedAnswer.message_id.in_(msg_ids)).delete(synchronize_session=False)
        db.query(models.Message).filter(models.Message.session_id == session_id).delete()
        db.query(models.Session).filter(models.Session.id == session_id).delete()
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}

@app.put("/api/sessions/{session_id}")
def update_session(session_id: str, req: SessionUpdateRequest, db: Session = Depends(get_db)):
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if session:
        session.title = req.title
        db.commit()
        db.refresh(session)
        return {"success": True, "session": to_dict(session)}
    raise HTTPException(status_code=404, detail="Session not found")

@app.get("/api/admin/users")
def get_admin_users(db: Session = Depends(get_db)):
    users = db.query(models.User).order_by(desc(models.User.created_at)).all()
    safe_users = []
    for u in users:
        u_dict = to_dict(u)
        u_dict.pop('password', None)
        if isinstance(u_dict.get("role"), str):
            u_dict["role"] = _normalize_role_value(u_dict["role"]) or u_dict["role"]
        safe_users.append(u_dict)
    return {"success": True, "users": safe_users}

@app.post("/api/admin/users")
def admin_create_user(req: AdminUserCreateRequest, db: Session = Depends(get_db)):
    role = _normalize_role_value(req.role)
    if not role:
        return {"success": False, "message": "Invalid role"}
    existing = db.query(models.User).filter(models.User.username == req.username).first()
    if existing:
        return {"success": False, "message": "Username already exists"}
    u = models.User(username=req.username, password=req.password, name=req.name, role=role)
    db.add(u)
    db.commit()
    db.refresh(u)
    u_dict = to_dict(u)
    u_dict.pop("password", None)
    return {"success": True, "user": u_dict}

@app.put("/api/admin/users/{user_id}")
def admin_update_user(user_id: str, req: AdminUserUpdateRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        return {"success": False, "message": "User not found"}
    if isinstance(req.name, str) and req.name.strip():
        user.name = req.name.strip()
    if isinstance(req.password, str) and req.password.strip():
        user.password = req.password
    if req.role is not None:
        role = _normalize_role_value(req.role)
        if not role:
            return {"success": False, "message": "Invalid role"}
        user.role = role
    db.commit()
    db.refresh(user)
    u_dict = to_dict(user)
    u_dict.pop("password", None)
    return {"success": True, "user": u_dict}

@app.get("/api/admin/analytics")
def get_admin_analytics(db: Session = Depends(get_db)):
    results = db.query(models.Message, models.Session, models.User).join(
        models.Session, models.Message.session_id == models.Session.id
    ).join(
        models.User, models.Session.user_id == models.User.id
    ).order_by(models.Message.created_at).all()

    feedbacks = db.query(models.Feedback).all()
    feedback_map = {str(f.message_id): f for f in feedbacks}

    message_map = {}
    for msg, sess, usr in results:
        if sess.id not in message_map:
            message_map[sess.id] = []
        message_map[sess.id].append({
            "id": str(msg.id),
            "role": msg.role,
            "content": msg.content,
            "createdAt": msg.created_at.isoformat(),
            "userName": usr.name,
            "userRole": usr.role,
            "sessionTitle": sess.title,
            "sessionId": str(sess.id)
        })

    queries = []
    for sess_id, msgs in message_map.items():
        for i in range(len(msgs)):
            msg = msgs[i]
            if msg["role"] == "user":
                answer_content = None
                feedback_value = None
                feedback_note = None
                if i + 1 < len(msgs) and msgs[i+1]["role"] == "agent":
                    ans_msg = msgs[i+1]
                    answer_content = ans_msg["content"]
                    ans_id = ans_msg["id"]
                    if ans_id in feedback_map:
                        fb = feedback_map[ans_id]
                        feedback_value = fb.value
                        feedback_note = fb.note
                
                queries.append({
                    "id": msg["id"],
                    "content": msg["content"],
                    "createdAt": msg["createdAt"],
                    "userName": msg["userName"],
                    "userRole": msg["userRole"],
                    "sessionTitle": msg["sessionTitle"],
                    "answerContent": answer_content,
                    "feedbackValue": feedback_value,
                    "feedbackNote": feedback_note
                })

    queries.sort(key=lambda x: x["createdAt"], reverse=True)
    return {"success": True, "queries": queries}

MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

@app.post("/api/admin/import")
async def import_data(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    role: str = Form("Employee"),
    db: Session = Depends(get_db),
):
    if not file:
        raise HTTPException(status_code=400, detail={"success": False, "message": "No file uploaded"})

    # Kiểm tra kích thước file
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    
    if file_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413, 
            detail={"success": False, "message": f"File size exceeds the limit of {MAX_FILE_SIZE_MB}MB"}
        )

    if not _init_pipeline_if_needed(force=False):
        err = pipeline_init_error or "Unknown initialization error"
        return {"success": False, "message": f"Pipeline not initialized: {err}", "error": err}
    
    upload_dir = (os.getenv("UPLOADS_DIR") or "").strip()
    if not upload_dir:
        upload_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))
    os.makedirs(upload_dir, exist_ok=True)
    
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    job = models.IngestJob(file_name=file.filename, file_path=file_path, role=role, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)

    ingest_queue.put(str(job.id))
    return {"success": True, "job": ingest_job_to_dict(job)}

@app.get("/api/files/{file_name}")
def get_uploaded_file(file_name: str):
    safe_name = os.path.basename(file_name or "")
    if not safe_name:
        return {"success": False, "message": "Invalid file name"}
    if not safe_name.lower().endswith(".pdf"):
        return {"success": False, "message": "Only PDF files are supported"}
    upload_dir = (os.getenv("UPLOADS_DIR") or "").strip()
    if not upload_dir:
        upload_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))
    file_path = os.path.join(upload_dir, safe_name)
    if not os.path.exists(file_path):
        return {"success": False, "message": "File not found"}
    headers = {"Content-Disposition": f'inline; filename=\"{safe_name}\"'}
    return FileResponse(file_path, media_type="application/pdf", headers=headers)

@app.get("/api/admin/ingest_jobs")
def list_ingest_jobs(limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(models.IngestJob).order_by(desc(models.IngestJob.created_at)).limit(max(1, min(limit, 200)))
    return {"success": True, "jobs": [ingest_job_to_dict(j) for j in q.all()]}

@app.get("/api/admin/ingest_jobs/{job_id}")
def get_ingest_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.IngestJob).filter(models.IngestJob.id == job_id).first()
    if not job:
        return {"success": False, "message": "Job not found"}
    return {"success": True, "job": ingest_job_to_dict(job)}

@app.post("/api/admin/ingest_jobs/{job_id}/retry")
def retry_ingest_job(job_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    job = db.query(models.IngestJob).filter(models.IngestJob.id == job_id).first()
    if not job:
        return {"success": False, "message": "Job not found"}
    new_job = models.IngestJob(
        parent_job_id=job.id,
        file_name=job.file_name,
        file_path=job.file_path,
        role=job.role,
        status="queued"
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    ingest_queue.put(str(new_job.id))
    return {"success": True, "job": ingest_job_to_dict(new_job)}

@app.post("/api/admin/ingest_jobs/{job_id}/rollback")
def rollback_ingest_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.IngestJob).filter(models.IngestJob.id == job_id).first()
    if not job:
        return {"success": False, "message": "Job not found"}
    if job.status not in ["success", "error"]:
        return {"success": False, "message": "Job is not eligible for rollback"}
    if job.rolled_back_at is not None:
        return {"success": False, "message": "Job already rolled back"}
    vector_ids = _safe_json_load(job.vector_ids_json) or []
    chunk_ids = _safe_json_load(job.chunk_ids_json) or []
    if not _init_pipeline_if_needed(force=False):
        err = pipeline_init_error or "Unknown initialization error"
        return {"success": False, "message": f"Pipeline not initialized: {err}", "error": err}
    try:
        if vector_ids:
            pipeline.vectorstore.delete(ids=list(vector_ids))
        if chunk_ids and hasattr(pipeline, "retriever") and hasattr(pipeline.retriever, "docstore"):
            pipeline.retriever.docstore.mdelete(list(chunk_ids))
            
        # Dọn dẹp file vật lý khi rollback (nếu file vẫn còn sót lại do job thất bại giữa chừng)
        try:
            if os.path.exists(job.file_path):
                os.remove(job.file_path)
                get_logger("ingest").info("ingest_job_rollback_cleanup_success", extra={"job_id": job_id, "file_path": job.file_path})
        except Exception as cleanup_err:
            get_logger("ingest").warning("ingest_job_rollback_cleanup_failed", extra={"job_id": job_id, "file_path": job.file_path, "error": str(cleanup_err)})
            
        job.status = "rolled_back"
        job.rolled_back_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
        return {"success": True, "job": ingest_job_to_dict(job)}
    except Exception as e:
        return {"success": False, "message": "Rollback failed", "error": str(e)}

@app.get("/api/admin/documents")
def get_documents():
    if not _init_pipeline_if_needed(force=False):
        err = pipeline_init_error or "Unknown initialization error"
        return {"success": False, "message": f"Pipeline not initialized: {err}", "error": err}
    try:
        set_step("admin_documents_list")
        docs = None
        try:
            docs = pipeline.vectorstore.get(include=["documents", "metadatas", "embeddings"])
        except Exception:
            pass
        if docs is None:
            try:
                docs = pipeline.vectorstore._collection.get(include=["documents", "metadatas", "embeddings"])
            except Exception:
                docs = pipeline.vectorstore.get()
        documents = []
        ids = docs.get("ids") if docs and docs.get("ids") is not None else []
        metadatas = docs.get("metadatas") if docs and docs.get("metadatas") is not None else []
        contents = docs.get("documents") if docs and docs.get("documents") is not None else []
        embeddings = docs.get("embeddings") if docs and docs.get("embeddings") is not None else []

        if len(ids) > 0:
            for i in range(len(ids)):
                doc_id = ids[i]
                metadata = metadatas[i] if i < len(metadatas) else {}
                content = contents[i] if i < len(contents) else ""
                embedding = embeddings[i] if i < len(embeddings) else None
                if embedding is not None and hasattr(embedding, "tolist"):
                    embedding = embedding.tolist()
                
                src = metadata.get("source", "") or ""
                src_name = src.split("/")[-1].split("\\")[-1] if src else ""
                tags_raw = metadata.get("tags", "") or ""
                tags = [t.strip() for t in str(tags_raw).split(",") if str(t).strip()]

                documents.append({
                    "id": doc_id,
                    "title": metadata.get("chunk_title") or metadata.get("source", "Unknown Document").split("/")[-1].split("\\")[-1],
                    "content": content,
                    "role": _normalize_role_value(metadata.get("role")) or "Employee",
                    "topic": metadata.get("category", "General"),
                    "createdAt": metadata.get("createdAt"),
                    "source": src_name,
                    "tags": tags,
                    "embedding": embedding,
                })
        return {"success": True, "documents": documents}
    except Exception as e:
        get_logger("admin.documents").exception("documents_list_failed")
        return {"success": False, "message": "Error getting documents", "error": str(e)}

@app.delete("/api/admin/documents/{doc_id}")
def delete_document(doc_id: str):
    if not _init_pipeline_if_needed(force=False):
        err = pipeline_init_error or "Unknown initialization error"
        return {"success": False, "message": f"Pipeline not initialized: {err}", "error": err}
    try:
        set_step("admin_documents_delete")
        pipeline.vectorstore.delete(ids=[doc_id])
        try:
            if hasattr(pipeline, "retriever") and hasattr(pipeline.retriever, "docstore"):
                pipeline.retriever.docstore.mdelete([doc_id])
        except Exception:
            pass
        return {"success": True, "message": "Document deleted successfully"}
    except Exception as e:
        get_logger("admin.documents").exception("documents_delete_failed", extra={"doc_id": doc_id})
        return {"success": False, "message": "Error deleting document", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=3005, reload=True)
