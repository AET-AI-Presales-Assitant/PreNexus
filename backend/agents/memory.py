from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from langchain_core.documents import Document

from .. import models
from ..database import get_db
from ..ingestion import KnowledgePipeline
from .common import coerce_llm_content_to_text, role_level, normalize_for_match


def format_history_lines(messages: List[models.Message]) -> str:
    lines = []
    for m in messages:
        r = "User" if m.role == "user" else "Assistant"
        lines.append(f"{r}: {m.content}")
    return "\n".join(lines)


def build_history_text(db: Session, req, lang: str) -> str:
    exact_match_constraints = []
    general_negative_constraints = []
    
    if getattr(req, "sessionId", None):
        current_query = getattr(req, "message", "")
        current_norm = normalize_for_match(current_query)
        
        try:
            # Lấy toàn bộ tin nhắn trong session để kiểm tra vòng lặp câu hỏi - câu trả lời
            all_msgs = (
                db.query(models.Message)
                .filter(models.Message.session_id == req.sessionId)
                .order_by(models.Message.created_at.asc())
                .all()
            )
            
            # 1. Tìm xem người dùng đã từng hỏi CÂU HỎI Y HỆT NÀY và chê câu trả lời chưa
            for i in range(len(all_msgs) - 1):
                if all_msgs[i].role == "user" and all_msgs[i+1].role == "agent":
                    prev_query = all_msgs[i].content or ""
                    # Nếu câu hỏi cũ giống hệt câu hiện tại
                    if normalize_for_match(prev_query) == current_norm:
                        agent_msg = all_msgs[i+1]
                        feedback = db.query(models.Feedback).filter(models.Feedback.message_id == agent_msg.id, models.Feedback.value.in_([-1, 2])).first()
                        if feedback:
                            note_text = f" (User note: {feedback.note})" if feedback.note else ""
                            exact_match_constraints.append(f"PREVIOUS BAD ANSWER: {agent_msg.content}{note_text}")

            # 2. Lấy 16 tin nhắn gần nhất để làm ngữ cảnh trò chuyện (như cũ)
            recent = all_msgs[-16:] if len(all_msgs) > 16 else all_msgs
            
            # 3. Lọc thêm các tin nhắn AI bị đánh giá Unhelpful gần đây (nếu không nằm trong exact_match)
            for m in recent:
                if m.role == "agent":
                    feedback = db.query(models.Feedback).filter(models.Feedback.message_id == m.id, models.Feedback.value.in_([-1, 2])).first()
                    if feedback:
                        note_text = f" (User note: {feedback.note})" if feedback.note else ""
                        constraint_str = f"PREVIOUS BAD ANSWER: {m.content}{note_text}"
                        if constraint_str not in exact_match_constraints:
                            general_negative_constraints.append(constraint_str)
                        
            sm = db.query(models.SessionMemory).filter(models.SessionMemory.session_id == req.sessionId).first()
            summary = (sm.summary or "").strip() if sm else ""
            recent_text = format_history_lines(recent)
            
            result_text = ""
            if summary:
                result_text = f"SESSION SUMMARY:\n{summary}\n\nRECENT MESSAGES:\n{recent_text}"
            else:
                result_text = recent_text
                
            # Chèn constraints vào cuối history để AI chú ý nhất
            if exact_match_constraints or general_negative_constraints:
                constraints_text = "\n\nCRITICAL CONSTRAINTS FROM USER FEEDBACK:\n"
                
                if exact_match_constraints:
                    constraints_text += "The user has asked this EXACT SAME question before and marked your previous answers as unhelpful or incorrect. You MUST provide a COMPLETELY DIFFERENT, BETTER, or CORRECTED answer. Do NOT repeat these mistakes:\n"
                    constraints_text += "\n---\n".join(exact_match_constraints) + "\n\n"
                    
                if general_negative_constraints:
                    constraints_text += "The user also marked these recent answers as unhelpful. Keep this in mind to avoid similar mistakes:\n"
                    constraints_text += "\n---\n".join(general_negative_constraints[-2:]) # Chỉ lấy 2 feedback chung gần nhất để tránh loãng
                    
                result_text += constraints_text
                
            return result_text
        except Exception as e:
            print(f"Error building history text: {e}")
            pass

    hist = getattr(req, "history", None)
    if hist:
        lines = []
        for m in hist[-20:]:
            r = "User" if m.role == "user" else "Assistant"
            lines.append(f"{r}: {m.content}")
        return "\n".join(lines)
    return ""


