import os
import shutil
import threading
import asyncio
from typing import List, Optional
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc, inspect, text
from pydantic import BaseModel
from datetime import datetime
import time
import uuid
import json
import re
import unicodedata
import traceback

from .database import engine, get_db
from . import models

# Import pipeline
from .ingestion import KnowledgePipeline
from langchain_core.documents import Document
from .agents.chat_workflow import stream_chat_sse, stream_error_sse

# Create tables if they don't exist (Drizzle handles this, but we can do it here too just in case)
# models.Base.metadata.create_all(bind=engine)

load_dotenv()

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
            print(f"Warning: Could not initialize KnowledgePipeline. Details: {pipeline_init_error}")
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
        print("Admin user seeded")
        return
    if admin.role != "SuperManager":
        admin.role = "SuperManager"
        db.commit()

@app.on_event("startup")
def startup_event():
    models.Base.metadata.create_all(bind=engine)
    db = next(get_db())
    seed_admin(db)

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
    return d

def _safe_json_load(s: str):
    try:
        return json.loads(s) if isinstance(s, str) and s.strip() else None
    except Exception:
        return None

def ingest_job_to_dict(job: models.IngestJob):
    d = to_dict(job) or {}
    if isinstance(d.get("errors"), str):
        d["errors"] = _safe_json_load(d["errors"]) or []
    if isinstance(d.get("vectorIds"), str):
        d["vectorIds"] = _safe_json_load(d["vectorIds"]) or []
    if isinstance(d.get("chunkIds"), str):
        d["chunkIds"] = _safe_json_load(d["chunkIds"]) or []
    return d

