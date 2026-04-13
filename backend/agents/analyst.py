from typing import List

from .common import coerce_llm_content_to_text, try_parse_json_object, invoke_llm


def analyst_gap_analysis(llm, query: str, history_text: str, context_blocks: List[str], lang: str) -> dict:
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
            - Ưu tiên câu hỏi ngắn, cụ thể, có thể trả lời nhanh.
            - Không Markdown, không giải thích ngoài JSON.
            Lịch sử hội thoại: {history_text or "Không có."}
            Yêu cầu người dùng: {query}
            CONTEXT: {context_text or "EMPTY"}
        """
    try:
        msg = llm.invoke(prompt)
        t = coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        obj = try_parse_json_object(t) or {}
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


async def analyst_gap_analysis_async(llm, query: str, history_text: str, context_blocks: List[str], lang: str) -> dict:
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
            - Ưu tiên câu hỏi ngắn, cụ thể, có thể trả lời nhanh.
            - Không Markdown, không giải thích ngoài JSON.
            Lịch sử hội thoại: {history_text or "Không có."}
            Yêu cầu người dùng: {query}
            CONTEXT: {context_text or "EMPTY"}
        """
    try:
        msg = await invoke_llm(llm, prompt)
        t = coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        obj = try_parse_json_object(t) or {}
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