def retrieve_user_memories(pipeline: KnowledgePipeline, query: str, user_id: Optional[str], user_role: str, k: int = 5) -> List[str]:
    if not user_id:
        return []
    try:
        raw = pipeline.memory_store.similarity_search_with_score(query, k=max(12, k * 3))
    except Exception:
        return []
    out = []
    for doc, dist in raw:
        meta = doc.metadata or {}
        if str(meta.get("user_id") or "") != str(user_id):
            continue
        mrole = str(meta.get("role") or "Employee")
        if role_level(user_role) < role_level(mrole):
            continue
        t = (doc.page_content or "").strip()
        if t:
            out.append(t)
        if len(out) >= k:
            break
    return out


def maybe_update_session_summary(pipeline: KnowledgePipeline, session_id: str, user_id: Optional[str], user_role: str, lang: str):
    if not session_id:
        return
    db_local = next(get_db())
    try:
        msg_count = db_local.query(models.Message).filter(models.Message.session_id == session_id).count()
        sm = db_local.query(models.SessionMemory).filter(models.SessionMemory.session_id == session_id).first()
        last_id = sm.last_message_id if sm else None
        all_msgs = (
            db_local.query(models.Message)
            .filter(models.Message.session_id == session_id)
            .order_by(models.Message.created_at.asc())
            .limit(80)
            .all()
        )
        new_msgs = all_msgs
        if last_id:
            try:
                idx = next(i for i, m in enumerate(all_msgs) if m.id == last_id)
                new_msgs = all_msgs[idx + 1 :]
            except StopIteration:
                new_msgs = all_msgs

        if sm is None:
            sm = models.SessionMemory(session_id=session_id, summary="", last_message_id=None, updated_at=datetime.utcnow())
            db_local.add(sm)
            db_local.commit()
            db_local.refresh(sm)

        if (msg_count < 12 and not sm.summary) or len(new_msgs) < 6:
            return

        existing = (sm.summary or "").strip()
        dialogue = format_history_lines(new_msgs)
        prompt = f"""
            You maintain a compact memory for an internal assistant.
            Update the session summary using the existing summary and new dialogue.

            Rules:
            - Language MUST be: {"Vietnamese" if lang == "vi" else "English"}.
            - Keep it short: 8-14 lines max.
            - Include only durable info: user goals, constraints, preferences, decisions, important entities.
            - Do NOT include secrets/PII.
            - Output plain text only.

            EXISTING SUMMARY:
            {existing or "(none)"}

            NEW DIALOGUE:
            {dialogue}
        """
        msg = pipeline.llm.invoke(prompt)
        updated = coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg).strip()
        if not updated:
            return

        last_msg_id = new_msgs[-1].id if new_msgs else sm.last_message_id
        sm.summary = updated
        sm.last_message_id = last_msg_id
        sm.updated_at = datetime.utcnow()
        db_local.commit()

        if user_id:
            um = (
                db_local.query(models.UserMemory)
                .filter(models.UserMemory.user_id == user_id, models.UserMemory.session_id == session_id, models.UserMemory.kind == "session_summary")
                .first()
            )
            if um is None:
                um = models.UserMemory(user_id=user_id, session_id=session_id, kind="session_summary", content=updated, updated_at=datetime.utcnow(), created_at=datetime.utcnow())
                db_local.add(um)
            else:
                um.content = updated
                um.updated_at = datetime.utcnow()
            db_local.commit()
            try:
                doc_id = f"session_summary:{session_id}"
                try:
                    pipeline.memory_store.delete(ids=[doc_id])
                except Exception:
                    pass
                pipeline.memory_store.add_documents(
                    [Document(page_content=updated, metadata={"user_id": str(user_id), "session_id": str(session_id), "role": user_role, "kind": "session_summary"})],
                    ids=[doc_id]
                )
            except Exception:
                pass
    except Exception:
        db_local.rollback()
    finally:
        db_local.close()

