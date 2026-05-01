"""
AIIterate AI Engine
Supports dynamic LLM configuration via settings, Tavily web search, and multi-provider routing.
"""
import json
from pathlib import Path

import aiohttp

# Module-level HTTP session for connection reuse
_http_session: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    """Get or create a reusable aiohttp session."""
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=90)
        )
    return _http_session


async def close_http_session():
    """Close the module-level HTTP session (call on shutdown)."""
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None


def _extract_json_block(raw: str) -> dict | None:
    """从 AI 原始输出中提取第一个完整 JSON 对象。

    处理嵌套对象、JSON 字符串内的花括号与转义字符；若前面出现坏 JSON，
    继续扫描后续对象，避免一次噪声导致整个评估 fallback。
    """
    depth = 0
    start = -1
    in_string = False
    escape = False

    for i, ch in enumerate(raw):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}' and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(raw[start:i+1])
                except json.JSONDecodeError:
                    start = -1
                    in_string = False
                    escape = False
                    continue
    return None


# ── Dynamic LLM router ────────────────────────────────────

def _resolve_llm_config(role: str = "default") -> dict:
    """
    读取 settings，解析 LLM 配置。
    优先级：role 级 > default 级。
    返回 {provider, base_url, api_key, model}
    settings 结构：
      { "llm": { "provider":"", "base_url":"", "api_key":"", "model":"",
                 "roles": { "answer": {...}, ... } } }
    """
    import aiterate_db as db
    settings = db.get_settings()
    llm = settings.get("llm") or {}

    default = {
        "provider": llm.get("provider", ""),
        "base_url":  llm.get("base_url",  ""),
        "api_key":   llm.get("api_key",   ""),
        "model":     llm.get("model",     ""),
    }

    if role != "default":
        role_cfg = (llm.get("roles") or {}).get(role, {})
        merged = {
            "provider": role_cfg.get("provider") or default["provider"],
            "base_url":  role_cfg.get("base_url")  or default["base_url"],
            "api_key":   role_cfg.get("api_key")   or default["api_key"],
            "model":     role_cfg.get("model")     or default["model"],
        }
    else:
        merged = default

    return {
        "provider": merged["provider"],
        "base_url":  (merged["base_url"] or "").rstrip("/"),
        "api_key":   merged["api_key"],
        "model":     merged["model"],
    }


async def _call_llm(messages: list, temperature: float = 0.7, max_tokens: int | None = None,
                    role: str = "default") -> str:
    cfg = _resolve_llm_config(role)
    provider = cfg["provider"]
    api_key  = cfg["api_key"]
    base_url = cfg["base_url"]
    model    = cfg["model"]

    if not api_key:
        raise RuntimeError(f"No API key configured for LLM role={role} provider={provider}")

    timeout = aiohttp.ClientTimeout(total=90)

    # ── Anthropic ────────────────────────────────────────
    if provider == "anthropic":
        system_msgs = [m["content"] for m in messages if m["role"] == "system"]
        user_msgs   = [m for m in messages if m["role"] != "system"]
        payload = {
            "model":      model,
            "max_tokens": max_tokens or 4096,
            "messages":   user_msgs,
        }
        if system_msgs:
            payload["system"] = "\n".join(system_msgs)
        headers = {
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type":      "application/json",
        }
        url = f"{base_url}/messages"
        session = await _get_session()
        async with session.post(url, headers=headers, json=payload) as resp:
            raw_text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(f"Anthropic API {resp.status}: {raw_text[:800]}")
            try:
                data = json.loads(raw_text)
                return data["content"][0]["text"]
            except Exception as exc:
                raise RuntimeError(f"Unexpected Anthropic response: {raw_text[:800]}") from exc

    # ── OpenAI-compatible (deepseek / openai / gemini / openrouter / custom) ──
    payload = {
        "model":       model,
        "messages":    messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    url = f"{base_url}/chat/completions"
    session = await _get_session()
    async with session.post(url, headers=headers, json=payload) as resp:
        raw_text = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"LLM API {resp.status}: {raw_text[:800]}")
        try:
            data = json.loads(raw_text)
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError(f"Unexpected LLM response: {raw_text[:800]}") from exc


# ── Tavily web search ─────────────────────────────────────

