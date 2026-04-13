import re
from typing import List

from .common import coerce_llm_content_to_text, try_parse_json_object, invoke_llm


def should_use_multistep(query: str) -> bool:
    q = (query or "").lower()
    return bool(re.search(r"\b(ai|who|người\s+nào|nhân\s+sự|kết\s+nối|liên\s+quan|vậy)\b", q))


def plan_multistep_subqueries(llm, query: str, lang: str) -> List[str]:
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
        t = coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        obj = try_parse_json_object(t)
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


def router_agent_plan(llm, query: str, history_text: str, lang: str) -> dict:
    if lang == "en":
        prompt = f"""
            You are a Router Agent. Classify the request and decide the workflow.
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
            Bạn là Router Agent. Nhiệm vụ: phân loại yêu cầu và quyết định workflow.
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
        t = coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        obj = try_parse_json_object(t) or {}
        intent = obj.get("intent") if isinstance(obj.get("intent"), str) else "qa"
        if intent not in ["qa", "proposal", "gap_analysis"]:
            intent = "qa"
        needs_multistep = obj.get("needs_multistep")
        if not isinstance(needs_multistep, bool):
            needs_multistep = should_use_multistep(query)
        needs_gap_analysis = obj.get("needs_gap_analysis")
        if not isinstance(needs_gap_analysis, bool):
            needs_gap_analysis = True
        notes = obj.get("notes") if isinstance(obj.get("notes"), str) else ""
        return {"intent": intent, "needs_multistep": needs_multistep, "needs_gap_analysis": needs_gap_analysis, "notes": notes}
    except Exception:
        return {"intent": "qa", "needs_multistep": should_use_multistep(query), "needs_gap_analysis": True, "notes": ""}


async def plan_multistep_subqueries_async(llm, query: str, lang: str) -> List[str]:
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
        msg = await invoke_llm(llm, prompt)
        t = coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        obj = try_parse_json_object(t)
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


async def router_agent_plan_async(llm, query: str, history_text: str, lang: str) -> dict:
    if lang == "en":
        prompt = f"""
            You are a Router Agent. Classify the request and decide the workflow.
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
            Bạn là Router Agent. Nhiệm vụ: phân loại yêu cầu và quyết định workflow.
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
        msg = await invoke_llm(llm, prompt)
        t = coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        obj = try_parse_json_object(t) or {}
        intent = obj.get("intent") if isinstance(obj.get("intent"), str) else "qa"
        if intent not in ["qa", "proposal", "gap_analysis"]:
            intent = "qa"
        needs_multistep = obj.get("needs_multistep")
        if not isinstance(needs_multistep, bool):
            needs_multistep = should_use_multistep(query)
        needs_gap_analysis = obj.get("needs_gap_analysis")
        if not isinstance(needs_gap_analysis, bool):
            needs_gap_analysis = True
        notes = obj.get("notes") if isinstance(obj.get("notes"), str) else ""
        return {"intent": intent, "needs_multistep": needs_multistep, "needs_gap_analysis": needs_gap_analysis, "notes": notes}
    except Exception:
        return {"intent": "qa", "needs_multistep": should_use_multistep(query), "needs_gap_analysis": True, "notes": ""}
