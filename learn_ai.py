"""
LearnSystem AI Engine
Supports dynamic LLM configuration via settings, Tavily web search, and multi-provider routing.
"""
import json
import os
from datetime import date, timedelta
from pathlib import Path

import aiohttp

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))

DOMAIN_CONTEXT = {
    "cs":    "计算机科学、编程、系统设计、算法、AI工程",
    "write": "写作、表达、文章结构、语言风格、技术写作",
    "psych": "心理学、认知科学、行为分析、情绪管理、人际关系",
    "phil":  "哲学、逻辑推理、伦理学、形而上学、认识论",
}

DOMAIN_NAMES = {
    "cs":    "计算机",
    "write": "写作",
    "psych": "心理学",
    "phil":  "哲学",
}


def _extract_json_block(raw: str, open_char: str, close_char: str) -> str | None:
    start = raw.find(open_char)
    end   = raw.rfind(close_char)
    if start == -1 or end == -1 or end <= start:
        return None
    return raw[start:end + 1]


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
    import learn_db as db
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


async def _call_llm(messages: list, temperature: float = 0.7, max_tokens: int = 1500,
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
            "max_tokens": max_tokens,
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
        async with aiohttp.ClientSession(timeout=timeout) as session:
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
        "max_tokens":  max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    url = f"{base_url}/chat/completions"
    async with aiohttp.ClientSession(timeout=timeout) as session:
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

async def tavily_search(query: str) -> str:
    """调用 Tavily API 搜索，返回摘要文本（用于注入 prompt）"""
    import learn_db as db
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
    async with aiohttp.ClientSession(timeout=timeout) as session:
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


async def generate_initial_answer(title: str, content: str, type: str = "question",
                                   web_search: bool = False) -> dict:
    # title 可能是完整问题（新模式）或简短标题（旧模式），content 可能为空
    question = title if not content else (title if len(title) > len(content) else content)

    system_prompt = ANSWER_SYSTEM

    if web_search:
        try:
            search_results = await tavily_search(question)
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
    raw = await _call_llm(messages, temperature=0.5, max_tokens=1200, role="answer")
    return {"answer": raw}


# ── 阶段2a：评估用户总结 ───────────────────────────────

SUMMARY_EVAL_SYSTEM = """你是一位严格的学习导师，正在评估学习者对知识的内化程度。

用户阅读了关于某个问题/观点的详细解答后，写了自己的总结。请评估：
1. 用户是否抓住了核心要点？
2. 有没有理解错误或遗漏？
3. 理解深度如何？

输出JSON：
{
  "score": <1-5整数>,
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
        block  = _extract_json_block(raw, "{", "}")
        result = json.loads(block)
        return {
            "score":          int(result.get("score", 3)),
            "understood_well": bool(result.get("understood_well", False)),
            "praise":         result.get("praise", ""),
            "gaps":           result.get("gaps", []),
            "verdict":        result.get("verdict", ""),
            "raw":            raw,
        }
    except Exception:
        return {"score": 3, "understood_well": False, "praise": "", "gaps": [], "verdict": "评估解析失败", "raw": raw}


# ── 阶段2b：回答用户追问 ───────────────────────────────

FOLLOWUP_ANSWER_SYSTEM = """你是一位耐心的导师，正在回答学习者的追问。

用户已经阅读了初始答案，现在有进一步的疑问。请：
- 直接、完整地回答这个追问
- 联系初始内容，帮助用户建立更深的理解
- 200-400字，清晰简洁
- 结尾不要再追问"""

async def answer_followup_question(original_question: str, ai_answer: str, press_input: str, history: list = None) -> dict:
    history_text = ""
    if history:
        for h in history[-3:]:
            history_text += f"\n之前的追问：{h.get('question', '')}\n回答：{h.get('answer', '')[:200]}\n"

    prompt = f"""原始问题/观点：{original_question}
初始回答摘要：{ai_answer[:400]}
{history_text}
用户的追问：{press_input}

请回答这个追问。"""

    messages = [
        {"role": "system", "content": FOLLOWUP_ANSWER_SYSTEM},
        {"role": "user",   "content": prompt},
    ]
    raw = await _call_llm(messages, temperature=0.5, max_tokens=800, role="default")
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

async def generate_review_questions(original_question: str, ai_answer: str, learning_history: str) -> dict:
    prompt = f"""主题：{original_question}
核心内容摘要：{ai_answer[:600]}
学习过程摘要：{learning_history[:400]}

请生成2-3个费曼式检验题。"""

    messages = [
        {"role": "system", "content": REVIEW_GEN_SYSTEM},
        {"role": "user",   "content": prompt},
    ]
    raw = await _call_llm(messages, temperature=0.5, max_tokens=400, role="review")
    try:
        block  = _extract_json_block(raw, "{", "}")
        result = json.loads(block)
        return {"questions": result.get("questions", []) or []}
    except Exception:
        return {"questions": ["用自己的话解释这个概念的核心是什么？"]}


# ── 阶段3：评估费曼回答 ───────────────────────────────

REVIEW_EVAL_SYSTEM = """你是一位考官，正在评估学习者的费曼检验回答质量，给出最终学习评价。

输出JSON：
{
  "final_score": <1-5整数>,
  "mastery_level": "<入门|理解|掌握|精通>",
  "strong_points": ["<理解到位的点1>", "<理解到位的点2>"],
  "weak_points": ["<还需加强的点1>"],
  "final_summary": "<100字内的整体学习评价>"
}"""

async def evaluate_review_answers(original_question: str, review_questions: list, review_answers: list) -> dict:
    qa_pairs = "\n".join([f"题目：{q}\n回答：{a}" for q, a in zip(review_questions, review_answers)])
    prompt = f"""主题：{original_question}

费曼问答：
{qa_pairs}

请评估学习者的掌握程度。"""

    messages = [
        {"role": "system", "content": REVIEW_EVAL_SYSTEM},
        {"role": "user",   "content": prompt},
    ]
    raw = await _call_llm(messages, temperature=0.3, max_tokens=600, role="review")
    try:
        block  = _extract_json_block(raw, "{", "}")
        result = json.loads(block)
        return {
            "final_score":   int(result.get("final_score", 3)),
            "mastery_level": result.get("mastery_level", "理解"),
            "strong_points": result.get("strong_points", []),
            "weak_points":   result.get("weak_points", []),
            "final_summary": result.get("final_summary", ""),
            "raw":           raw,
        }
    except Exception:
        return {"final_score": 3, "mastery_level": "理解", "strong_points": [], "weak_points": [], "final_summary": "评估解析失败", "raw": raw}


# ── 生成本周引导任务 ──────────────────────────────────

TASK_GEN_SYSTEM = """你是一位精准的学习规划师。根据用户在各领域的学习历史和当前材料，
生成本周最重要的4-6个学习任务。

任务必须：
- 具体可执行，不能模糊
- 有明确的输出（写什么、做什么、验证什么）
- 难度适中，不超过用户当前能力的20%
- 各领域均衡分配

严格输出JSON数组：
[
  {
    "domain_id": "<cs|write|psych|phil>",
    "task_type": "<read|feynman|write|project|connect|review>",
    "title": "<简短标题>",
    "description": "<2-3句具体说明>",
    "prompt": "<给用户的具体引导语，告诉他输出什么>",
    "priority": <1|2|3>
  }
]"""


async def generate_weekly_tasks(domains_data: list, recent_sessions: list) -> list:
    domain_summary = ""
    for d in domains_data:
        domain_summary += f"\n{d['name']}：当前材料={d.get('current_material', '未设置')}，"
        domain_summary += f"进度={d.get('done_units', 0)}/{max(d.get('total_units', 0), 1)} 单元，"
        domain_summary += f"周目标={d.get('weekly_goal_minutes', 60)} 分钟"

    session_summary = ""
    for s in recent_sessions[:10]:
        session_summary += (
            f"\n- {s.get('type', 'question')}: {s.get('title', '')} "
            f"(评分:{s.get('score', '?')}, 状态:{s.get('status', '?')})" 
        )

    today    = date.today().isoformat()
    week_end = (date.today() + timedelta(days=7)).isoformat()

    user_msg = f"""今天是 {today}，本周结束日期 {week_end}。

当前学习材料：{domain_summary}

最近学习记录：{session_summary if session_summary else '暂无'}

请生成本周 4-6 个引导任务，尽量覆盖四个领域。"""

    messages = [
        {"role": "system", "content": TASK_GEN_SYSTEM},
        {"role": "user",   "content": user_msg},
    ]

    raw = await _call_llm(messages, temperature=0.6, max_tokens=1500, role="default")
    try:
        block = _extract_json_block(raw, "[", "]")
        if not block:
            raise ValueError("JSON array not found")
        tasks = json.loads(block)
        if not isinstance(tasks, list):
            raise ValueError("Tasks payload is not a list")
        return tasks
    except Exception:
        return []