@app.post("/api/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    try:
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
        print(f"Login error: {e}")
        return {"success": False, "message": "Internal Server Error"}

@app.post("/api/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    try:
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
        print(f"Register error: {e}")
        return {"success": False, "message": "Internal Server Error"}

@app.get("/api/sessions")
def get_sessions(userId: str, db: Session = Depends(get_db)):
    try:
        sessions = db.query(models.Session).filter(models.Session.user_id == userId).order_by(desc(models.Session.created_at)).all()
        return {"success": True, "sessions": [to_dict(s) for s in sessions]}
    except Exception as e:
        print(f"Error fetching sessions: {e}")
        return {"success": False, "message": str(e)}

@app.post("/api/sessions")
def create_session(req: SessionCreateRequest, db: Session = Depends(get_db)):
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
    messages = db.query(models.Message).filter(models.Message.session_id == session_id).order_by(models.Message.created_at).all()
    return {"success": True, "messages": [to_dict(m) for m in messages]}

@app.post("/api/messages")
def create_message(req: MessageCreateRequest, db: Session = Depends(get_db)):
    new_msg = models.Message(
        session_id=req.sessionId,
        role=req.role,
        content=req.content
    )
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)
    return {"success": True, "message": to_dict(new_msg)}

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
    query = (req.message or "").strip()
    if not query:
        return StreamingResponse(
            stream_error_sse("Decomposition", "Empty message", "Empty message"),
            media_type="text/event-stream"
        )

    user_role = _get_user_role(db, req.userId, req.userRole or "Employee")
    top_k = max(1, min(int(req.topK or 4), 10))
    async def _gen():
        def _yield_event(event_type: str, data: dict):
            payload = {"type": event_type, **(data or {})}
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        yield _yield_event("trace", {"step": "Decomposition", "details": "Initializing pipeline...", "status": "pending"})
        ok = await asyncio.to_thread(_init_pipeline_if_needed, False)
        if not ok:
            err = pipeline_init_error or "Unknown initialization error"
            yield _yield_event("trace", {"step": "Decomposition", "details": f"Pipeline not initialized: {err}", "status": "error"})
            yield _yield_event("error", {"message": f"Pipeline not initialized: {err}"})
            yield _yield_event("done", {"citations": [], "used_docs": [], "answer": ""})
            return

        yield _yield_event("trace", {"step": "Decomposition", "details": "Pipeline initialized.", "status": "success"})
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
        Return ONLY JSON (no Markdown, no extra text) matching:
        {{
          "topInterests": [{{"topic": "string", "reason": "string"}}],
          "knowledgeGaps": [{{"question": "string", "suggestion": "string"}}]
        }}
        Rules:
        - topInterests: max 3 items.
        - knowledgeGaps: 2-3 items.
        - reason/suggestion must be short and actionable.
        - Do not include secrets/PII if the queries contain sensitive info.
        USER QUERIES:
        {chr(10).join(queries)}
    """
    try:
        msg = pipeline.llm.invoke(prompt)
        text = msg.content if hasattr(msg, "content") else str(msg)
        return {"success": True, "result": text}
    except Exception as e:
        return {"success": False, "message": "Error analyzing gaps", "error": str(e)}

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    try:
        try:
            db.execute(text("DELETE FROM followup_contexts WHERE session_id = :sid"), {"sid": session_id})
        except Exception:
            db.rollback()
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
    # Fetch all messages joined with session and user
    # To keep it simple, we can fetch messages and join manually or use SQLAlchemy joins
    results = db.query(models.Message, models.Session, models.User).join(
        models.Session, models.Message.session_id == models.Session.id
    ).join(
        models.User, models.Session.user_id == models.User.id
    ).order_by(models.Message.created_at).all()

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
                if i + 1 < len(msgs) and msgs[i+1]["role"] == "agent":
                    answer_content = msgs[i+1]["content"]
                
                queries.append({
                    "id": msg["id"],
                    "content": msg["content"],
                    "createdAt": msg["createdAt"],
                    "userName": msg["userName"],
                    "userRole": msg["userRole"],
                    "sessionTitle": msg["sessionTitle"],
                    "answerContent": answer_content
                })

    queries.sort(key=lambda x: x["createdAt"], reverse=True)
    return {"success": True, "queries": queries}

@app.post("/api/admin/import")
async def import_data(background_tasks: BackgroundTasks, file: UploadFile = File(...), role: str = Form("Employee"), db: Session = Depends(get_db)):
    if not file:
        raise HTTPException(status_code=400, detail={"success": False, "message": "No file uploaded"})

    if not _init_pipeline_if_needed(force=False):
        err = pipeline_init_error or "Unknown initialization error"
        return {"success": False, "message": f"Pipeline not initialized: {err}", "error": err}
    
    upload_dir = os.path.join(os.getcwd(), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    job = models.IngestJob(file_name=file.filename, file_path=file_path, role=role, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)

    def _run_job(job_id: str):
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

            result = pipeline.process_and_ingest(j.file_path, j.role)
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
        except Exception as e:
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

    background_tasks.add_task(_run_job, str(job.id))
    return {"success": True, "job": ingest_job_to_dict(job)}

@app.get("/api/files/{file_name}")
def get_uploaded_file(file_name: str):
    safe_name = os.path.basename(file_name or "")
    if not safe_name:
        return {"success": False, "message": "Invalid file name"}
    if not safe_name.lower().endswith(".pdf"):
        return {"success": False, "message": "Only PDF files are supported"}
    upload_dir = os.path.join(os.getcwd(), "uploads")
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

    def _run_job(job_id2: str):
        db_local = next(get_db())
        try:
            j = db_local.query(models.IngestJob).filter(models.IngestJob.id == job_id2).first()
            if not j:
                return
            j.status = "processing"
            j.started_at = datetime.utcnow()
            j.error = None
            j.errors_json = None
            j.vector_ids_json = None
            j.chunk_ids_json = None
            db_local.commit()

            if not _init_pipeline_if_needed(force=False):
                raise RuntimeError(f"Pipeline not initialized: {pipeline_init_error or 'Unknown initialization error'}")

            result = pipeline.process_and_ingest(j.file_path, j.role)
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
        except Exception as e:
            try:
                j = db_local.query(models.IngestJob).filter(models.IngestJob.id == job_id2).first()
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

    background_tasks.add_task(_run_job, str(new_job.id))
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
                    "embedding": embedding
                })
        return {"success": True, "documents": documents}
    except Exception as e:
        print(f"Error getting documents: {e}")
        return {"success": False, "message": "Error getting documents", "error": str(e)}

@app.delete("/api/admin/documents/{doc_id}")
def delete_document(doc_id: str):
    if not _init_pipeline_if_needed(force=False):
        err = pipeline_init_error or "Unknown initialization error"
        return {"success": False, "message": f"Pipeline not initialized: {err}", "error": err}
    try:
        pipeline.vectorstore.delete(ids=[doc_id])
        try:
            if hasattr(pipeline, "retriever") and hasattr(pipeline.retriever, "docstore"):
                pipeline.retriever.docstore.mdelete([doc_id])
        except Exception:
            pass
        return {"success": True, "message": "Document deleted successfully"}
    except Exception as e:
        print(f"Error deleting document: {e}")
        return {"success": False, "message": "Error deleting document", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=3005, reload=True)
