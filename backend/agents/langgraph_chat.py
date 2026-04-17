import asyncio
import json
import os
from typing import Any, Dict, List, Optional, TypedDict, Tuple

from langgraph.graph import END, StateGraph

from .. import models
from ..database import get_db
from ..ingestion import KnowledgePipeline
from ..logger import get_logger, set_step
from ..settings import get_settings
from .common import (
    allowed_roles_for,
    detect_language,
    i18n,
    role_level,
    tokenize,
)
from .memory import build_history_text, maybe_update_session_summary
from .synthesis import extract_page_number, run_synthesis_json_answer_async

log = get_logger("langgraph_chat")


class ChatState(TypedDict, total=False):
    pipeline: KnowledgePipeline
    req: Any
    user_role: str
    top_k: int
    emit: Any
    yield_event: Any

    lang: str
    i18n: Dict[str, str]
    query: str
    history_text: str
    plan: Dict[str, Any]

    citations: List[dict]
    used_docs: List[dict]
    context_blocks: List[str]
    analysis: Dict[str, Any]

    full_answer: str
    citations_used: List[dict]
    used_docs_used: List[dict]
    answer_ready: bool


async def _emit(state: ChatState, event_type: str, data: dict):
    if event_type == "trace":
        try:
            step = (data or {}).get("step")
            if isinstance(step, str) and step:
                set_step(step)
        except Exception:
            pass
        try:
            log.info("trace_event", extra={"step": (data or {}).get("step"), "status": (data or {}).get("status"), "details": (data or {}).get("details")})
        except Exception:
            pass
    elif event_type == "error":
        try:
            log.error("error_event", extra={"message": (data or {}).get("message")})
        except Exception:
            pass
    elif event_type == "done":
        try:
            log.info("done_event", extra={"agentMessageId": (data or {}).get("agentMessageId"), "citations_count": len((data or {}).get("citations") or []), "used_docs_count": len((data or {}).get("used_docs") or [])})
        except Exception:
            pass
    y = state["yield_event"]
    await state["emit"](y(event_type, data or {}))


def _safe_trace_details(s: str) -> str:
    s = (s or "").replace("\n", " ").strip()
    if len(s) > 220:
        s = s[:220].rstrip() + "…"
    return s


def _yield_event_builder():
    def _yield_event(event_type: str, data: dict):
        safe_data = dict(data or {})
        if event_type == "trace":
            safe_data["details"] = _safe_trace_details(safe_data.get("details", ""))
        payload = {"type": event_type, **safe_data}
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return _yield_event


def _trim_text(s: str, max_chars: int) -> str:
    if max_chars <= 0:
        return s or ""
    t = s or ""
    if len(t) <= max_chars:
        return t
    return t[:max_chars].rstrip() + "…"


def _retrieve_scored(pipeline: KnowledgePipeline, user_role: str, query: str, top_k: int, relax: bool, ignore_distance: bool = False) -> List[Tuple[Any, float, float, int]]:
    rag_cfg = get_settings().rag
    max_dist = rag_cfg.max_distance
    if relax:
        max_dist = min(rag_cfg.relax_distance_cap, max_dist + rag_cfg.relax_distance_delta)
    allowed_roles = allowed_roles_for(user_role)
    if not allowed_roles:
        return []
    where = {"role": {"$in": allowed_roles}}
    candidate_k = max(top_k * rag_cfg.retrieval_fanout_multiplier, rag_cfg.retrieval_min_candidates)
    try:
        retrieved_local = pipeline.vectorstore.similarity_search_with_score(query, k=candidate_k, filter=where)
    except Exception:
        retrieved_local = pipeline.vectorstore.similarity_search_with_score(query, k=candidate_k)

    qtoks = set(tokenize(query))
    scored = []
    for doc, dist in retrieved_local:
        meta = doc.metadata or {}
        doc_role = meta.get("role", "Employee")
        if role_level(user_role) < role_level(doc_role):
            continue
        try:
            dist_f = float(dist) if dist is not None else 999.0
        except Exception:
            dist_f = 999.0
        if (not ignore_distance) and dist_f > max_dist:
            continue
        tags = meta.get("tags", "") or ""
        title = meta.get("chunk_title", "") or ""
        category = meta.get("category", "") or ""
        keys = set(tokenize(tags) + tokenize(title) + tokenize(category) + tokenize(doc.page_content or ""))
        overlap = len(qtoks.intersection(keys))
        sim = 1.0 / (1.0 + dist_f)
        combined = sim + (rag_cfg.overlap_weight * overlap)
        scored.append((doc, dist_f, combined, overlap))
    
    # Sử dụng tiêu chí phụ (source metadata) để đảm bảo thứ tự sắp xếp luôn cố định
    scored.sort(key=lambda x: (x[2], x[0].metadata.get("source", "")), reverse=True)
    return scored


