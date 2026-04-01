import os
import shutil
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc, inspect
from pydantic import BaseModel
from datetime import datetime
import time
import uuid
import json
import re
import unicodedata

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

PENDING_FOLLOWUPS = {}

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

def _role_level(role: str) -> int:
    levels = {"Guest": 1, "Employee": 2, "Admin": 3}
    return levels.get(role or "", 0)

def _get_user_role(db: Session, user_id: Optional[str], fallback_role: str) -> str:
    if user_id:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if user and user.role:
            return user.role
    return fallback_role

def _coerce_llm_content_to_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if item is None:
                continue
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, str):
                    if t.strip():
                        parts.append(t)
                    else:
                        if item.get("type") == "text":
                            continue
                c = item.get("content")
                if isinstance(c, str) and c.strip():
                    parts.append(c)
                    continue
                continue
            parts.append(str(item))
        return "\n".join([p for p in parts if p])
    return str(content)

def _sanitize_user_facing_text(text: str) -> str:
    t = text or ""
    t = re.sub(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t

def _append_stream_text(current: str, piece: str) -> str:
    if not piece:
        return ""
    if not current:
        return piece
    last = current[-1]
    first = piece[0]
    if last.isalnum() and first.isalnum():
        return " " + piece
    return piece

def _detect_language(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "vi"
    if re.search(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", q, flags=re.IGNORECASE):
        return "vi"
    ql = q.lower()
    if re.search(r"\b(và|là|của|không|cần|hãy|vui lòng|tôi|bạn|ở đâu|như thế nào)\b", ql):
        return "vi"
    return "en"

def _i18n(lang: str) -> dict:
    if lang == "en":
        return {
            "no_internal_data": "No internal data",
            "followup_intro": "No internal data",
            "followup_prompt": "To continue, please answer these questions:",
            "summary_title": "Quick summary:",
            "details_title": "Details:",
            "no_markdown": "Do not use Markdown formatting."
        }
    return {
        "no_internal_data": "Không có dữ liệu nội bộ",
        "followup_intro": "Không có dữ liệu nội bộ",
        "followup_prompt": "Để tiếp tục, vui lòng trả lời các câu hỏi sau:",
        "summary_title": "Tóm tắt nhanh:",
        "details_title": "Chi tiết:",
        "no_markdown": "Không dùng Markdown."
    }

def _normalize_for_match(text: str) -> str:
    t = (text or "").lower()
    t = unicodedata.normalize("NFKD", t)
    t = t.encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return t.strip()

def _tokenize(text: str) -> List[str]:
    t = _normalize_for_match(text)
    if not t:
        return []
    return [p for p in t.split() if len(p) >= 2]

def _select_sources_from_answer(answer: str, citations: List[dict], used_docs: List[dict], max_sources: int = 5):
    ans_tokens = set(_tokenize(answer or ""))
    if not citations:
        return [], []
    scored = []
    for c in citations:
        title = c.get("title") or ""
        snippet = c.get("snippet") or ""
        tokens = set(_tokenize(f"{title} {snippet}"))
        overlap = len(ans_tokens.intersection(tokens))
        base = c.get("score")
        try:
            base_f = float(base) if base is not None else 0.0
        except Exception:
            base_f = 0.0
        scored.append((overlap, base_f, c))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    picked = [c for (overlap, _base, c) in scored if overlap >= 2][:max_sources]
    if not picked:
        picked = [c for (_overlap, _base, c) in scored[:min(max_sources, len(scored))]]

    picked_ids = {str(c.get("id") or "") for c in picked}
    docs = [d for d in (used_docs or []) if str(d.get("id") or "") in picked_ids]
    return picked, docs

def _extract_page_number(text: str) -> Optional[int]:
    m = re.search(r"---\s*PAGE\s*(\d+)\s*---", text or "", flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def _extract_first_json_value(text: str) -> Optional[str]:
    s = (text or "").strip()
    if not s:
        return None
    start_obj = s.find("{")
    start_arr = s.find("[")
    if start_obj == -1 and start_arr == -1:
        return None
    if start_obj == -1:
        start = start_arr
        open_ch, close_ch = "[", "]"
    elif start_arr == -1:
        start = start_obj
        open_ch, close_ch = "{", "}"
    else:
        if start_obj < start_arr:
            start = start_obj
            open_ch, close_ch = "{", "}"
        else:
            start = start_arr
            open_ch, close_ch = "[", "]"

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
        if ch == open_ch:
            depth += 1
            continue
        if ch == close_ch:
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None

def _try_parse_json_object(text: str) -> Optional[dict]:
    j = _extract_first_json_value(text)
    if not j or not j.startswith("{"):
        return None
    try:
        obj = json.loads(j)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None

def _draft_ideal_answer_for_retrieval(llm, query: str, history_text: str, lang: str) -> str:
    if lang == "en":
        prompt = f"""
        You are an internal assistant. Write an ideal (not necessarily correct) HYPOTHETICAL answer to the following question to use as an extended query for the search system.
        Requirements:
        - Keep it concise (4-8 sentences).
        - Prioritize mentioning entities, technologies, projects, roles, skills, customers, and deliverables.
        - Avoid Markdown, quotations, or statements like "I am assuming."
        Conversation history (if any): {history_text or "None."}
        Query: {query}
        """
    else:
        prompt = f"""
        Bạn là trợ lý nội bộ. Hãy viết một câu trả lời GIẢ ĐỊNH lý tưởng (không cần đúng) cho câu hỏi sau để dùng làm truy vấn mở rộng cho hệ thống tìm kiếm.
        Yêu cầu:
        - Viết ngắn gọn 4-8 câu.
        - Ưu tiên nêu thực thể, công nghệ, dự án, vai trò, kỹ năng, khách hàng, deliverables.
        - Tránh Markdown, dấu ngoặc kép, hoặc câu kiểu "tôi đang giả định".
        Lịch sử hội thoại (nếu có): {history_text or "Không có."}
        Câu hỏi: {query}
        """
    try:
        msg = llm.invoke(prompt)
        t = _coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg).strip()
        return t
    except Exception:
        return ""

def _should_use_multistep(query: str) -> bool:
    q = (query or "").lower()
    return bool(re.search(r"\b(ai|who|người\s+nào|nhân\s+sự|kết\s+nối|liên\s+quan|vậy)\b", q))

def _plan_multistep_subqueries(llm, query: str, lang: str) -> List[str]:
    if lang == "en":
        prompt = f"""
        Break down the query into smaller queries to search within the internal Knowledge Base.
        Use only when connecting information across multiple steps (e.g., project → technology → people).
        Return ONLY one JSON object according to the schema:
        {{"subqueries":["string"]}}
        Rules:
        - 1 to 3 subqueries.
        - Each subquery is independent and concise.
        - No Markdown, no explanations.
        Query: {query}
        """
    else:
        prompt = f"""
        Hãy phân rã câu hỏi thành các truy vấn nhỏ để tìm trong Knowledge Base nội bộ.
        Chỉ dùng khi cần kết nối thông tin nhiều bước (ví dụ dự án → công nghệ → nhân sự).
        Trả về DUY NHẤT một JSON object theo schema:
        {{"subqueries":["string"]}}
        Quy tắc:
        - 1 đến 3 subqueries.
        - Mỗi subquery là câu truy vấn độc lập, ngắn gọn.
        - Không Markdown, không giải thích.
        Câu hỏi: {query}
        """
    try:
        msg = llm.invoke(prompt)
        t = _coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        obj = _try_parse_json_object(t)
        subs = obj.get("subqueries") if isinstance(obj, dict) else None
        if not isinstance(subs, list):
            return []
        cleaned = []
        for s in subs:
            if isinstance(s, str) and s.strip():
                cleaned.append(s.strip())
        return cleaned[:3]
    except Exception:
        return []

def _router_agent_plan(llm, query: str, history_text: str, lang: str) -> dict:
    if lang == "en":
        prompt = f"""
        You are a Router Agent (orchestrator brain). Task: Classify requests and determine workflow.
        Return ONLY one JSON object according to schema:
        {{
        "intent": "qa|proposal|gap_analysis",
        "needs_multistep": boolean,
        "needs_gap_analysis": boolean,
        "notes": "string"
        }}
        Rules:
        - "proposal" when the user wants a proposal/RFP/solution suggestion.
        - "gap_analysis" when the user wants to analyze missing internal data.
        - "qa" for a general question.
        - "needs_multistep" = true if the question requires multi-step linking.
        - "needs_gap_analysis" defaults to true unless truly unnecessary.
        - No Markdown, no explanations outside JSON.
        Conversation History: {history_text or "None."}
        User Request: {query}
        """
    else:
        prompt = f"""
        Bạn là Router Agent (bộ não điều hướng). Nhiệm vụ: phân loại yêu cầu và quyết định workflow.
        Trả về DUY NHẤT một JSON object theo schema:
        {{
        "intent": "qa|proposal|gap_analysis",
        "needs_multistep": boolean,
        "needs_gap_analysis": boolean,
        "notes": "string"
        }}
        Quy tắc:
        - "proposal" khi người dùng muốn soạn proposal/RFP/đề xuất giải pháp.
        - "gap_analysis" khi người dùng muốn phân tích khoảng trống/thiếu dữ liệu.
        - "qa" cho câu hỏi thông thường.
        - "needs_multistep" = true nếu câu hỏi cần kết nối thông tin nhiều bước.
        - "needs_gap_analysis" mặc định true, trừ khi thật sự không cần.
        - Không Markdown, không giải thích ngoài JSON.
        Lịch sử hội thoại: {history_text or "Không có."}
        Yêu cầu người dùng: {query}
        """
    try:
        msg = llm.invoke(prompt)
        t = _coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        obj = _try_parse_json_object(t) or {}
        intent = obj.get("intent") if isinstance(obj.get("intent"), str) else "qa"
        if intent not in ["qa", "proposal", "gap_analysis"]:
            intent = "qa"
        needs_multistep = obj.get("needs_multistep")
        if not isinstance(needs_multistep, bool):
            needs_multistep = _should_use_multistep(query)
        needs_gap_analysis = obj.get("needs_gap_analysis")
        if not isinstance(needs_gap_analysis, bool):
            needs_gap_analysis = True
        notes = obj.get("notes") if isinstance(obj.get("notes"), str) else ""
        return {"intent": intent, "needs_multistep": needs_multistep, "needs_gap_analysis": needs_gap_analysis, "notes": notes}
    except Exception:
        return {"intent": "qa", "needs_multistep": _should_use_multistep(query), "needs_gap_analysis": True, "notes": ""}

def _analyst_gap_analysis(llm, query: str, history_text: str, context_blocks: List[str], lang: str) -> dict:
    context_text = chr(10).join(context_blocks[:6]) if context_blocks else ""
    if lang == "en":
        prompt = f"""
        You are an Analyst Agent (Gap Analysis specialist). Identify:
            1) Missing information in internal data to provide a better answer.
            2) Questions to ask the user to gather required information.
        Return ONLY one JSON object according to the schema:
        {{
        "has_internal_data": boolean,
        "gaps": [{{"gap": "string", "impact": "string"}}],
        "questions_to_user": ["string"]
        }}
        Rules:
        - If CONTEXT is empty/irrelevant, set has_internal_data=false.
        - gaps max 5, questions_to_user max 5.
        - No Markdown, no explanations outside JSON.
        Conversation History: {history_text or "None."}
        User Request: {query}
        CONTEXT: {context_text or "EMPTY"}
        """
    else:
        prompt = f"""
        Bạn là Analyst Agent (chuyên gia Gap Analysis). Hãy xác định:
            1) Thông tin còn thiếu trong dữ liệu nội bộ để trả lời tốt hơn.
            2) Các câu hỏi cần hỏi lại người dùng để thu thập thông tin.
        Trả về DUY NHẤT một JSON object theo schema:
        {{
        "has_internal_data": boolean,
        "gaps": [{{"gap": "string", "impact": "string"}}],
        "questions_to_user": ["string"]
        }}
        Quy tắc:
        - Nếu CONTEXT rỗng/không liên quan, đặt has_internal_data=false.
        - gaps tối đa 5, questions_to_user tối đa 5.
        - Không Markdown, không giải thích ngoài JSON.
        Lịch sử hội thoại: {history_text or "Không có."}
        Yêu cầu người dùng: {query}
        CONTEXT: {context_text or "EMPTY"}
    """
    try:
        msg = llm.invoke(prompt)
        t = _coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        obj = _try_parse_json_object(t) or {}
        has_internal_data = obj.get("has_internal_data")
        if not isinstance(has_internal_data, bool):
            has_internal_data = bool(context_blocks)
        gaps = obj.get("gaps") if isinstance(obj.get("gaps"), list) else []
        cleaned_gaps = []
        for g in gaps:
            if not isinstance(g, dict):
                continue
            gap = g.get("gap")
            impact = g.get("impact")
            if isinstance(gap, str) and gap.strip():
                cleaned_gaps.append({"gap": gap.strip(), "impact": impact.strip() if isinstance(impact, str) else ""})
        questions = obj.get("questions_to_user") if isinstance(obj.get("questions_to_user"), list) else []
        cleaned_qs = [q.strip() for q in questions if isinstance(q, str) and q.strip()][:5]
        return {"has_internal_data": has_internal_data, "gaps": cleaned_gaps[:5], "questions_to_user": cleaned_qs}
    except Exception:
        return {"has_internal_data": bool(context_blocks), "gaps": [], "questions_to_user": []}

def _pending_key_for_request(req: ChatRequest) -> Optional[str]:
    if getattr(req, "sessionId", None):
        return f"s:{req.sessionId}"
    if getattr(req, "userId", None):
        return f"u:{req.userId}"
    return None

def _fallback_questions_for_user(query: str, lang: str) -> List[str]:
    if lang == "en":
        return [
            "What project/client context are you asking about? (project name, industry, size)",
            "What output format do you need? (quick answer / proposal / checklist / email reply)",
            "Are there any required technologies/stacks? (e.g., React, FastAPI, AWS, GCP...)",
            "Any constraints on timeline/budget/team?",
            "Can you provide 2–3 must-have requirements and any nice-to-have items?"
        ]
    return [
        "Bạn đang hỏi trong bối cảnh dự án/khách hàng nào? (tên dự án, ngành, quy mô)",
        "Bạn cần đầu ra ở dạng gì? (tư vấn nhanh / proposal / checklist / email trả lời)",
        "Có công nghệ/stack bắt buộc không? (ví dụ: React, FastAPI, AWS, GCP...)",
        "Có ràng buộc về timeline/budget/đội ngũ không?",
        "Bạn có thể cung cấp 2–3 điểm yêu cầu chính (must-have) và điểm ưu tiên (nice-to-have)?"
    ]

def _format_followup_message(questions: List[str], query: str, lang: str) -> str:
    qs = [q.strip() for q in (questions or []) if isinstance(q, str) and q.strip()]
    if not qs:
        qs = _fallback_questions_for_user(query, lang)
    i18n = _i18n(lang)
    lines = [i18n["followup_intro"], "", i18n["followup_prompt"]]
    for i, q in enumerate(qs[:5], start=1):
        lines.append(f"{i}) {q}")
    return "\n".join(lines).strip()

def _extract_followup_questions(analysis: dict, query: str, lang: str) -> List[str]:
    qs = []
    if isinstance(analysis, dict):
        raw = analysis.get("questions_to_user")
        if isinstance(raw, list):
            qs = [q.strip() for q in raw if isinstance(q, str) and q.strip()]
    if not qs:
        qs = _fallback_questions_for_user(query, lang)
    return qs[:5]

def _rewrite_query_for_retrieval(llm, query: str) -> str:
    prompt = f"""
        You are a Query Rewriter Agent (Retrieval Optimizer). Task: Rewrite the user query to improve retrieval against a company knowledge base.
        Return ONLY the rewritten query text, no quotes, no extra words.
        User query: {query}
        Rewritten query:
    """
    try:
        msg = llm.invoke(prompt)
        text = _coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        return text.strip()
    except Exception:
        return ""

@app.post("/api/chat")
async def chat(req: ChatRequest, db: Session = Depends(get_db)):
    if not pipeline:
        return {"success": False, "message": "Pipeline not initialized"}

    query = (req.message or "").strip()
    if not query:
        return {"success": False, "message": "Empty message"}

    user_role = _get_user_role(db, req.userId, req.userRole or "Employee")
    top_k = max(1, min(int(req.topK or 4), 10))

    # Determine if it's a normal request or streaming request
    # Since we want to support streaming, we will return a StreamingResponse
    async def generate_response():
        def _yield_event(event_type: str, data: dict):
            payload = {"type": event_type, **data}
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        step_order = ["Decomposition", "Delegation", "Critique", "Synthesis"]
        for step in step_order:
            yield _yield_event("trace", {"step": step, "details": "", "status": "pending"})

        history_text = ""
        if req.history:
            lines = []
            for m in req.history[-20:]:
                r = "User" if m.role == "user" else "Assistant"
                lines.append(f"{r}: {m.content}")
            history_text = "\n".join(lines)

        query_effective = query
        lang = _detect_language(query_effective)
        i18n = _i18n(lang)
        pending_key = _pending_key_for_request(req)
        if pending_key and pending_key in PENDING_FOLLOWUPS:
            pending = PENDING_FOLLOWUPS.pop(pending_key, None) or {}
            original_query = pending.get("original_query") if isinstance(pending.get("original_query"), str) else ""
            if original_query.strip():
                query_effective = f"{original_query}\n\n" + ("Additional information from the user:\n" if lang == "en" else "Thông tin bổ sung từ người dùng:\n") + f"{query}"
                lang = _detect_language(original_query)
                i18n = _i18n(lang)
                yield _yield_event("trace", {"step": "Decomposition", "details": "Router Agent: nhận câu trả lời bổ sung và tiếp tục workflow..." if lang == "vi" else "Router Agent: received additional answers and continue the workflow...", "status": "pending"})

        yield _yield_event("trace", {"step": "Decomposition", "details": "Router Agent: phân loại yêu cầu và chọn workflow..." if lang == "vi" else "Router Agent: categorize requirements and select workflow...", "status": "pending"})
        plan = _router_agent_plan(pipeline.llm, query_effective, history_text, lang)
        plan_intent = plan.get("intent") if isinstance(plan, dict) else "qa"
        yield _yield_event(
            "trace",
            {
                "step": "Decomposition",
                "details": f"Router Agent: intent={plan_intent}, multistep={'yes' if plan.get('needs_multistep') else 'no'}.",
                "status": "success"
            }
        )

        def _retrieve(q: str):
            retrieved_local = pipeline.vectorstore.similarity_search_with_score(q, k=max(top_k * 10, 20))
            qtoks = set(_tokenize(q))
            scored = []
            for doc, dist in retrieved_local:
                meta = doc.metadata or {}
                doc_role = meta.get("role", "Employee")
                if _role_level(user_role) < _role_level(doc_role):
                    continue

                tags = meta.get("tags", "") or ""
                title = meta.get("chunk_title", "") or ""
                category = meta.get("category", "") or ""
                keys = set(_tokenize(tags) + _tokenize(title) + _tokenize(category) + _tokenize(doc.page_content or ""))
                overlap = len(qtoks.intersection(keys))

                sim = 1.0 / (1.0 + float(dist)) if dist is not None else 0.0
                combined = sim + (0.12 * overlap)
                scored.append((doc, float(dist) if dist is not None else 0.0, combined, overlap))

            scored.sort(key=lambda x: x[2], reverse=True)
            return scored

        yield _yield_event("trace", {"step": "Delegation", "details": "Researcher Agent: tạo truy vấn mở rộng (pseudo-answer)..." if lang == "vi" else "Researcher Agent: draft pseudo-answer for query expansion...", "status": "pending"})
        ideal_answer = _draft_ideal_answer_for_retrieval(pipeline.llm, query_effective, history_text, lang)
        yield _yield_event("trace", {"step": "Delegation", "details": "Researcher Agent: truy xuất tri thức trong Knowledge Base..." if lang == "vi" else "Researcher Agent: retrieve from Knowledge Base...", "status": "pending"})

        queries_to_run = [query_effective]
        use_multistep = bool(plan.get("needs_multistep")) if isinstance(plan, dict) else _should_use_multistep(query_effective)
        if use_multistep:
            planned = _plan_multistep_subqueries(pipeline.llm, query_effective, lang)
            if planned:
                uniq = []
                seen = set()
                for qv in [query_effective, *planned]:
                    if qv and qv not in seen:
                        seen.add(qv)
                        uniq.append(qv)
                queries_to_run = uniq[:4]

        try:
            merged = {}
            for qi in queries_to_run:
                base_q = (qi or "").strip()
                expanded = base_q
                if ideal_answer:
                    expanded = f"{expanded}\n\n{ideal_answer}"

                yield _yield_event("trace", {"step": "Delegation", "details": (f"Researcher Agent: truy vấn: {base_q}" if lang == "vi" else f"Researcher Agent: query: {base_q}"), "status": "pending"})
                for doc, dist, combined, overlap in _retrieve(expanded):
                    meta = doc.metadata or {}
                    did = str(meta.get(pipeline.id_key) or meta.get("doc_id") or "")
                    if not did:
                        continue
                    cur = merged.get(did)
                    if (cur is None) or (combined > cur[2]):
                        merged[did] = (doc, dist, combined, overlap)

                if not merged:
                    rewritten = _rewrite_query_for_retrieval(pipeline.llm, base_q)
                    if rewritten and rewritten != base_q:
                        expanded2 = rewritten
                        if ideal_answer:
                            expanded2 = f"{expanded2}\n\n{ideal_answer}"
                        for doc, dist, combined, overlap in _retrieve(expanded2):
                            meta = doc.metadata or {}
                            did = str(meta.get(pipeline.id_key) or meta.get("doc_id") or "")
                            if not did:
                                continue
                            cur = merged.get(did)
                            if (cur is None) or (combined > cur[2]):
                                merged[did] = (doc, dist, combined, overlap)

            accessible_scored = list(merged.values())
            accessible_scored.sort(key=lambda x: x[2], reverse=True)
            accessible_scored = accessible_scored[:top_k]

            if accessible_scored:
                yield _yield_event("trace", {"step": "Delegation", "details": (f"Researcher Agent: tìm thấy {len(accessible_scored)} kết quả phù hợp." if lang == "vi" else f"Researcher Agent: {len(accessible_scored)} relevant results."), "status": "success"})
            else:
                yield _yield_event("trace", {"step": "Delegation", "details": ("Researcher Agent: không tìm thấy dữ liệu phù hợp." if lang == "vi" else "Researcher Agent: no relevant data found."), "status": "success"})
        except Exception as e:
            print(f"Error during retrieval: {e}")
            yield _yield_event("error", {"message": "Error during retrieval"})
            return

        accessible = [(d, dist) for (d, dist, _combined, _overlap) in accessible_scored]

        if not accessible:
            yield _yield_event("trace", {"step": "Critique", "details": "Analyst Agent: thiếu dữ liệu nội bộ. Chuẩn bị câu hỏi làm rõ..." if lang == "vi" else "Analyst Agent: missing internal data. Preparing clarification questions...", "status": "pending"})
            analysis = _analyst_gap_analysis(pipeline.llm, query_effective, history_text, [], lang)
            questions = _extract_followup_questions(analysis, query_effective, lang)
            if pending_key:
                PENDING_FOLLOWUPS[pending_key] = {
                    "original_query": query_effective,
                    "questions": questions,
                    "created_at": time.time()
                }
            yield _yield_event("trace", {"step": "Critique", "details": (f"Analyst Agent: cần {len(questions)} thông tin bổ sung từ người dùng." if lang == "vi" else f"Analyst Agent: need {len(questions)} more inputs from the user."), "status": "success"})
            yield _yield_event("trace", {"step": "Synthesis", "details": "Synthesis Agent: gửi câu hỏi làm rõ để tiếp tục workflow." if lang == "vi" else "Synthesis Agent: asking follow-up questions to continue the workflow.", "status": "success"})
            answer = _format_followup_message(questions, query_effective, lang)
            yield _yield_event("answer_start", {})
            yield _yield_event("chunk", {"content": answer})
            yield _yield_event("done", {"citations": [], "used_docs": [], "answer": answer, "followup": {"required": True, "questions": questions}})
            return

        doc_ids = []
        for doc, _score in accessible:
            meta = doc.metadata or {}
            did = meta.get(pipeline.id_key) or meta.get("doc_id")
            if did:
                doc_ids.append(str(did))

        chunk_map = {}
        try:
            chunks = pipeline.chunkstore.get(ids=doc_ids, include=["documents", "metadatas"])
            ids = chunks.get("ids") if chunks and chunks.get("ids") is not None else []
            docs = chunks.get("documents") if chunks and chunks.get("documents") is not None else []
            metas = chunks.get("metadatas") if chunks and chunks.get("metadatas") is not None else []
            for i in range(len(ids)):
                chunk_map[str(ids[i])] = {
                    "content": docs[i] if i < len(docs) else "",
                    "metadata": metas[i] if i < len(metas) else {}
                }
        except Exception as e:
            print(f"Error loading chunks: {e}")

        citations = []
        context_blocks = []
        used_docs = []
        for idx, (doc, score) in enumerate(accessible, start=1):
            meta = doc.metadata or {}
            did = str(meta.get(pipeline.id_key) or meta.get("doc_id") or "")
            chunk = chunk_map.get(did, {})
            content = (chunk.get("content") or "").strip()
            cmeta = chunk.get("metadata") or meta
            title = (cmeta.get("chunk_title") or meta.get("chunk_title") or meta.get("source") or "Document").split("/")[-1].split("\\")[-1]
            source = (cmeta.get("source") or meta.get("source") or "")
            source_name = source.split("/")[-1].split("\\")[-1] if source else title
            category = cmeta.get("category") or meta.get("category") or "General"
            role = cmeta.get("role") or meta.get("role") or "Employee"

            snippet = content[:800] if content else (doc.page_content or "")[:800]
            page = _extract_page_number(content) or _extract_page_number(doc.page_content or "")
            citations.append({
                "id": did,
                "title": title,
                "source": source_name,
                "category": category,
                "role": role,
                "score": float(score),
                "page": page,
                "snippet": snippet
            })

            context_blocks.append(f"[{idx}] {title} ({source_name}, {category})\n{content or doc.page_content}")
            used_docs.append({
                "id": did,
                "title": title,
                "content": content or doc.page_content,
                "score": float(score),
                "metadata": {"source": source_name, "category": category, "role": role}
            })

        yield _yield_event("trace", {"step": "Delegation", "details": (f"Researcher Agent: đã chuẩn bị {len(citations)} nguồn để tổng hợp." if lang == "vi" else f"Researcher Agent: prepared {len(citations)} sources for synthesis."), "status": "success"})

        yield _yield_event("trace", {"step": "Critique", "details": "Analyst Agent: phân tích khoảng trống thông tin (gap analysis)..." if lang == "vi" else "Analyst Agent: performing gap analysis...", "status": "pending"})
        analysis = _analyst_gap_analysis(pipeline.llm, query_effective, history_text, context_blocks, lang)
        gaps = analysis.get("gaps") if isinstance(analysis, dict) else []
        gap_note = f"{len(gaps)} gaps" if isinstance(gaps, list) else "done"
        yield _yield_event("trace", {"step": "Critique", "details": (f"Analyst Agent: hoàn tất gap analysis ({gap_note})." if lang == "vi" else f"Analyst Agent: completed gap analysis ({gap_note})."), "status": "success"})
        prompt = f"""
        You are the Synthesis Agent. Create the final answer using ONLY the provided CONTEXT.
        If the context does not contain the answer, respond exactly: "{i18n["no_internal_data"]}"
        CONVERSATION HISTORY: {history_text or "No previous conversation history."}
        CONTEXT: {chr(10).join(context_blocks)}
        USER QUERY: {query_effective}
        ROUTER PLAN: {json.dumps(plan, ensure_ascii=False)}
        GAP ANALYSIS: {json.dumps(analysis, ensure_ascii=False)}
        INSTRUCTIONS:
        - Respond in this language ONLY: {"Vietnamese" if lang == "vi" else "English"}.
        - Do not invent facts not present in the context.
        - Do not include inline citations like [1] or [1, 2] in the answer.
        - Write a natural answer (avoid rigid templates).
        - You MAY emphasize important keywords/phrases using **bold** markers, but use it sparingly.
        - Avoid other Markdown: no headings with #, no code fences.
        - If ROUTER PLAN intent is "proposal", write a professional proposal with clear sections and keep it concise.
        """

        yield _yield_event("trace", {"step": "Synthesis", "details": "Synthesis Agent: soạn câu trả lời/proposal..." if lang == "vi" else "Synthesis Agent: drafting the final answer/proposal...", "status": "pending"})
        yield _yield_event("answer_start", {})

        full_answer = ""
        try:
            for chunk_msg in pipeline.llm.stream(prompt):
                text_chunk = _coerce_llm_content_to_text(chunk_msg.content if hasattr(chunk_msg, "content") else chunk_msg)
                if text_chunk:
                    clean_chunk = _sanitize_user_facing_text(text_chunk)
                    if clean_chunk:
                        to_yield = _append_stream_text(full_answer, clean_chunk)
                        full_answer += to_yield
                        yield _yield_event("chunk", {"content": to_yield})

        except Exception as e:
            print(f"Error during generation: {e}")
            yield _yield_event("error", {"message": "Error during generation"})
            return

        full_answer = (full_answer or "").strip()
        if not full_answer:
            full_answer = i18n["no_internal_data"]
            yield _yield_event("clear", {})
            yield _yield_event("chunk", {"content": full_answer})

        citations_used, used_docs_used = _select_sources_from_answer(full_answer, citations, used_docs, max_sources=5)

        yield _yield_event("trace", {"step": "Synthesis", "details": "Synthesis Agent: hoàn tất." if lang == "vi" else "Synthesis Agent: completed.", "status": "success"})
        # Save to database in a separate session context since Depends(get_db) might close it during streaming? 
        # Actually it's safer to just use a fresh local session
        if req.sessionId:
            db_local = next(get_db())
            try:
                new_msg = models.Message(session_id=req.sessionId, role="agent", content=full_answer)
                db_local.add(new_msg)
                db_local.commit()
            except Exception as e:
                db_local.rollback()
                print(f"Error saving message: {e}")
            finally:
                db_local.close()

        yield _yield_event("done", {"citations": citations_used, "used_docs": used_docs_used, "answer": full_answer})

    return StreamingResponse(generate_response(), media_type="text/event-stream")

@app.post("/api/admin/analyze_gaps")
def analyze_gaps(req: AnalyzeGapsRequest):
    if not pipeline:
        return {"success": False, "message": "Pipeline not initialized"}
    queries = req.queries[:100]
    prompt = f"""
        You are an AI analyst for a Presales Knowledge Base. Analyze the following user queries to provide insights for the admin.
        USER QUERIES: {chr(10).join(queries)}
        REQUIREMENTS:
        Return the result STRICTLY as a JSON object matching this structure:
        {{
        "topInterests": [{{"topic": "string", "reason": "string"}}],
        "knowledgeGaps": [{{"question": "string", "suggestion": "string"}}]
        }}
        Limit topInterests to 3 items, and knowledgeGaps to 2-3 items. Only JSON.
    """
    try:
        msg = pipeline.llm.invoke(prompt)
        text = msg.content if hasattr(msg, "content") else str(msg)
        return {"success": True, "result": text}
    except Exception as e:
        return {"success": False, "message": "Error analyzing gaps", "error": str(e)}

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
                
                documents.append({
                    "id": doc_id,
                    "title": metadata.get("chunk_title") or metadata.get("source", "Unknown Document").split("/")[-1].split("\\")[-1],
                    "content": content,
                    "role": metadata.get("role", "Employee"),
                    "topic": metadata.get("category", "General"),
                    "createdAt": metadata.get("createdAt"),
                    "embedding": embedding
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
        pipeline.vectorstore.delete(ids=[doc_id])
        try:
            pipeline.chunkstore.delete(ids=[doc_id])
        except Exception:
            pass
        return {"success": True, "message": "Document deleted successfully"}
    except Exception as e:
        print(f"Error deleting document: {e}")
        return {"success": False, "message": "Error deleting document", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=3005, reload=True)
