import json

from ..ingestion import KnowledgePipeline


def stream_error_sse(step: str, details: str, message: str):
    async def _gen():
        def _yield_event(event_type: str, data: dict):
            payload = {"type": event_type, **(data or {})}
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        yield _yield_event("trace", {"step": step, "details": details, "status": "error"})
        yield _yield_event("error", {"message": message})
        yield _yield_event("done", {"citations": [], "used_docs": [], "answer": ""})

    return _gen()


def stream_chat_sse(pipeline: KnowledgePipeline, req, user_role: str, top_k: int):
    try:
        from .langgraph_chat import stream_chat_sse_langgraph
        return stream_chat_sse_langgraph(pipeline, req, user_role, top_k)
    except Exception as e:
        return stream_error_sse(
            "Decomposition",
            "Workflow initialization failed",
            f"Workflow initialization failed: {type(e).__name__}: {e}",
        )