async def _node_init(state: ChatState) -> ChatState:
    req = state["req"]
    query = (getattr(req, "message", "") or "").strip()
    lang = detect_language(query)
    i18n_map = i18n(lang)

    await _emit(state, "trace", {"step": "Decomposition", "details": "Chuẩn bị ngữ cảnh (history + ngôn ngữ)..." if lang == "vi" else "Preparing context (history + language)...", "status": "pending"})
    db_hist = next(get_db())
    try:
        history_text = build_history_text(db_hist, req, lang)
    finally:
        db_hist.close()

    plan = {"intent": "qa", "needs_multistep": False, "needs_gap_analysis": False, "notes": "fastest_qa_v1"}
    await _emit(state, "trace", {"step": "Decomposition", "details": "QA: retrieve → synthesize." if lang == "en" else "QA: truy xuất → tổng hợp.", "status": "success"})

    return {"query": query, "lang": lang, "i18n": i18n_map, "history_text": history_text, "plan": plan, "analysis": {}, "answer_ready": False}


async def _node_retrieve(state: ChatState) -> ChatState:
    pipeline = state["pipeline"]
    lang = state["lang"]
    query = state["query"]
    await _emit(state, "trace", {"step": "Delegation", "details": "Truy xuất tri thức từ Knowledge Base..." if lang == "vi" else "Retrieving from Knowledge Base...", "status": "pending"})
    top_k = int(state.get("top_k") or 4)
    accessible_scored = _retrieve_scored(pipeline, state["user_role"], query, top_k, relax=False, ignore_distance=False)[:top_k]
    if not accessible_scored:
        accessible_scored = _retrieve_scored(pipeline, state["user_role"], query, top_k, relax=True, ignore_distance=False)[:top_k]
    if not accessible_scored:
        accessible_scored = _retrieve_scored(pipeline, state["user_role"], query, top_k, relax=True, ignore_distance=True)[:top_k]
        if accessible_scored:
            await _emit(
                state,
                "trace",
                {
                    "step": "Delegation",
                    "details": "Không có nguồn nào đạt ngưỡng distance; dùng best-effort sources để tránh false negative." if lang == "vi" else "No sources met the distance threshold; using best-effort sources to avoid false negatives.",
                    "status": "success",
                },
            )

    if accessible_scored:
        await _emit(state, "trace", {"step": "Delegation", "details": (f"Đã tìm thấy {len(accessible_scored)} nguồn phù hợp." if lang == "vi" else f"Found {len(accessible_scored)} relevant sources."), "status": "success"})
    else:
        kb_count = None
        try:
            if hasattr(pipeline, "vectorstore") and hasattr(pipeline.vectorstore, "_collection"):
                kb_count = int(pipeline.vectorstore._collection.count())
        except Exception:
            kb_count = None
        d = "Không tìm thấy dữ liệu phù hợp." if lang == "vi" else "No relevant data found."
        if isinstance(kb_count, int):
            d = f"{d} (kb_count={kb_count})"
        await _emit(state, "trace", {"step": "Delegation", "details": d, "status": "success"})

    accessible = [(d, dist) for (d, dist, _combined, _overlap) in accessible_scored]
    if not accessible:
        answer = state["i18n"]["no_internal_data"]
        await _emit(state, "trace", {"step": "Synthesis", "details": "Synthesis: skipped (no sources)." if lang == "en" else "Synthesis: bỏ qua (không có nguồn).", "status": "success"})
        await _emit(state, "clear", {})
        await _emit(state, "answer_start", {})
        await _emit(state, "chunk", {"content": answer})
        return {"full_answer": answer, "citations_used": [], "used_docs_used": [], "citations": [], "used_docs": [], "context_blocks": [], "analysis": {}, "answer_ready": True}

    doc_ids: List[str] = []
    for doc, _score in accessible:
        meta = doc.metadata or {}
        did = meta.get(pipeline.id_key) or meta.get("doc_id")
        if did:
            doc_ids.append(str(did))

    chunk_map: Dict[str, dict] = {}
    if hasattr(pipeline, "retriever") and hasattr(pipeline.retriever, "docstore"):
        try:
            full_docs = pipeline.retriever.docstore.mget(doc_ids)
            for i, doc_obj in enumerate(full_docs):
                if doc_obj:
                    chunk_map[doc_ids[i]] = {"content": doc_obj.page_content, "metadata": doc_obj.metadata}
        except Exception:
            chunk_map = {}

    citations: List[dict] = []
    context_blocks: List[str] = []
    used_docs: List[dict] = []
    max_ctx_chars = int(float(os.getenv("RAG_MAX_CONTEXT_CHARS_PER_SOURCE", "1600") or "1600"))
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
        page = extract_page_number(content) or extract_page_number(doc.page_content or "")
        citations.append({"id": did, "title": title, "source": source_name, "category": category, "role": role, "score": float(score), "page": page, "snippet": snippet})
        trimmed = _trim_text(content or (doc.page_content or ""), max_ctx_chars)
        context_blocks.append(f"[{idx}] {title} ({source_name}, {category})\n{trimmed}")
        used_docs.append({"id": did, "title": title, "content": trimmed, "score": float(score), "metadata": {"source": source_name, "category": category, "role": role}})

    await _emit(state, "trace", {"step": "Delegation", "details": (f"Đã chuẩn bị {len(citations)} nguồn để kiểm tra và tổng hợp." if lang == "vi" else f"Prepared {len(citations)} sources for verification and synthesis."), "status": "success"})

    return {"citations": citations, "used_docs": used_docs, "context_blocks": context_blocks, "analysis": {}, "answer_ready": False}


