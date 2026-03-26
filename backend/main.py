import os
import shutil
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc, inspect
from pydantic import BaseModel
from datetime import datetime
import uuid

from .database import engine, get_db
from . import models

# Import pipeline
from .ingestion import KnowledgePipeline

# Create tables if they don't exist (Drizzle handles this, but we can do it here too just in case)
# models.Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Pipeline globally (Ensure GOOGLE_API_KEY is set in environment or pass it)
# Assuming it will be passed via env
api_key = os.getenv("GEMINI_API_KEY", "AIzaSyBM_Xgk-b6M31axc_RqmY6nxEmKokX8DsU")
try:
    pipeline = KnowledgePipeline(api_key=api_key)
except ImportError as e:
    print(f"Warning: Could not initialize KnowledgePipeline due to missing imports. Details: {e}")
    pipeline = None

# Seed Admin User
def seed_admin(db: Session):
    admin = db.query(models.User).filter(models.User.username == "admin").first()
    if not admin:
        new_admin = models.User(
            username="admin",
            password="admin123",
            role="Admin",
            name="System Admin"
        )
        db.add(new_admin)
        db.commit()
        print("Admin user seeded")

@app.on_event("startup")
def startup_event():
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

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    db.query(models.Message).filter(models.Message.session_id == session_id).delete()
    db.query(models.Session).filter(models.Session.id == session_id).delete()
    db.commit()
    return {"success": True}

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
        safe_users.append(u_dict)
    return {"success": True, "users": safe_users}

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
async def import_data(file: UploadFile = File(...), role: str = Form("Employee")):
    if not file:
        raise HTTPException(status_code=400, detail={"success": False, "message": "No file uploaded"})
    
    upload_dir = os.path.join(os.getcwd(), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    try:
        print(f"Processing uploaded file directly in FastAPI: {file_path}")
        pipeline.process_and_ingest(file_path, role)
        return {"success": True, "message": f"File {file.filename} processed and ingested successfully"}
    except Exception as e:
        print(f"Error processing file: {e}")
        return {"success": False, "message": "Error processing file", "error": str(e)}

@app.get("/api/admin/documents")
def get_documents():
    if not pipeline:
        return {"success": False, "message": "Pipeline not initialized"}
    try:
        # Lấy toàn bộ documents từ vectorstore
        # ChromaDB get() method
        docs = pipeline.vectorstore.get()
        documents = []
        if docs and docs.get("ids"):
            for i in range(len(docs["ids"])):
                doc_id = docs["ids"][i]
                metadata = docs["metadatas"][i] if docs.get("metadatas") else {}
                content = docs["documents"][i] if docs.get("documents") else ""
                
                documents.append({
                    "id": doc_id,
                    "title": metadata.get("source", "Unknown Document").split("/")[-1].split("\\")[-1],
                    "content": content,
                    "role": metadata.get("role", "Employee"),
                    "topic": metadata.get("category", "General")
                })
        return {"success": True, "documents": documents}
    except Exception as e:
        print(f"Error getting documents: {e}")
        return {"success": False, "message": "Error getting documents", "error": str(e)}

@app.delete("/api/admin/documents/{doc_id}")
def delete_document(doc_id: str):
    if not pipeline:
        return {"success": False, "message": "Pipeline not initialized"}
    try:
        # ChromaDB xóa theo id
        pipeline.vectorstore.delete(ids=[doc_id])
        return {"success": True, "message": "Document deleted successfully"}
    except Exception as e:
        print(f"Error deleting document: {e}")
        return {"success": False, "message": "Error deleting document", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=3005, reload=True)