def _clean_search_query(question: str) -> str:
    """从用户输入中提取干净的搜索关键词，去掉大段引用和噪声。"""
    # 取第一段——遇到引用分隔符或空行就截断
    for sep in ['下面是原文', '原文如下', '以下是原文', '下面是', '\n\n', '\n']:
        idx = question.find(sep)
        if idx > 10:  # 至少保留 10 个字
            question = question[:idx].strip()
            break
    # 截断到 ~120 字，太长的 query 对 Tavily 效果差
    if len(question) > 120:
        question = question[:120].rsplit('，', 1)[0].rsplit('。', 1)[0]
    return question.strip()


async def tavily_search(query: str) -> str:
    """调用 Tavily API 搜索，返回摘要文本（用于注入 prompt）"""
    import aiterate_db as db
    settings = db.get_settings()
    api_key = settings.get("tavily_api_key", "")
    if not api_key:
        raise RuntimeError("Tavily API key not configured")

    payload = {
        "api_key":      api_key,
        "query":        query,
        "search_depth": "basic",
        "max_results":  5,
    }
    timeout = aiohttp.ClientTimeout(total=30)
    session = await _get_session()
    async with session.post("https://api.tavily.com/search", json=payload) as resp:
        raw_text = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"Tavily API {resp.status}: {raw_text[:400]}")
        data = json.loads(raw_text)
        results = data.get("results", [])
        snippets = [r.get("content", "") for r in results if r.get("content")]
        return "\n\n".join(snippets[:5])


# ── 阶段1：生成初始完整答案 ────────────────────────────

ANSWER_SYSTEM = """你是一位知识渊博的导师。用户提出了一个问题或观点，你需要给出详细、完整的解答。

要求：
- 问题类型：给出清晰完整的答案，从基础到深入，用例子辅助说明
- 观点类型：分析这个观点的合理性、背景、相关知识，给出全面评价
- 语言简洁有力，结构清晰（可以用小标题或分点）
- 长度：300-600字，确保覆盖核心要点
- 结尾不要追问用户，只给答案"""

async def generate_title(content: str) -> str:
    """从用户输入的完整内容里提取一个简短标题（≤20字）"""
    messages = [
        {"role": "system", "content": "你是一个标题生成助手。用户输入一段问题或观点，你只需要输出一个简短的标题，不超过20个汉字，不加引号，不加任何解释，只输出标题本身。"},
        {"role": "user",   "content": content},
    ]
    raw = await _call_llm(messages, temperature=0.3, max_tokens=60, role="title")
    return raw.strip().strip('"').strip('《》').strip()[:40]


INBOX_QUESTION_SYSTEM = """你是一个“问题生成教练”，不是问答助手。

用户会给你一个词、短语、句子、摘录、聊天片段或临时想法。这些素材可能很零散，用户自己还没有形成明确问题。

你的任务：
1. 从素材中识别值得深入研究的概念、矛盾、假设和边界。
2. 生成 5 个高质量研究问题。
3. 每个问题都要能进入后续学习、深化和费曼检验。
4. 问题要具体、可探究、有张力，避免空泛。
5. 不要直接回答问题。
6. 不要生成鸡汤式问题。

好问题标准：
- 能揭示概念背后的机制
- 能连接多个知识域
- 能挑战用户原有假设
- 能引出可验证的理解
- 能推动用户形成更稳定的认知结构

尽量覆盖不同问题类型：概念澄清型、机制解释型、边界条件型、反常识型、连接迁移型。
输出严格 JSON：
{
  "questions": [
    {
      "question": "问题文本",
      "why": "为什么这个问题值得研究",
      "angle": "哲学 / 心理学 / 技术 / 写作 / 生活 / 跨学科",
      "depth": "low / medium / high",
      "related_concepts": ["概念1", "概念2"],
      "suggested_type": "question"
    }
  ]
}"""