async def _node_synthesis(state: ChatState) -> ChatState:
    lang = state["lang"]
    await _emit(state, "trace", {"step": "Synthesis", "details": "Synthesis Agent: creating JSON {answer, citations_used}..." if lang == "en" else "Synthesis Agent: tạo JSON {answer, citations_used}...", "status": "pending"})
    await _emit(state, "clear", {})
    await _emit(state, "answer_start", {})

    full_answer, citations_used, used_docs_used = await run_synthesis_json_answer_async(
        state["pipeline"].llm,
        state["query"],
        state.get("history_text") or "",
        lang,
        state["i18n"],
        state.get("plan") or {},
        state.get("analysis") or {},
        state.get("context_blocks") or [],
        state.get("citations") or [],
        state.get("used_docs") or [],
    )

    buf_send = ""
    for ch in (full_answer or ""):
        buf_send += ch
        if ch == "\n" or len(buf_send) >= 140:
            await _emit(state, "chunk", {"content": buf_send})
            buf_send = ""
    if buf_send:
        await _emit(state, "chunk", {"content": buf_send})

    await _emit(state, "trace", {"step": "Synthesis", "details": "Synthesis Agent: completed." if lang == "en" else "Synthesis Agent: hoàn tất.", "status": "success"})
    return {"full_answer": full_answer, "citations_used": citations_used, "used_docs_used": used_docs_used, "answer_ready": True}


async def _node_finalize(state: ChatState) -> ChatState:
    req = state["req"]
    agent_message_id = None
    if getattr(req, "sessionId", None):
        db_local = next(get_db())
        try:
            citations_json = json.dumps(state.get("citations_used") or [], ensure_ascii=False)
            used_docs_json = json.dumps(state.get("used_docs_used") or [], ensure_ascii=False)
            new_msg = models.Message(
                session_id=req.sessionId, 
                role="agent", 
                content=state.get("full_answer") or "",
                citations_json=citations_json,
                used_docs_json=used_docs_json
            )
            db_local.add(new_msg)
            db_local.commit()
            db_local.refresh(new_msg)
            agent_message_id = str(new_msg.id)
        except Exception:
            db_local.rollback()
        finally:
            db_local.close()

        asyncio.create_task(
            asyncio.to_thread(
                maybe_update_session_summary,
                state["pipeline"],
                str(req.sessionId),
                str(getattr(req, "userId", None)) if getattr(req, "userId", None) else None,
                state["user_role"],
                state["lang"],
            )
        )
    await _emit(state, "done", {"citations": state.get("citations_used") or [], "used_docs": state.get("used_docs_used") or [], "answer": state.get("full_answer") or "", "agentMessageId": agent_message_id})
    return {}


def _route_after_retrieve(state: ChatState) -> str:
    if state.get("answer_ready"):
        return "finalize"
    return "synthesis"

def stream_chat_sse_langgraph(pipeline: KnowledgePipeline, req, user_role: str, top_k: int):
    async def generate():
        y = _yield_event_builder()
        q: asyncio.Queue[str] = asyncio.Queue()

        async def emit(s: str):
            await q.put(s)

        state: ChatState = {"pipeline": pipeline, "req": req, "user_role": user_role, "top_k": top_k, "emit": emit, "yield_event": y}

        graph = StateGraph(ChatState)
        graph.add_node("init", _node_init)
        graph.add_node("retrieve", _node_retrieve)
        graph.add_node("synthesis", _node_synthesis)
        graph.add_node("finalize", _node_finalize)

        graph.set_entry_point("init")
        graph.add_edge("init", "retrieve")
        graph.add_conditional_edges("retrieve", _route_after_retrieve, {"synthesis": "synthesis", "finalize": "finalize"})
        graph.add_edge("synthesis", "finalize")
        graph.add_edge("finalize", END)

        runner = graph.compile()

        async def _run():
            await runner.ainvoke(state)
            await q.put("")

        task = asyncio.create_task(_run())
        try:
            while True:
                item = await q.get()
                if item == "":
                    break
                yield item
        finally:
            task.cancel()

    return generate()
