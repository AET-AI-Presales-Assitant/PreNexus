from .common import coerce_llm_content_to_text, invoke_llm


def draft_ideal_answer_for_retrieval(llm, query: str, history_text: str, lang: str) -> str:
    if lang == "en":
        prompt = f"""
            You are a Retrieval Expander. Write a neutral "query expansion description" to help search internal documents.
            Requirements:
            - 4–8 sentences, concise.
            - Prefer listing keywords and entities: customers, industries, projects, technologies, deliverables, KPIs, timeline, geography, teams/roles.
            - Do NOT claim facts as true; do NOT use first person; do NOT use phrases like "I assume".
            - No Markdown.
            Conversation history (if any): {history_text or "None."}
            User query: {query}
            Expansion:
        """
    else:
        prompt = f"""
            Bạn là “Retrieval Expander”. Hãy viết một đoạn “mô tả truy vấn mở rộng” để giúp tìm tài liệu nội bộ, KHÔNG khẳng định là sự thật.
            YÊU CẦU:
            - 4–8 câu, ưu tiên liệt kê từ khoá/đối tượng: khách hàng, ngành, dự án, công nghệ, deliverables, KPI, timeline, địa danh, team/role.
            - Không dùng ngôi “tôi”, không dùng lời khẳng định chắc chắn, không dùng “tôi giả định”.
            - Không Markdown.
            Lịch sử hội thoại (nếu có): {history_text or "Không có."}
            Câu hỏi: {query}
            Đoạn mở rộng:
        """
    try:
        msg = llm.invoke(prompt)
        t = coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg).strip()
        return t
    except Exception:
        return ""


def rewrite_query_for_retrieval(llm, query: str) -> str:
    prompt = f"""
        You are a Query Rewriter for internal document search. Rewrite the query to improve retrieval.
        Rules:
        - Keep the original intent; do NOT add new facts.
        - Add helpful synonyms/variants (VN/EN) only if consistent with the original query.
        - Output ONLY one line of text (no quotes, no explanation).
        Original query: {query}
        Rewritten query:
    """
    try:
        msg = llm.invoke(prompt)
        text = coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        return text.strip()
    except Exception:
        return ""


async def draft_ideal_answer_for_retrieval_async(llm, query: str, history_text: str, lang: str) -> str:
    if lang == "en":
        prompt = f"""
        You are a Retrieval Expander. Write a neutral "query expansion description" to help search internal documents.
        Requirements:
        - 4–8 sentences, concise.
        - Prefer listing keywords and entities: customers, industries, projects, technologies, deliverables, KPIs, timeline, geography, teams/roles.
        - Do NOT claim facts as true; do NOT use first person; do NOT use phrases like "I assume".
        - No Markdown.
        Conversation history (if any): {history_text or "None."}
        User query: {query}
        Expansion:
        """
    else:
        prompt = f"""
        Bạn là “Retrieval Expander”. Hãy viết một đoạn “mô tả truy vấn mở rộng” để giúp tìm tài liệu nội bộ, KHÔNG khẳng định là sự thật.
        YÊU CẦU:
        - 4–8 câu, ưu tiên liệt kê từ khoá/đối tượng: khách hàng, ngành, dự án, công nghệ, deliverables, KPI, timeline, địa danh, team/role.
        - Không dùng ngôi “tôi”, không dùng lời khẳng định chắc chắn, không dùng “tôi giả định”.
        - Không Markdown.
        Lịch sử hội thoại (nếu có): {history_text or "Không có."}
        Câu hỏi: {query}
        Đoạn mở rộng:
        """
    try:
        msg = await invoke_llm(llm, prompt)
        t = coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg).strip()
        return t
    except Exception:
        return ""


async def rewrite_query_for_retrieval_async(llm, query: str) -> str:
    prompt = f"""
        You are a Query Rewriter for internal document search. Rewrite the query to improve retrieval.
        Rules:
        - Keep the original intent; do NOT add new facts.
        - Add helpful synonyms/variants (VN/EN) only if consistent with the original query.
        - Output ONLY one line of text (no quotes, no explanation).
        Original query: {query}
        Rewritten query:
    """
    try:
        msg = await invoke_llm(llm, prompt)
        text = coerce_llm_content_to_text(msg.content if hasattr(msg, "content") else msg)
        return text.strip()
    except Exception:
        return ""
