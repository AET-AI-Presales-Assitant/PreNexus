import asyncio
import json
import os
from typing import Any, Dict, List, Optional, TypedDict, Tuple

from langgraph.graph import END, StateGraph

from .. import models
from ..database import get_db
from ..ingestion import KnowledgePipeline
from .analyst import analyst_gap_analysis_async
from .common import (
    allowed_roles_for,
    detect_language,
    i18n,
    normalize_for_match,
    role_level,
    tokenize,
)
from .memory import build_history_text, maybe_update_session_summary, retrieve_user_memories
from .researcher import draft_ideal_answer_for_retrieval_async, rewrite_query_for_retrieval_async
from .router import plan_multistep_subqueries_async, router_agent_plan_async, should_use_multistep
from .synthesis import extract_page_number, run_synthesis_json_answer_async


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
    queries_to_run: List[str]
    ideal_answer: str

    citations: List[dict]
    used_docs: List[dict]
    context_blocks: List[str]
    analysis: Dict[str, Any]

    full_answer: str
    citations_used: List[dict]
    used_docs_used: List[dict]
    answer_ready: bool


async def _emit(state: ChatState, event_type: str, data: dict):
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


def _retrieve_scored(pipeline: KnowledgePipeline, user_role: str, query: str, top_k: int, relax: bool) -> List[Tuple[Any, float, float, int]]:
    max_dist = float(os.getenv("RAG_MAX_DISTANCE", "0.75") or "0.75")
    if relax:
        max_dist = min(0.95, max_dist + 0.15)
    allowed_roles = allowed_roles_for(user_role)
    if not allowed_roles:
        return []
    where = {"role": {"$in": allowed_roles}}
    try:
        retrieved_local = pipeline.vectorstore.similarity_search_with_score(query, k=max(top_k * 10, 20), filter=where)
    except Exception:
        retrieved_local = pipeline.vectorstore.similarity_search_with_score(query, k=max(top_k * 10, 20))

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
        if dist_f > max_dist:
            continue
        tags = meta.get("tags", "") or ""
        title = meta.get("chunk_title", "") or ""
        category = meta.get("category", "") or ""
        keys = set(tokenize(tags) + tokenize(title) + tokenize(category) + tokenize(doc.page_content or ""))
        overlap = len(qtoks.intersection(keys))
        sim = 1.0 / (1.0 + dist_f)
        combined = sim + (0.12 * overlap)
        scored.append((doc, dist_f, combined, overlap))
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored


async def _node_init(state: ChatState) -> ChatState:
    req = state["req"]
    query = (getattr(req, "message", "") or "").strip()
    lang = detect_language(query)
    i18n_map = i18n(lang)

    await _emit(state, "trace", {"step": "Decomposition", "details": "Chuẩn bị ngữ cảnh..." if lang == "vi" else "Preparing context...", "status": "pending"})
    db_hist = next(get_db())
    try:
        history_text = build_history_text(db_hist, req, lang)
    finally:
        db_hist.close()

    memories = await asyncio.to_thread(retrieve_user_memories, state["pipeline"], query, getattr(req, "userId", None), state["user_role"], k=5)
    if memories:
        mem_lines = "\n".join([f"- {m}" for m in memories[:5]])
        history_text = (history_text + "\n\n" if history_text else "") + ("MEMORIES:\n" + mem_lines)

    await _emit(state, "trace", {"step": "Decomposition", "details": "Router Agent: phân loại yêu cầu và chọn workflow..." if lang == "vi" else "Router Agent: categorize requirements and select workflow...", "status": "pending"})
    plan = await router_agent_plan_async(state["pipeline"].llm, query, history_text, lang)
    plan_intent = plan.get("intent") if isinstance(plan, dict) else "qa"
    await _emit(state, "trace", {"step": "Decomposition", "details": f"Router Agent: intent={plan_intent}, multistep={'yes' if plan.get('needs_multistep') else 'no'}.", "status": "success"})

    return {"query": query, "lang": lang, "i18n": i18n_map, "history_text": history_text, "plan": plan, "answer_ready": False}