async def generate_inbox_questions(content: str, direction: str | None = None) -> dict:
    """把用户随手收集的碎片素材转化为候选研究问题。"""
    direction_line = f"\n用户希望这次问题更偏向：{direction}" if direction else ""
    prompt = f"""用户素材：
{content}
{direction_line}

请生成 5 个值得研究的问题。"""
    messages = [
        {"role": "system", "content": INBOX_QUESTION_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    raw = await _call_llm(messages, temperature=0.65, max_tokens=2048, role="question")
    result = _extract_json_block(raw)
    if not result or not isinstance(result.get("questions"), list):
        return {"questions": [], "raw": raw, "parse_failed": True}

    normalized = []
    for item in result.get("questions", [])[:8]:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        concepts = item.get("related_concepts") or []
        if not isinstance(concepts, list):
            concepts = []
        normalized.append({
            "question": question,
            "why": str(item.get("why") or "").strip(),
            "angle": str(item.get("angle") or "跨学科").strip() or "跨学科",
            "depth": str(item.get("depth") or "medium").strip() or "medium",
            "related_concepts": [str(c).strip() for c in concepts if str(c).strip()][:8],
            "suggested_type": str(item.get("suggested_type") or "question").strip() or "question",
        })
    return {"questions": normalized, "raw": raw, "parse_failed": False}


async def generate_initial_answer(title: str, content: str, type: str = "question",
                                   web_search: bool = False,
                                   knowledge_node: dict | None = None) -> dict:
    # title 可能是完整问题（新模式）或简短标题（旧模式），content 可能为空
    question = title if not content else (title if len(title) > len(content) else content)

    system_prompt = ANSWER_SYSTEM

    # 注入知识节点上下文
    if knowledge_node:
        kn_title = knowledge_node.get("title", "")
        kn_keywords = knowledge_node.get("keywords", [])
        kn_fragments = knowledge_node.get("prompt_fragments", [])
        kn_context = f"\n\n【知识领域】{kn_title}"
        if kn_keywords:
            kn_context += f"\n核心概念：{'、'.join(kn_keywords)}"
        if kn_fragments:
            kn_context += f"\n关注角度：{'；'.join(kn_fragments[:2])}"
        system_prompt = ANSWER_SYSTEM + kn_context + "\n\n请在回答中覆盖以上核心概念，并体现相关角度的思考。"

    if web_search:
        try:
            clean_query = _clean_search_query(question)
            search_results = await tavily_search(clean_query)
            system_prompt = (
                ANSWER_SYSTEM
                + f"\n\n【联网搜索参考资料】\n{search_results}\n\n请结合以上最新资料给出答案，可以引用具体信息，但要用自己的语言组织。"
            )
        except Exception as e:
            # 搜索失败不影响正常回答
            system_prompt = ANSWER_SYSTEM + f"\n\n（联网搜索失败：{e}，以下基于内部知识作答）"

    if type == "viewpoint":
        prompt = f"观点：{question}\n\n请对这个观点进行全面分析和评价。"
    else:
        prompt = f"问题：{question}\n\n请给出详细完整的答案。"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": prompt},
    ]
    raw = await _call_llm(messages, temperature=0.5, role="answer")
    return {"answer": raw}


# ── 阶段2a：评估用户总结 ───────────────────────────────

TAKE_EVAL_SYSTEM = """你是一位严格的学习导师，正在评估学习者对知识的内化程度。

用户阅读了关于某个问题/观点的详细解答后，写了自己的总结。请评估：
1. 用户是否抓住了核心要点？
2. 有没有理解错误或遗漏？
3. 理解深度如何？

输出JSON：
{
  "score": <0-100整数，60以上=基本理解，80以上=深入理解>,
  "understood_well": <true/false>,
  "praise": "<1句真实的肯定，不要夸张>",
  "gaps": ["<遗漏或误解1>", "<遗漏或误解2>"],
  "verdict": "<50字内总体评价>"
}"""

async def evaluate_user_take(original_question: str, ai_answer: str, user_take: str) -> dict:
    prompt = f"""原始问题/观点：{original_question}

AI的完整回答：
{ai_answer[:800]}

用户的理解：
{user_take}

请评估用户的理解是否准确，有无偏差。""" 

    messages = [
        {"role": "system", "content": TAKE_EVAL_SYSTEM},
        {"role": "user",   "content": prompt},
    ]
    raw = await _call_llm(messages, temperature=0.3, max_tokens=600, role="evaluate")
    try:
        result = _extract_json_block(raw)
        if result is None:
            raise ValueError("parse failed")
        return {
            "score":          int(result.get("score", 50)),
            "understood_well": bool(result.get("understood_well", False)),
            "praise":         result.get("praise", ""),
            "gaps":           result.get("gaps", []),
            "verdict":        result.get("verdict", ""),
            "raw":            raw,
        }
    except Exception:
        return {"score": 50, "understood_well": False, "praise": "", "gaps": [], "verdict": "评估解析失败",
                "raw": raw, "parse_failed": True}


# ── 阶段2b：回答用户追问 ───────────────────────────────

FOLLOWUP_ANSWER_SYSTEM = """你是一位耐心的导师，正在回答学习者的追问。

用户已经阅读了初始答案，现在有进一步的疑问。请：
- 直接、完整地回答这个追问
- 联系初始内容，帮助用户建立更深的理解
- 200-400字，清晰简洁
- 结尾不要再追问"""

async def answer_followup_question(original_question: str, ai_answer: str, press_input: str,
                                   history: list = None, web_search: bool = False) -> dict:
    history_text = ""
    if history:
        for h in history[-3:]:
            history_text += f"\n之前的追问：{h.get('question', '')}\n回答：{h.get('answer', '')[:200]}\n"

    system_prompt = FOLLOWUP_ANSWER_SYSTEM

    # 如果初始选了联网搜索，追问也联网
    if web_search:
        try:
            clean_query = _clean_search_query(press_input)
            search_results = await tavily_search(clean_query)
            system_prompt = (
                FOLLOWUP_ANSWER_SYSTEM
                + f"\n\n【联网搜索参考资料】\n{search_results}\n\n请结合以上最新资料回答追问。"
            )
        except Exception:
            pass

    prompt = f"""原始问题/观点：{original_question}
初始回答摘要：{ai_answer[:400]}
{history_text}
用户的追问：{press_input}

请回答这个追问。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": prompt},
    ]
    raw = await _call_llm(messages, temperature=0.5, role="deepen")
    return {"answer": raw}


# ── 阶段3：生成费曼题 ─────────────────────────────────

REVIEW_GEN_SYSTEM = """你是一位费曼式导师，要通过提问来检验学习者是否真正理解了知识。

根据问题/观点及其完整讨论，生成2-3个检验题。要求：
- 题目需要学习者用自己的话解释（不能直接搜索到的答案）
- 覆盖最核心的2-3个知识点
- 难度适中，不刁钻

输出JSON：
{
  "questions": ["<检验题1>", "<检验题2>", "<检验题3>"]
}"""

async def generate_review_questions(original_question: str, ai_answer: str, learning_history: str,
                                   knowledge_node: dict | None = None) -> dict:
    prompt = f"""主题：{original_question}
核心内容摘要：{ai_answer[:600]}
学习过程摘要：{learning_history[:400]}"""

    # 注入知识节点上下文，要求覆盖关键概念
    if knowledge_node:
        kn_title = knowledge_node.get("title", "")
        kn_keywords = knowledge_node.get("keywords", [])
        kn_fragments = knowledge_node.get("prompt_fragments", [])
        prompt += f"""
知识领域：{kn_title}
核心概念：{'、'.join(kn_keywords) if kn_keywords else '无'}
关注角度：{'；'.join(kn_fragments[:2]) if kn_fragments else '无'}
请生成2-3个费曼式检验题，确保覆盖以上核心概念。"""

    prompt += "\n\n请生成2-3个费曼式检验题。"

    messages = [
        {"role": "system", "content": REVIEW_GEN_SYSTEM},
        {"role": "user",   "content": prompt},
    ]
    raw = await _call_llm(messages, temperature=0.5, max_tokens=800, role="review")
    try:
        result = _extract_json_block(raw)
        if result is None:
            raise ValueError("parse failed")
        return {"questions": result.get("questions", []) or []}
    except Exception:
        return {"questions": ["用自己的话解释这个概念的核心是什么？"], "parse_failed": True}


# ── 阶段2c：推荐深化追问 ─────────────────────────────

SUGGEST_DEEPEN_SYSTEM = """你是一位学习引导专家。根据学习者当前暴露的薄弱点，生成2-3个具体的追问建议。

要求：
- 每个建议要直击薄弱点的核心
- 追问应该是学习者可以深度思考的开放式问题
- 例子：「举一个反例说明这个概念在什么情况下不适用」「用真实项目的场景套一下这个概念」
- 每个建议不超过25字

输出JSON：
{
  "suggestions": ["<建议1>", "<建议2>", "<建议3>"]
}"""

async def suggest_deepen_prompts(original_question: str, gaps: list[str]) -> dict:
    if not gaps:
        return {"suggestions": []}

    prompt = f"""主题：{original_question}

学习者暴露的薄弱点：
{chr(10).join(f'- {g}' for g in gaps)}

请针对这些薄弱点，给出2-3个具体的追问建议。"""

    messages = [
        {"role": "system", "content": SUGGEST_DEEPEN_SYSTEM},
        {"role": "user",   "content": prompt},
    ]
    raw = await _call_llm(messages, temperature=0.5, max_tokens=600, role="deepen")
    try:
        result = _extract_json_block(raw)
        if result is None:
            raise ValueError("parse failed")
        return {"suggestions": result.get("suggestions", [])[:3]}
    except Exception:
        return {"suggestions": []}


# ── 阶段3：评估费曼回答 ───────────────────────────────

REVIEW_EVAL_SYSTEM = """你是一位考官，正在评估学习者的费曼检验回答质量，给出逐题评价和整体评分。

输出JSON：
{
  "item_scores": [
    {
      "score": <0-100整数>,
      "comment": "<50字内：指出回答的亮点、不足，或可以继续完善的角度>"
    }
  ],
  "final_score": <0-100整数，所有题目的综合得分>,
  "mastery_level": "<入门|理解|掌握|精通>",
  "strong_points": ["<理解到位的点1>", "<理解到位的点2>"],
  "weak_points": ["<还需加强的点1>"],
  "final_summary": "<100字内的整体学习评价>"
}

item_scores 数组长度必须与题目数量完全一致。"""

async def evaluate_review_answers(original_question: str, review_questions: list, review_answers: list,
                                   web_search: bool = False) -> dict:
    qa_pairs = "\n".join([f"题目：{q}\n回答：{a}" for q, a in zip(review_questions, review_answers)])
    prompt = f"""主题：{original_question}

费曼问答：
{qa_pairs}

请评估学习者的掌握程度。"""

    system_prompt = REVIEW_EVAL_SYSTEM

    if web_search:
        try:
            clean_query = _clean_search_query(original_question)
            search_results = await tavily_search(clean_query)
            system_prompt = (
                REVIEW_EVAL_SYSTEM
                + f"\n\n【联网搜索参考资料】\n{search_results}\n\n请结合以上最新资料评估学习者的回答准确性和深度。"
            )
        except Exception:
            pass

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": prompt},
    ]
    raw = await _call_llm(messages, temperature=0.3, max_tokens=600, role="review")
    try:
        result = _extract_json_block(raw)
        if result is None:
            raise ValueError("parse failed")
        return {
            "item_scores":   result.get("item_scores", []),
            "final_score":   int(result.get("final_score", 50)),
            "mastery_level": result.get("mastery_level", "理解"),
            "strong_points": result.get("strong_points", []),
            "weak_points":   result.get("weak_points", []),
            "final_summary": result.get("final_summary", ""),
            "raw":           raw,
        }
    except Exception:
        return {"item_scores": [], "final_score": 50, "mastery_level": "理解", "strong_points": [],
                "weak_points": [], "final_summary": "评估解析失败", "raw": raw, "parse_failed": True}


# ── Phase 4.2: Rubric 版本化 ───────────────────────────────

def _resolve_rubric(role: str) -> str:
    """从 DB 读取指定 role 的评分标准（支持用户自定义）。"""
    import aiterate_db as db
    rubric = db.get_rubric(role)
    return rubric.get("content", "")


async def evaluate_review_re_explanation(original_question: str, ai_material: str,
                                          user_explanation: str) -> dict:
    """Phase 4.2: Evaluate a user's re-explanation during spaced repetition review.
    
    使用 DB 中配置的 review_explain rubric（可自定义版本化）。
    """
    rubric = _resolve_rubric("review_explain") or (
        "你是一位学习导师，评估学习者的间隔复习效果。输出 JSON：{score, praise, gap, verdict}"
    )
    prompt = f"""原始问题：
{original_question}

学习材料（AI 原始回答）：
{ai_material[:2000]}

学习者的重新解释：
{user_explanation}

请评估学习者在间隔复习中的表现。"""

    messages = [
        {"role": "system", "content": rubric},
        {"role": "user", "content": prompt},
    ]
    raw = await _call_llm(messages, temperature=0.3, max_tokens=400, role="review")
    try:
        result = _extract_json_block(raw)
        if result is None:
            raise ValueError("parse failed")
        return {
            "score": int(result.get("score", 50)),
            "praise": result.get("praise", ""),
            "gap": result.get("gap", ""),
            "verdict": result.get("verdict", ""),
            "raw": raw,
        }
    except Exception:
        return {"score": 50, "praise": "", "gap": "", "verdict": "评估解析失败",
                "raw": raw, "parse_failed": True}


