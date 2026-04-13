import json
import os
import re
import unicodedata
from typing import List, Optional
import asyncio
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential_jitter, retry_if_exception


def role_level(role: str) -> int:
    r = (role or "").strip()
    if r.lower() == "admin":
        r = "SuperManager"
    levels = {"Employee": 1, "Lead": 2, "Manager": 3, "SuperManager": 4}
    return levels.get(r, 0)

def allowed_roles_for(user_role: str) -> List[str]:
    order = [("Employee", 1), ("Lead", 2), ("Manager", 3), ("SuperManager", 4)]
    lvl = role_level(user_role)
    return [name for (name, l) in order if l <= lvl]


def coerce_llm_content_to_text(content) -> str:
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


def detect_language(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "vi"
    if re.search(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", q, flags=re.IGNORECASE):
        return "vi"
    ql = q.lower()
    if re.search(r"\b(và|là|của|không|cần|hãy|vui lòng|tôi|bạn|ở đâu|như thế nào)\b", ql):
        return "vi"
    return "en"


def i18n(lang: str) -> dict:
    if lang == "en":
        return {
            "no_internal_data": "Relevant knowledge for this topic will be added shortly.",
            "followup_intro": "Relevant knowledge for this topic will be added shortly.",
            "followup_prompt": "To continue, please answer these questions:",
            "summary_title": "Quick summary:",
            "details_title": "Details:",
            "no_markdown": "Do not use Markdown formatting."
        }
    return {
        "no_internal_data": "Kiến thức liên quan tới chủ đề này sẽ được bổ sung trong thời gian ngắn.",
        "followup_intro": "Kiến thức liên quan tới chủ đề này sẽ được bổ sung trong thời gian ngắn.",
        "followup_prompt": "Để tiếp tục, vui lòng trả lời các câu hỏi sau:",
        "summary_title": "Tóm tắt nhanh:",
        "details_title": "Chi tiết:",
        "no_markdown": "Không dùng Markdown."
    }


def normalize_for_match(text: str) -> str:
    t = (text or "").lower()
    t = unicodedata.normalize("NFKD", t)
    t = t.encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return t.strip()


def tokenize(text: str) -> List[str]:
    t = normalize_for_match(text)
    if not t:
        return []
    return [p for p in t.split() if len(p) >= 2]


def extract_first_json_value(text: str) -> Optional[str]:
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


def try_parse_json_object(text: str) -> Optional[dict]:
    j = extract_first_json_value(text)
    if not j or not j.startswith("{"):
        return None
    try:
        obj = json.loads(j)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None


async def invoke_llm(llm, prompt):
    attempts = 3
    try:
        attempts = int(os.getenv("LLM_RETRY_ATTEMPTS", "3") or "3")
    except Exception:
        attempts = 3
    attempts = max(1, min(attempts, 5))
    try:
        timeout_s = float(os.getenv("LLM_TIMEOUT_SECONDS", "45") or "45")
    except Exception:
        timeout_s = 45.0
    timeout_s = max(3.0, min(timeout_s, 600.0))

    def _is_retryable_exception(e: Exception) -> bool:
        if isinstance(e, ValueError):
            return False
        name = type(e).__name__.lower()
        msg = str(e).lower()
        if any(k in name for k in ["ratelimit", "timeout", "temporar", "serviceunavailable", "connection", "http"]):
            return True
        if any(k in msg for k in ["429", "rate limit", "timeout", "temporarily", "unavailable", "connection reset", "connection aborted", "server error", "503", "500"]):
            return True
        return True

    async def _call_once():
        if hasattr(llm, "ainvoke"):
            return await asyncio.wait_for(llm.ainvoke(prompt), timeout=timeout_s)
        return await asyncio.wait_for(asyncio.to_thread(lambda: llm.invoke(prompt)), timeout=timeout_s)

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=0.6, max=6.0),
        retry=retry_if_exception(_is_retryable_exception),
        reraise=True,
    ):
        with attempt:
            return await _call_once()


async def astream_llm_with_retry(llm, prompt):
    if not hasattr(llm, "astream"):
        return None
    attempts = 3
    try:
        attempts = int(os.getenv("LLM_RETRY_ATTEMPTS", "3") or "3")
    except Exception:
        attempts = 3
    attempts = max(1, min(attempts, 5))
    try:
        timeout_s = float(os.getenv("LLM_TIMEOUT_SECONDS", "45") or "45")
    except Exception:
        timeout_s = 45.0
    timeout_s = max(3.0, min(timeout_s, 600.0))

    def _is_retryable_exception(e: Exception) -> bool:
        if isinstance(e, ValueError):
            return False
        name = type(e).__name__.lower()
        msg = str(e).lower()
        if any(k in name for k in ["ratelimit", "timeout", "temporar", "serviceunavailable", "connection", "http"]):
            return True
        if any(k in msg for k in ["429", "rate limit", "timeout", "temporarily", "unavailable", "connection reset", "connection aborted", "server error", "503", "500"]):
            return True
        return True

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=0.6, max=6.0),
        retry=retry_if_exception(_is_retryable_exception),
        reraise=True,
    ):
        with attempt:
            stream = llm.astream(prompt)
            first = await asyncio.wait_for(stream.__anext__(), timeout=timeout_s)

            async def _combined():
                yield first
                async for c in stream:
                    yield c

            return _combined()