async def _node_retrieve(state: ChatState) -> ChatState:
    pipeline = state["pipeline"]
    lang = state["lang"]
    query = state["query"]
    history_text = state.get("history_text") or ""
    plan = state.get("plan") or {}

    await _emit(state, "trace", {"step": "Delegation", "details": "Researcher Agent: tạo truy vấn mở rộng (pseudo-answer)..." if lang == "vi" else "Researcher Agent: draft pseudo-answer for query expansion...", "status": "pending"})
    ideal_answer = await draft_ideal_answer_for_retrieval_async(pipeline.llm, query, history_text, lang)
    await _emit(state, "trace", {"step": "Delegation", "details": "Researcher Agent: truy xuất tri thức trong Knowledge Base..." if lang == "vi" else "Researcher Agent: retrieve from Knowledge Base...", "status": "pending"})

    queries_to_run = [query]
    use_multistep = bool(plan.get("needs_multistep")) if isinstance(plan, dict) else should_use_multistep(query)
    if use_multistep:
        planned = await plan_multistep_subqueries_async(pipeline.llm, query, lang)
        if planned:
            uniq = []
            seen = set()
            for qv in [query, *planned]:
                if qv and qv not in seen:
                    seen.add(qv)
                    uniq.append(qv)
            queries_to_run = uniq[:4]

    top_k = int(state.get("top_k") or 4)
    merged: Dict[str, Tuple[Any, float, float, int]] = {}
    for qi in queries_to_run:
        base_q = (qi or "").strip()
        expanded = base_q
        if ideal_answer:
            expanded = f"{expanded}\n\n{ideal_answer}"
        await _emit(state, "trace", {"step": "Delegation", "details": (f"Researcher Agent: truy vấn: {base_q}" if lang == "vi" else f"Researcher Agent: query: {base_q}"), "status": "pending"})
        for doc, dist, combined, overlap in _retrieve_scored(pipeline, state["user_role"], expanded, top_k, relax=False):
            meta = doc.metadata or {}
            did = str(meta.get(pipeline.id_key) or meta.get("doc_id") or "")
            if not did:
                continue
            cur = merged.get(did)
            if (cur is None) or (combined > cur[2]):
                merged[did] = (doc, dist, combined, overlap)

        if not merged:
            rewritten = await rewrite_query_for_retrieval_async(pipeline.llm, base_q)
            if rewritten and rewritten != base_q:
                expanded2 = rewritten
                if ideal_answer:
                    expanded2 = f"{expanded2}\n\n{ideal_answer}"
                for doc, dist, combined, overlap in _retrieve_scored(pipeline, state["user_role"], expanded2, top_k, relax=True):
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
        await _emit(state, "trace", {"step": "Delegation", "details": (f"Researcher Agent: tìm thấy {len(accessible_scored)} kết quả phù hợp." if lang == "vi" else f"Researcher Agent: {len(accessible_scored)} relevant results."), "status": "success"})
    else:
        await _emit(state, "trace", {"step": "Delegation", "details": ("Researcher Agent: không tìm thấy dữ liệu phù hợp." if lang == "vi" else "Researcher Agent: no relevant data found."), "status": "success"})

    accessible = [(d, dist) for (d, dist, _combined, _overlap) in accessible_scored]
    if not accessible:
        answer = state["i18n"]["no_internal_data"]
        await _emit(state, "trace", {"step": "Critique", "details": "Analyst Agent: bỏ qua (không có nguồn phù hợp)." if lang == "vi" else "Analyst Agent: skipped (no relevant sources).", "status": "success"})
        await _emit(state, "trace", {"step": "Synthesis", "details": "Synthesis Agent: bỏ qua (không có nguồn phù hợp)." if lang == "vi" else "Synthesis Agent: skipped (no relevant sources).", "status": "success"})
        await _emit(state, "clear", {})
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
        context_blocks.append(f"[{idx}] {title} ({source_name}, {category})\n{content or doc.page_content}")
        used_docs.append({"id": did, "title": title, "content": content or doc.page_content, "score": float(score), "metadata": {"source": source_name, "category": category, "role": role}})

    await _emit(state, "trace", {"step": "Delegation", "details": (f"Researcher Agent: đã chuẩn bị {len(citations)} nguồn để tổng hợp." if lang == "vi" else f"Researcher Agent: prepared {len(citations)} sources for synthesis."), "status": "success"})

    return {"citations": citations, "used_docs": used_docs, "context_blocks": context_blocks, "ideal_answer": ideal_answer, "queries_to_run": queries_to_run, "answer_ready": False}


async def _node_critique(state: ChatState) -> ChatState:
    lang = state["lang"]
    await _emit(state, "trace", {"step": "Critique", "details": "Analyst Agent: phân tích khoảng trống thông tin (gap analysis)..." if lang == "vi" else "Analyst Agent: performing gap analysis...", "status": "pending"})
    analysis = await analyst_gap_analysis_async(state["pipeline"].llm, state["query"], state.get("history_text") or "", state.get("context_blocks") or [], lang)
    gaps = analysis.get("gaps") if isinstance(analysis, dict) else []
    gap_note = f"{len(gaps)} gaps" if isinstance(gaps, list) else "done"
    await _emit(state, "trace", {"step": "Critique", "details": (f"Analyst Agent: hoàn tất gap analysis ({gap_note})." if lang == "vi" else f"Analyst Agent: completed gap analysis ({gap_note})."), "status": "success"})
    return {"analysis": analysis}


async def _node_synthesis(state: ChatState) -> ChatState:
    lang = state["lang"]
    await _emit(state, "trace", {"step": "Synthesis", "details": "Synthesis Agent: tạo JSON {answer, citations_used}..." if lang == "vi" else "Synthesis Agent: producing JSON {answer, citations_used}...", "status": "pending"})
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

    await _emit(state, "trace", {"step": "Synthesis", "details": "Synthesis Agent: hoàn tất." if lang == "vi" else "Synthesis Agent: completed.", "status": "success"})
    return {"full_answer": full_answer, "citations_used": citations_used, "used_docs_used": used_docs_used, "answer_ready": True}


async def _node_finalize(state: ChatState) -> ChatState:
    req = state["req"]
    if getattr(req, "sessionId", None):
        db_local = next(get_db())
        try:
            new_msg = models.Message(session_id=req.sessionId, role="agent", content=state.get("full_answer") or "")
            db_local.add(new_msg)
            db_local.commit()
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
    await _emit(state, "done", {"citations": state.get("citations_used") or [], "used_docs": state.get("used_docs_used") or [], "answer": state.get("full_answer") or ""})
    return {}


def _route_after_retrieve(state: ChatState) -> str:
    if state.get("answer_ready"):
        return "finalize"
    return "critique"


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
        graph.add_node("critique", _node_critique)
        graph.add_node("synthesis", _node_synthesis)
        graph.add_node("finalize", _node_finalize)

        graph.set_entry_point("init")
        graph.add_edge("init", "retrieve")
        graph.add_conditional_edges("retrieve", _route_after_retrieve, {"critique": "critique", "finalize": "finalize"})
        graph.add_edge("critique", "synthesis")
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

