#!/usr/bin/env python3
"""
AIIterate 全流程回归测试
覆盖所有状态转换、边界情况、配置变更影响
用法: cd ~/vibe/aiterate && python tests/test_full_flow.py
"""

import json, time, sys, os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# 自动读取 admin token，适配 Phase 0 安全加固
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aiterate_db import get_settings

BASE = "http://192.168.31.222:7070"
ADMIN_TOKEN = get_settings().get("admin_token", "")
if not ADMIN_TOKEN:
    print("⚠️  admin_token 未配置！测试可能因 401 全部失败。")

passed = 0
failed = 0
SESSION_IDS = []  # 记住创建的 session，最后可以清理

# ── helpers ──────────────────────────────────────────────────────────────

def api(method, path, body=None, timeout=120):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if ADMIN_TOKEN:
        req.add_header("X-Admin-Token", ADMIN_TOKEN)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            if not raw.strip():
                return {}
            return json.loads(raw)
    except HTTPError as e:
        raw = e.read().decode()
        try:
            err = json.loads(raw)
            raise RuntimeError(f"HTTP {e.code}: {err.get('detail', raw[:200])}")
        except json.JSONDecodeError:
            raise RuntimeError(f"HTTP {e.code}: {raw[:200]}")
    except URLError as e:
        raise RuntimeError(f"Connection error: {e}")

def T(name, fn):
    """Run a test case. fn() raises on failure, returns debug info string on success."""
    global passed, failed
    try:
        info = fn()
        print(f"  ✅ {name}")
        if info:
            print(f"     {info}")
        passed += 1
        return info
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        failed += 1
        return None

def wait_until(session_id, target_statuses, max_wait=60):
    """Poll workspace until status is one of target_statuses."""
    target = set(target_statuses)
    for _ in range(max_wait // 2):
        ws = api("GET", f"/api/sessions/{session_id}/workspace")
        s = ws["session"]["status"]
        if s in target:
            return ws
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for status in {target_statuses}, got {s}")

def assert_eq(actual, expected, label=""):
    if actual != expected:
        raise AssertionError(f"{label} expected={expected}, got={actual}")

# ── Suite ────────────────────────────────────────────────────────────────

def test_00_setup_pass_score():
    """全局：设低通过分，确保流程测试不被 AI 评分随机性影响"""
    s = api("GET", "/api/settings")
    old = s.get("feynman_pass_score", 60)
    api("PATCH", "/api/settings", {"feynman_pass_score": 20})
    return f"set pass_score 20 (was {old})"

def test_01_health():
    """服务健康检查"""
    r = api("GET", "/healthz")
    assert_eq(r["service"], "aiterate", "service")
    assert_eq(r["ok"], True, "ok")

def test_02_settings_read():
    """读取设置"""
    r = api("GET", "/api/settings")
    assert "llm" in r
    assert ("tavily_api_key_masked" in r or "tavily_api_key" in r), f"missing tavily key, got keys={list(r.keys())}"
    assert "feynman_pass_score" in r

def test_03_stats_baseline():
    """统计接口正常"""
    r = api("GET", "/api/stats")
    assert "total_sessions" in r
    assert "completed_sessions" in r

def test_04_sessions_list():
    """Session 列表"""
    r = api("GET", "/api/sessions?limit=5")
    assert isinstance(r, list)

def test_05_404_session():
    """不存在的 session 返回 404"""
    try:
        api("GET", "/api/sessions/99999")
        raise AssertionError("Should have raised 404")
    except RuntimeError as e:
        if "404" not in str(e):
            raise

# ══════════════════════════════════════════════════════════════════════════
# Flow 1: 完美路径 — 费曼直接通过 → completed
# ══════════════════════════════════════════════════════════════════════════

def test_flow1_create():
    """Flow1: 创建 session"""
    r = api("POST", "/api/sessions", {
        "content": "什么是哈希表？请解释哈希函数、冲突解决（拉链法和开放寻址法）的核心原理。",
        "type": "question",
        "web_search": False
    })
    sid = r["session_id"]
    SESSION_IDS.append(sid)
    assert_eq(r["status"], "preparing", "init status")
    return f"sid={sid}"

def test_flow1_wait_answer():
    """Flow1: 等待 AI 回答 → learning"""
    sid = SESSION_IDS[-1]
    ws = wait_until(sid, {"learning", "error"})
    if ws["session"]["status"] == "error":
        raise RuntimeError(f"Answer generation failed: {ws['session'].get('error_msg','')}")
    assert len(ws["session"].get("material","")) > 100, "AI answer too short"
    return f"title={ws['session']['title']}, material={len(ws['session']['material'])} chars"

def test_flow1_take():
    """Flow1: 写理解"""
    sid = SESSION_IDS[-1]
    r = api("POST", f"/api/sessions/{sid}/deepen", {
        "action_type": "take",
        "content": "哈希表是通过哈希函数把 key 映射到数组索引的数据结构，实现 O(1) 查找。哈希函数要尽量均匀分布。冲突解决方法有两种：拉链法在每个槽位放链表，开放寻址法在数组中找下一个空位。拉链法更简单但对缓存不友好，开放寻址法内存连续但删除困难需要惰性删除标记。"
    })
    assert r["score"] >= 1, f"score too low: {r['score']}"
    return f"score={r['score']}, understood={r.get('understood_well')}"

def test_flow1_press():
    """Flow1: 追问"""
    sid = SESSION_IDS[-1]
    r = api("POST", f"/api/sessions/{sid}/deepen", {
        "action_type": "press",
        "content": "负载因子是什么？它如何影响哈希表的性能？"
    })
    assert len(r.get("answer","")) > 50, "press answer too short"
    return f"answer len={len(r['answer'])}"

def test_flow1_feynman_start():
    """Flow1: 开始费曼"""
    sid = SESSION_IDS[-1]
    r = api("POST", f"/api/sessions/{sid}/start-feynman")
    qs = r.get("questions", [])
    assert 2 <= len(qs) <= 3, f"expected 2-3 questions, got {len(qs)}"
    return f"{len(qs)} questions, group_id={r['group_id']}"

def test_flow1_feynman_pass():
    """Flow1: 费曼高质量回答 → 通过"""
    sid = SESSION_IDS[-1]
    # 取当前待答的 feynman group
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    group = ws.get("current_review_group", [])
    questions = [r["input"] for r in group]
    gid = group[0]["group_id"] if group else None
    assert gid, "no current feynman group"

    # 认真回答每一题
    answers = []
    for q in questions:
        answers.append(
            f"针对「{q}」的详细回答：这个问题涉及到数据结构设计的核心权衡。"
            f"从原理上讲，哈希表通过哈希函数将任意 key 映射到固定大小的数组索引，"
            f"理想情况下 O(1) 查找。但现实中哈希冲突不可避免。拉链法在每个槽位维护链表，"
            f"实现简单、删除方便，但指针追逐对 CPU 缓存不友好，内存碎片化严重。"
            f"开放寻址法则直接在数组中线性探测，内存连续、缓存友好，但删除需要惰性标记，"
            f"且负载因子高时性能急剧下降。工程实践中 Java HashMap 用拉链法+红黑树退化优化，"
            f"Python dict 用开放寻址+伪随机探测。选择取决于内存约束和访问模式。"
            f"负载因子是已用槽/总槽，超过阈值就扩容，是对空间换时间的参数化控制。"
            f"关键理解：没有完美的哈希函数，冲突解决策略是在均匀性、空间、速度三者间权衡。"
        )

    r = api("POST", f"/api/sessions/{sid}/complete-feynman", {
        "group_id": gid,
        "answers": answers
    })
    return f"score={r['final_score']}, passed={r['passed']}, status={r['new_status']}, mastery={r['mastery_level']}"

def test_flow1_verify_completed():
    """Flow1: 最终 workspace 应该是 completed"""
    sid = SESSION_IDS[-1]
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    status = ws["session"]["status"]
    assert_eq(status, "completed", "final status")
    assert ws["session"].get("score", 0) > 0, "should have final score"

# ══════════════════════════════════════════════════════════════════════════
# Flow 2: 费曼失败 → revising → 再深化 → 费曼再战 → 通过
# ══════════════════════════════════════════════════════════════════════════

def test_flow2_create():
    """Flow2: 创建 session"""
    r = api("POST", "/api/sessions", {
        "content": "解释 TCP 三次握手和四次挥手的过程，以及为什么需要这些步骤。",
        "type": "question",
        "web_search": False
    })
    SESSION_IDS.append(r["session_id"])
    return f"sid={r['session_id']}"

def test_flow2_wait_answer():
    sid = SESSION_IDS[-1]
    ws = wait_until(sid, {"learning", "error"})
    if ws["session"]["status"] == "error":
        raise RuntimeError(ws["session"].get("error_msg",""))
    return f"title={ws['session']['title']}"

def test_flow2_take():
    sid = SESSION_IDS[-1]
    r = api("POST", f"/api/sessions/{sid}/deepen", {
        "action_type": "take",
        "content": "三次握手是建立连接的过程，客户端发 SYN，服务端回 SYN-ACK，客户端再发 ACK。四次挥手是断开连接，因为 TCP 是全双工的，每方向都需要单独关闭。主动关闭方发 FIN，被动方回 ACK，然后被动方也发 FIN，主动方回 ACK 并进入 TIME_WAIT。"
    })
    return f"score={r['score']}"

def test_flow2_feynman_start():
    sid = SESSION_IDS[-1]
    r = api("POST", f"/api/sessions/{sid}/start-feynman")
    return f"{len(r['questions'])} questions"

def test_flow2_feynman_fail():
    """Flow2: 故意答得很差 → 费曼不通过"""
    sid = SESSION_IDS[-1]
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    group = ws.get("current_review_group", [])
    questions = [r["input"] for r in group]
    gid = group[0]["group_id"]

    # 故意随便答
    answers = ["不知道" for _ in questions]

    r = api("POST", f"/api/sessions/{sid}/complete-feynman", {
        "group_id": gid,
        "answers": answers
    })
    assert r["passed"] == False, "should fail with bad answers"
    assert_eq(r["new_status"], "revising", "failed feynman status")
    return f"score={r['final_score']}, passed={r['passed']}, status→{r['new_status']}"

def test_flow2_verify_revising():
    """Flow2: 验证 revising 状态下深化面板可用"""
    sid = SESSION_IDS[-1]
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    assert_eq(ws["session"]["status"], "revising", "status should be revising")
    # 后端 phase 应该正确返回 revising（之前缺失的 Bug 已修）
    assert_eq(ws["phase"], "revising", "phase should be revising")
    return f"phase={ws['phase']}"

def test_flow2_deepen_after_fail():
    """Flow2: 费曼失败后继续深化"""
    sid = SESSION_IDS[-1]
    r = api("POST", f"/api/sessions/{sid}/deepen", {
        "action_type": "press",
        "content": "TIME_WAIT 状态为什么要等 2MSL？"
    })
    return f"answer len={len(r['answer'])}"

def test_flow2_feynman_retry_pass():
    """Flow2: 再次费曼 → 认真答 → 通过"""
    sid = SESSION_IDS[-1]
    r = api("POST", f"/api/sessions/{sid}/start-feynman")
    group_id = r["group_id"]
    ws = wait_until(sid, {"feynman", "completed"})

    # 等到 feynman 状态稳定后读题
    ws2 = api("GET", f"/api/sessions/{sid}/workspace")
    group = ws2.get("current_review_group", [])
    questions = [rnd["input"] for rnd in group]
    gid = group[0]["group_id"] if group else group_id

    answers = []
    for q in questions:
        answers.append(
            f"针对「{q}」的详细回答：理解 TCP 协议需要从状态机的角度出发。"
            f"三次握手不是随意设计的：第一次握手（SYN）让服务端知道客户端能发、且客户端初始化了 seq=x；"
            f"第二次握手（SYN-ACK）让客户端知道服务端能收能发、且确认了 x、初始化了 seq=y；"
            f"第三次握手（ACK）让服务端知道客户端能收。每一步都在建立双向信任——"
            f"这不仅是技术需求，更是对不可靠网络下可靠通信的工程智慧。为什么是三次不是两次？"
            f"因为两次握手无法防止旧的重复 SYN 包导致服务端建立半开连接。"
            f"四次挥手因为 TCP 是全双工的：主动关闭方发 FIN 表示「我说完了」，被动方回 ACK 表示「收到」，"
            f"但被动方可能还有数据要发，所以等它发完后也发 FIN，主动方最后回 ACK。"
            f"TIME_WAIT 等 2MSL（最长报文段寿命的两倍）有两个目的：确保最后的 ACK 能到达对方"
            f"（如果丢了，对方会重发 FIN，主动方还能再回 ACK）；"
            f"让本连接的所有报文在网络中彻底消失，防止被后续同端口的新连接误收。"
            f"这在端口快速复用（SO_REUSEADDR）场景中尤其关键。"
        )

    r2 = api("POST", f"/api/sessions/{sid}/complete-feynman", {
        "group_id": gid,
        "answers": answers
    })
    return f"score={r2['final_score']}, passed={r2['passed']}, status→{r2['new_status']}"

def test_flow2_verify_completed():
    sid = SESSION_IDS[-1]
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    assert_eq(ws["session"]["status"], "completed", "should be completed after retry")
    return f"score={ws['session']['score']}"

# ══════════════════════════════════════════════════════════════════════════
# Flow 3: 费曼通过分数线动态修改验证
# ══════════════════════════════════════════════════════════════════════════

def test_flow3_read_default_pass_score():
    """Flow3: 默认通过分"""
    s = api("GET", "/api/settings")
    ps = s.get("feynman_pass_score", 60)
    return f"default pass_score={ps}"

def test_flow3_change_pass_score_high():
    """Flow3: 设为 95 → 正常回答也难通过"""
    r = api("PATCH", "/api/settings", {"feynman_pass_score": 95})
    assert_eq(r["feynman_pass_score"], 95, "pass_score should be 95")
    return f"set to 95 ✓"

def test_flow3_create_with_high_bar():
    """Flow3: 创建新 session，pass_score=95"""
    r = api("POST", "/api/sessions", {
        "content": "解释快速排序的分区过程及其时间复杂度分析。",
        "type": "question",
        "web_search": False
    })
    SESSION_IDS.append(r["session_id"])
    return f"sid={r['session_id']}"

def test_flow3_wait_and_deepen():
    sid = SESSION_IDS[-1]
    wait_until(sid, {"learning", "error"})
    api("POST", f"/api/sessions/{sid}/deepen", {
        "action_type": "take",
        "content": "快速排序的核心是分区——选一个 pivot，把小于 pivot 的放左边，大于的放右边，然后递归处理左右子数组。最好和平均 O(n log n)，最坏 O(n²)。分区可以用双指针法实现原地排序。"
    })
    return "deepen done"

def test_flow3_feynman_with_high_bar():
    """Flow3: pass_score=95 → 正常答也大概率 fail"""
    sid = SESSION_IDS[-1]
    r = api("POST", f"/api/sessions/{sid}/start-feynman")
    gid = r["group_id"]
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    group = ws.get("current_review_group", [])
    questions = [rnd["input"] for rnd in group]
    gid2 = group[0]["group_id"] if group else gid

    answers = [
        f"针对问题「{q}」的详细回答：快速排序的优雅之处在于它通过一次分区操作将问题规模减半，"
        f"这种分治策略是算法设计的典范。分区过程选择一个 pivot，通过双指针将小于 pivot 的元素交换到左边、"
        f"大于的交换到右边，然后递归处理左右子数组。最好情况 pivot 每次都能将数组平分，递归深度 O(log n)，"
        f"每层 O(n)，总复杂度 O(n log n)。最坏情况是已排序数组+pivot 选第一个元素，退化为 O(n²)。"
        f"工程上的改进包括：三数取中优化 pivot 选择、小数组切换到插入排序、尾递归优化减少栈深度。"
        f"快速排序通常比归并排序更快因为它的常数因子更小、且原地排序不需要额外数组。"
        f"但它是不稳定排序——相同元素的相对顺序可能改变。理解这些细节才能真正掌握排序算法的选择。"
        for q in questions
    ]
    r2 = api("POST", f"/api/sessions/{sid}/complete-feynman", {
        "group_id": gid2,
        "answers": answers
    })
    # 不强制 assert passed==False，只是记录实际结果
    return f"score={r2['final_score']}, passed={r2['passed']}, bar=95"

def test_flow3_lower_bar_and_verify():
    """Flow3: 降到 10 → 必然通过"""
    api("PATCH", "/api/settings", {"feynman_pass_score": 10})
    s = api("GET", "/api/settings")
    assert_eq(s["feynman_pass_score"], 10, "pass_score should be 10 after lowering")
    return f"lowered to 10 ✓"

def test_flow3_restore_pass_score():
    """Flow3: 恢复默认 60"""
    api("PATCH", "/api/settings", {"feynman_pass_score": 60})
    s = api("GET", "/api/settings")
    assert_eq(s["feynman_pass_score"], 60, "restored to 60")
    return "restored to 60 ✓"

# ══════════════════════════════════════════════════════════════════════════
# Flow 4: 观点类型 + 联网搜索
# ══════════════════════════════════════════════════════════════════════════

def test_flow4_viewpoint_with_search():
    """Flow4: 观点类型 + 联网搜索"""
    r = api("POST", "/api/sessions", {
        "content": "我认为微服务架构被过度推广了，大部分项目其实用单体架构就够了。",
        "type": "viewpoint",
        "web_search": True
    })
    SESSION_IDS.append(r["session_id"])
    return f"sid={r['session_id']}, type=viewpoint, web_search=True"

def test_flow4_wait_viewpoint():
    sid = SESSION_IDS[-1]
    ws = wait_until(sid, {"learning", "error"})
    if ws["session"]["status"] == "error":
        raise RuntimeError(ws["session"].get("error_msg",""))
    # 观点类型的回答应该包含"分析"相关的内容
    mat = ws["session"].get("material","")
    return f"type={ws['session']['type']}, answer={len(mat)} chars"

# ══════════════════════════════════════════════════════════════════════════
# Flow 5: 手动完成（跳过费曼）
# ══════════════════════════════════════════════════════════════════════════

def test_flow5_create():
    r = api("POST", "/api/sessions", {
        "content": "什么是布隆过滤器？它的原理和适用场景是什么？",
        "type": "question",
        "web_search": False
    })
    SESSION_IDS.append(r["session_id"])
    return f"sid={r['session_id']}"

def test_flow5_wait_and_deepen():
    sid = SESSION_IDS[-1]
    wait_until(sid, {"learning", "error"})
    api("POST", f"/api/sessions/{sid}/deepen", {
        "action_type": "take",
        "content": "布隆过滤器是一种概率型数据结构，用多个哈希函数和位数组来判断元素是否可能存在。它可以说「一定不存在」但只能说「可能存在」。原理是用 k 个哈希函数将元素映射到位数组的 k 个位置，查的时候如果所有位都是 1 就说可能存在。优点是空间效率极高，缺点是存在误判率且不支持删除。"
    })
    return "deepen done"

def test_flow5_manual_complete():
    """Flow5: 手动标记完成（不进费曼）"""
    sid = SESSION_IDS[-1]
    r = api("POST", f"/api/sessions/{sid}/complete")
    assert_eq(r["ok"], True)
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    assert_eq(ws["session"]["status"], "completed", "manually completed")
    return f"status→{ws['session']['status']}"

# ══════════════════════════════════════════════════════════════════════════
# Flow 6: 心理学 — 认知失调（简单完美路径）
# ══════════════════════════════════════════════════════════════════════════

def test_flow6_create():
    """Flow6: 心理学 — 创建 session"""
    r = api("POST", "/api/sessions", {
        "content": "什么是认知失调？请解释费斯廷格的认知失调理论及其在日常生活中的表现。",
        "type": "question",
        "web_search": False
    })
    SESSION_IDS.append(r["session_id"])
    return f"sid={r['session_id']}"

def test_flow6_wait_answer():
    sid = SESSION_IDS[-1]
    ws = wait_until(sid, {"learning", "error"})
    if ws["session"]["status"] == "error":
        raise RuntimeError(ws["session"].get("error_msg", ""))
    return f"title={ws['session']['title']}"

def test_flow6_take():
    sid = SESSION_IDS[-1]
    r = api("POST", f"/api/sessions/{sid}/deepen", {
        "action_type": "take",
        "content": (
            "认知失调是指人同时持有两个互相矛盾的信念/行为时产生的心理不适感。"
            "费斯廷格1957年提出：人会自动寻求减少这种不适。常见策略有三种：改变信念（吸烟者开始怀疑研究）、"
            "改变行为（真的戒烟）、增加新认知来合理化（'活在当下，死前再后悔也不迟'）。"
            "经典实验：让人做无聊任务，只给1美元的比给20美元的更觉得任务有趣——因为前者需要自我说服。"
            "日常例子：高价买的东西自动觉得更好（合理化投资），环保主义者开空调时觉得'偶尔一次没关系'。"
        )
    })
    return f"score={r['score']}"

def test_flow6_feynman_pass():
    """Flow6: 费曼通过 → completed"""
    sid = SESSION_IDS[-1]
    api("POST", f"/api/sessions/{sid}/start-feynman")
    ws = wait_until(sid, {"feynman", "completed"})
    ws2 = api("GET", f"/api/sessions/{sid}/workspace")
    group = ws2.get("current_review_group", [])
    if not group:
        return "already completed"
    questions = [rnd["input"] for rnd in group]
    gid = group[0]["group_id"]
    answers = [
        f"针对「{q}」：认知失调的核心洞见是，人并非总是理性的——我们会主动扭曲现实来保护自我形象。"
        f"当行为和信念冲突时，改变信念比改变行为容易得多。这解释了很多非理性行为：为什么买了彩票的人"
        f"突然觉得自己会赢；为什么加入邪教后越难退出；为什么受苦越多越爱一个团体（投入越大越合理化）。"
        f"费斯廷格的实验设计非常精妙：通过控制报酬大小，操纵人是否需要用认知改变来解释自己的行为。"
        f"这个理论后来发展出自我知觉理论的争议，但核心现象——人在矛盾下会自动寻求一致性——已被大量实验证实。"
        for q in questions
    ]
    r = api("POST", f"/api/sessions/{sid}/complete-feynman", {"group_id": gid, "answers": answers})
    return f"score={r['final_score']}, passed={r['passed']}, status→{r['new_status']}"

def test_flow6_verify():
    sid = SESSION_IDS[-1]
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    assert_eq(ws["session"]["status"], "completed", "flow6 should be completed")

# ══════════════════════════════════════════════════════════════════════════
# Flow 7: 生物学 — DNA 复制（简单完美路径）
# ══════════════════════════════════════════════════════════════════════════

def test_flow7_create():
    """Flow7: 生物学 — 创建 session"""
    r = api("POST", "/api/sessions", {
        "content": "解释 DNA 半保留复制的机制：主要酶的作用、前导链和滞后链的合成差异是什么？",
        "type": "question",
        "web_search": False
    })
    SESSION_IDS.append(r["session_id"])
    return f"sid={r['session_id']}"

def test_flow7_wait_and_take():
    sid = SESSION_IDS[-1]
    wait_until(sid, {"learning", "error"})
    r = api("POST", f"/api/sessions/{sid}/deepen", {
        "action_type": "take",
        "content": (
            "DNA 复制是半保留的：每条子链保留一条亲代链。关键酶：解旋酶打开双链，"
            "引物酶合成 RNA 引物（DNA 聚合酶只能延伸不能从头合成），DNA 聚合酶 III 从 5'→3' 方向合成，"
            "DNA 连接酶连接冈崎片段。前导链连续合成（与解链方向一致），"
            "滞后链不连续合成产生冈崎片段（因为聚合酶只能 5'→3'，方向相反），"
            "之后 RNA 引物被切除、填补、连接。整个过程需要 SSB 蛋白稳定单链，拓扑异构酶消除超螺旋张力。"
        )
    })
    return f"score={r['score']}"

def test_flow7_feynman_pass():
    """Flow7: 费曼通过"""
    sid = SESSION_IDS[-1]
    api("POST", f"/api/sessions/{sid}/start-feynman")
    wait_until(sid, {"feynman", "completed"})
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    group = ws.get("current_review_group", [])
    if not group:
        return "already completed"
    gid = group[0]["group_id"]
    questions = [rnd["input"] for rnd in group]
    answers = [
        f"针对「{q}」：DNA 半保留复制的精妙之处在于它保证了遗传信息的精确传递。"
        f"解旋酶消耗 ATP 打开氢键，形成复制叉；SSB 蛋白防止单链重新折叠；"
        f"拓扑异构酶 II 在前方切断并重接来释放超螺旋张力，否则 DNA 会被拧断。"
        f"聚合酶只能 5'→3' 延伸这一限制导致了前导链/滞后链的不对称性——这不是设计缺陷，"
        f"而是化学约束下的最优解。滞后链的冈崎片段（原核约1000-2000 nt，真核约100-200 nt）"
        f"需要 DNA Pol I 替换引物、连接酶封口，整个过程消耗更多时间和酶资源，"
        f"但这是物理定律下不可避免的。半保留机制由 Meselson-Stahl 实验通过 N15/N14 密度梯度离心完美证实。"
        for q in questions
    ]
    r = api("POST", f"/api/sessions/{sid}/complete-feynman", {"group_id": gid, "answers": answers})
    return f"score={r['final_score']}, passed={r['passed']}"

def test_flow7_verify():
    sid = SESSION_IDS[-1]
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    assert_eq(ws["session"]["status"], "completed", "flow7 should be completed")

# ══════════════════════════════════════════════════════════════════════════
# Flow 8: 经济学 — 纳什均衡（简单完美路径）
# ══════════════════════════════════════════════════════════════════════════

def test_flow8_create():
    """Flow8: 经济学 — 博弈论纳什均衡"""
    r = api("POST", "/api/sessions", {
        "content": "什么是纳什均衡？用囚徒困境解释为什么理性个体会陷入集体次优结果。",
        "type": "question",
        "web_search": False
    })
    SESSION_IDS.append(r["session_id"])
    return f"sid={r['session_id']}"

def test_flow8_wait_and_take():
    sid = SESSION_IDS[-1]
    wait_until(sid, {"learning", "error"})
    r = api("POST", f"/api/sessions/{sid}/deepen", {
        "action_type": "take",
        "content": (
            "纳什均衡是博弈中没有玩家单方面改变策略能让自己获益的状态。"
            "囚徒困境：两个囚犯分开审讯，互相背叛是纳什均衡（无论对方怎么选，背叛都是最优反应），"
            "但双方合作才是帕累托最优。理性个体基于自身利益选择背叛，导致集体次优（5年+5年 vs 合作的1年+1年）。"
            "这解释了军备竞赛、公地悲剧、价格战——个体理性导致集体非理性。"
            "解决方案：重复博弈（声誉机制）、外部约束（法律）、小群体（相互监督）。"
        )
    })
    return f"score={r['score']}"

def test_flow8_feynman_pass():
    """Flow8: 费曼通过"""
    sid = SESSION_IDS[-1]
    api("POST", f"/api/sessions/{sid}/start-feynman")
    wait_until(sid, {"feynman", "completed"})
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    group = ws.get("current_review_group", [])
    if not group:
        return "already completed"
    gid = group[0]["group_id"]
    questions = [rnd["input"] for rnd in group]
    answers = [
        f"针对「{q}」：纳什均衡的深刻之处在于它揭示了'理性'的内在悖论。"
        f"每个玩家都是理性的，逻辑链完全正确，但集体结果却是次优的。"
        f"这不是因为人愚蠢，而是因为激励结构本身有问题。囚徒困境的数学结构：背叛是严格占优策略——"
        f"无论对方合作还是背叛，背叛对我都更好（0年 vs 1年，5年 vs 8年）。"
        f"当双方都用这个逻辑，就陷入(5,5)的均衡，而非(1,1)的最优。"
        f"真实世界应用：OPEC 成员总想超额生产（破坏油价协议），核大国陷入军备竞赛，"
        f"企业价格战打到无利可图。解法的关键是改变博弈结构：无限重复博弈中'以牙还牙'策略可以维持合作——"
        f"Axelrod 的计算机锦标赛证明了这一点。这就是为什么长期关系、重复互动是合作的基础。"
        for q in questions
    ]
    r = api("POST", f"/api/sessions/{sid}/complete-feynman", {"group_id": gid, "answers": answers})
    return f"score={r['final_score']}, passed={r['passed']}"

def test_flow8_verify():
    sid = SESSION_IDS[-1]
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    assert_eq(ws["session"]["status"], "completed", "flow8 should be completed")

# ══════════════════════════════════════════════════════════════════════════
# Flow 9: 物理 — 量子叠加与测量（简单完美路径）
# ══════════════════════════════════════════════════════════════════════════

def test_flow9_create():
    """Flow9: 物理 — 量子叠加"""
    r = api("POST", "/api/sessions", {
        "content": "解释量子叠加态和波函数坍缩：薛定谔的猫思想实验说明了什么问题？",
        "type": "question",
        "web_search": False
    })
    SESSION_IDS.append(r["session_id"])
    return f"sid={r['session_id']}"

def test_flow9_wait_and_take():
    sid = SESSION_IDS[-1]
    wait_until(sid, {"learning", "error"})
    r = api("POST", f"/api/sessions/{sid}/deepen", {
        "action_type": "take",
        "content": (
            "量子叠加：粒子在未被测量前同时处于多种状态，描述为波函数（各状态的概率幅叠加）。"
            "测量时波函数坍缩到一个确定状态，概率由波函数模的平方给出（玻恩规则）。"
            "薛定谔的猫：将量子不确定性放大到宏观——猫与衰变粒子纠缠，在观测前既活又死。"
            "这暴露了量子力学的测量问题：叠加态的边界在哪里？观测者效应是什么？"
            "主要诠释：哥本哈根诠释（波函数坍缩是真实的，不追问'之前'）、"
            "多世界诠释（波函数从不坍缩，所有结果在平行宇宙中实现）、退相干理论（宏观环境与系统纠缠，"
            "叠加态在环境中'消散'，显现为经典行为）。"
        )
    })
    return f"score={r['score']}"

def test_flow9_feynman_pass():
    """Flow9: 费曼通过"""
    sid = SESSION_IDS[-1]
    api("POST", f"/api/sessions/{sid}/start-feynman")
    wait_until(sid, {"feynman", "completed"})
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    group = ws.get("current_review_group", [])
    if not group:
        return "already completed"
    gid = group[0]["group_id"]
    questions = [rnd["input"] for rnd in group]
    answers = [
        f"针对「{q}」：薛定谔设计这个思想实验的本意是批判哥本哈根诠释——他认为'既死又活'是荒谬的，"
        f"说明量子力学在宏观尺度下一定不完备。量子叠加的核心数学是线性叠加原理：|ψ⟩ = α|0⟩ + β|1⟩，"
        f"|α|²+|β|²=1。这不是'不知道是哪个状态'，而是'真的同时是两个状态'——双缝实验证明了这点，"
        f"单个粒子能与自己干涉，说明它真的同时通过了两条缝。测量问题的困难在于：什么算'测量'？"
        f"意识参与？任何宏观相互作用？退相干理论给出了最令人满意的物理答案：宏观物体与环境的"
        f"大量粒子纠缠，导致量子相干性极快地消失（飞秒量级），我们看到的经典行为是量子力学在"
        f"环境耦合下的涌现。但这并不解决多世界vs单一结果的哲学问题，这仍然是开放问题。"
        for q in questions
    ]
    r = api("POST", f"/api/sessions/{sid}/complete-feynman", {"group_id": gid, "answers": answers})
    return f"score={r['final_score']}, passed={r['passed']}"

def test_flow9_verify():
    sid = SESSION_IDS[-1]
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    assert_eq(ws["session"]["status"], "completed", "flow9 should be completed")

# ══════════════════════════════════════════════════════════════════════════
# Flow 10: 历史 — 工业革命（观点类型）
# ══════════════════════════════════════════════════════════════════════════

def test_flow10_create():
    """Flow10: 历史/观点 — 工业革命起源"""
    r = api("POST", "/api/sessions", {
        "content": "我认为工业革命首先在英国发生不是偶然的，而是制度、地理、文化多重因素共同作用的必然结果。",
        "type": "viewpoint",
        "web_search": False
    })
    SESSION_IDS.append(r["session_id"])
    return f"sid={r['session_id']}"

def test_flow10_wait_and_take():
    sid = SESSION_IDS[-1]
    ws = wait_until(sid, {"learning", "error"})
    if ws["session"]["status"] == "error":
        raise RuntimeError(ws["session"].get("error_msg", ""))
    r = api("POST", f"/api/sessions/{sid}/deepen", {
        "action_type": "take",
        "content": (
            "英国工业革命的多因素论：制度层面——光荣革命后议会保护产权和专利（1624年专利法），"
            "降低创新风险；殖民地市场提供需求和原料。地理层面——丰富的煤矿与铁矿相邻分布，"
            "可通航河流降低运输成本；岛国地位减少战争破坏。文化层面——非国教徒（贵格会、清教徒）"
            "重视勤劳、储蓄、实用技能，大量工匠精英阶层；皇家学会促进科学实用化。"
            "劳动力价格：高工资促使用机器替代人工（与低工资的中国和印度形成对比）。"
            "这些因素缺一不可，互相强化——制度稳定才能让资本积累，高工资才有机器替代的动力。"
        )
    })
    return f"score={r['score']}"

def test_flow10_feynman_pass():
    """Flow10: 费曼通过"""
    sid = SESSION_IDS[-1]
    api("POST", f"/api/sessions/{sid}/start-feynman")
    wait_until(sid, {"feynman", "completed"})
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    group = ws.get("current_review_group", [])
    if not group:
        return "already completed"
    gid = group[0]["group_id"]
    questions = [rnd["input"] for rnd in group]
    answers = [
        f"针对「{q}」：工业革命的'必然性'是个危险的说法——历史没有必然，但有条件。"
        f"更准确的说法是：18世纪英国的条件组合，使得工业化的涌现概率远高于其他地方。"
        f"Robert Allen 的高工资/低能源价格理论特别有说服力：英国矿工工资是阿姆斯特丹的2倍、"
        f"中国的5倍，而煤炭价格极低（矿山旁边）。在这个价格信号下，用蒸汽机替代工人是划算的，"
        f"而在中国和印度则不然——这解释了为什么同样的技术知识只在英国被产业化。"
        f"制度因素不可忽视：Gregory Clark 的研究显示光荣革命后违约率下降，利率降至4%，"
        f"长期投资成为可能。但文化决定论（如韦伯的新教伦理）已被历史学家质疑——"
        f"荷兰更新教但工业革命没在那里发生。历史解释的艺术在于识别'最关键的瓶颈因素'，"
        f"而不是列举所有相关因素。"
        for q in questions
    ]
    r = api("POST", f"/api/sessions/{sid}/complete-feynman", {"group_id": gid, "answers": answers})
    return f"score={r['final_score']}, passed={r['passed']}"

def test_flow10_verify():
    sid = SESSION_IDS[-1]
    ws = api("GET", f"/api/sessions/{sid}/workspace")
    assert_eq(ws["session"]["status"], "completed", "flow10 should be completed")

# ══════════════════════════════════════════════════════════════════════════
# Flow 11: 边界情况
# ══════════════════════════════════════════════════════════════════════════

def test_edge_empty_content():
    """空内容不能提交"""
    try:
        api("POST", "/api/sessions", {"content": "", "type": "question"})
        raise AssertionError("should reject empty")
    except RuntimeError as e:
        # FastAPI validation errors come as HTTP 422
        if "422" not in str(e) and "内容不能为空" not in str(e) and "field required" not in str(e).lower():
            raise RuntimeError(f"Unexpected error for empty content: {e}")

def test_edge_invalid_action_type():
    """无效的 action_type"""
    sid = SESSION_IDS[0]  # 用已完成的 session
    try:
        api("POST", f"/api/sessions/{sid}/deepen", {
            "action_type": "invalid",
            "content": "test"
        })
        raise AssertionError("should reject invalid action_type")
    except RuntimeError as e:
        if "400" not in str(e) and "422" not in str(e):
            raise

def test_edge_invalid_theme():
    """无效的主题名"""
    try:
        api("PATCH", "/api/profile", {"theme": "invalid"})
        raise AssertionError("should reject invalid theme")
    except RuntimeError as e:
        if "400" not in str(e):
            raise

def test_edge_reopen():
    """reopen 端点：completed → learning"""
    if len(SESSION_IDS) >= 3:
        sid = SESSION_IDS[2]
        try:
            r = api("POST", f"/api/sessions/{sid}/reopen")
            assert_eq(r["ok"], True)
            ws = api("GET", f"/api/sessions/{sid}/workspace")
            assert_eq(ws["session"]["status"], "learning", "reopened to learning")
        except RuntimeError as e:
            if "404" in str(e):
                pass
            else:
                raise

def test_edge_knowledge_tree():
    """知识树数据结构正确"""
    r = api("GET", "/api/knowledge-tree")
    tree = r.get("tree", [])
    assert len(tree) >= 1, "knowledge tree should have entries"
    return f"{len(tree)} domains"

# ══════════════════════════════════════════════════════════════════════════
# Flow 7: 不变式验证（测试结束后对所有 session 检查）
# ══════════════════════════════════════════════════════════════════════════

def test_invariants():
    """验证所有测试 session 的数据一致性"""
    problems = []
    for sid in SESSION_IDS:
        try:
            ws = api("GET", f"/api/sessions/{sid}/workspace")
        except:
            continue
        s = ws["session"]
        rounds = ws.get("rounds", [])

        # completed session 最好有 score，但手动完成可以没有
        if s["status"] == "completed" and s.get("score") is not None:
            pass  # ok

        # deepening/revising session 不能同时有 pending feynman
        feynman_rounds = [r for r in rounds if r["type"] == "feynman"]
        if feynman_rounds:
            pending = [r for r in feynman_rounds if r["status"] == "pending"]
            if pending and s["status"] not in ("feynman", "revising"):
                problems.append(f"sid={sid}: pending feynman but status={s['status']}")

        # 有 rounds 的 session 不应该还是 learning 状态
        if rounds and s["status"] == "learning":
            problems.append(f"sid={sid}: has {len(rounds)} rounds but status=learning")

    if problems:
        raise AssertionError("\n  " + "\n  ".join(problems))
    return f"checked {len(SESSION_IDS)} sessions, no invariants violated"

# ══════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════

ALL_TESTS = [
    # Setup
    ("00 设定低通过分", test_00_setup_pass_score),
    # 基础
    ("01 健康检查", test_01_health),
    ("02 读取设置", test_02_settings_read),
    ("03 统计接口", test_03_stats_baseline),
    ("04 Session 列表", test_04_sessions_list),
    ("05 404 不存在 session", test_05_404_session),

    # Flow 1: 完美路径
    ("Flow1-1 创建 session", test_flow1_create),
    ("Flow1-2 AI 生成回答", test_flow1_wait_answer),
    ("Flow1-3 写理解 (take)", test_flow1_take),
    ("Flow1-4 追问 (press)", test_flow1_press),
    ("Flow1-5 开始费曼", test_flow1_feynman_start),
    ("Flow1-6 费曼通过 → completed", test_flow1_feynman_pass),
    ("Flow1-7 验证 completed", test_flow1_verify_completed),

    # Flow 2: 失败→revising→再深化→通过
    ("Flow2-1 创建 session", test_flow2_create),
    ("Flow2-2 AI 生成回答", test_flow2_wait_answer),
    ("Flow2-3 写理解", test_flow2_take),
    ("Flow2-4 开始费曼", test_flow2_feynman_start),
    ("Flow2-5 费曼失败 → revising", test_flow2_feynman_fail),
    ("Flow2-6 验证 revising + phase 正确", test_flow2_verify_revising),
    ("Flow2-7 失败后继续深化", test_flow2_deepen_after_fail),
    ("Flow2-8 再战费曼 → 通过", test_flow2_feynman_retry_pass),
    ("Flow2-9 验证 completed", test_flow2_verify_completed),

    # Flow 3: 通过分动态修改
    ("Flow3-1 默认通过分", test_flow3_read_default_pass_score),
    ("Flow3-2 设为 95", test_flow3_change_pass_score_high),
    ("Flow3-3 创建 session(bar=95)", test_flow3_create_with_high_bar),
    ("Flow3-4 深化", test_flow3_wait_and_deepen),
    ("Flow3-5 费曼(bar=95)", test_flow3_feynman_with_high_bar),
    ("Flow3-6 降到 10", test_flow3_lower_bar_and_verify),
    ("Flow3-7 恢复默认 60", test_flow3_restore_pass_score),

    # Flow 4: 观点 + 联网
    ("Flow4-1 观点+联网创建", test_flow4_viewpoint_with_search),
    ("Flow4-2 观点 AI 分析", test_flow4_wait_viewpoint),

    # Flow 5: 手动完成
    ("Flow5-1 创建 session", test_flow5_create),
    ("Flow5-2 深化", test_flow5_wait_and_deepen),
    ("Flow5-3 手动完成", test_flow5_manual_complete),

    # Flow 6-10 前重设低通过分（Flow3 已恢复默认 60，新 flow 需要低分线）
    ("Flow6-0 重设通过分为 20", lambda: api("PATCH", "/api/settings", {"feynman_pass_score": 20}) or "pass_score→20"),

    # Flow 6: 心理学 — 认知失调
    ("Flow6-1 创建 session(心理学)", test_flow6_create),
    ("Flow6-2 AI 生成回答", test_flow6_wait_answer),
    ("Flow6-3 写理解", test_flow6_take),
    ("Flow6-4 费曼通过 → completed", test_flow6_feynman_pass),
    ("Flow6-5 验证 completed", test_flow6_verify),

    # Flow 7: 生物学 — DNA 复制
    ("Flow7-1 创建 session(生物学)", test_flow7_create),
    ("Flow7-2 深化", test_flow7_wait_and_take),
    ("Flow7-3 费曼通过 → completed", test_flow7_feynman_pass),
    ("Flow7-4 验证 completed", test_flow7_verify),

    # Flow 8: 经济学 — 纳什均衡
    ("Flow8-1 创建 session(经济学)", test_flow8_create),
    ("Flow8-2 深化", test_flow8_wait_and_take),
    ("Flow8-3 费曼通过 → completed", test_flow8_feynman_pass),
    ("Flow8-4 验证 completed", test_flow8_verify),

    # Flow 9: 物理 — 量子叠加
    ("Flow9-1 创建 session(物理)", test_flow9_create),
    ("Flow9-2 深化", test_flow9_wait_and_take),
    ("Flow9-3 费曼通过 → completed", test_flow9_feynman_pass),
    ("Flow9-4 验证 completed", test_flow9_verify),

    # Flow 10: 历史 — 工业革命(观点)
    ("Flow10-1 创建 session(历史/观点)", test_flow10_create),
    ("Flow10-2 AI 分析 + 深化", test_flow10_wait_and_take),
    ("Flow10-3 费曼通过 → completed", test_flow10_feynman_pass),
    ("Flow10-4 验证 completed", test_flow10_verify),

    # 边界情况
    ("Edge1 空内容拒绝", test_edge_empty_content),
    ("Edge2 无效 action_type", test_edge_invalid_action_type),
    ("Edge3 无效 theme", test_edge_invalid_theme),
    ("Edge4 reopen 端点", test_edge_reopen),
    ("Edge5 知识树结构", test_edge_knowledge_tree),

    # 不变式
    ("Invariant 数据一致性", test_invariants),
]

if __name__ == "__main__":
    print("=" * 65)
    print("  AIIterate 全流程回归测试")
    print("  " + time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 65)

    for name, fn in ALL_TESTS:
        print(f"\n── {name} ──")
        T(name, fn)

    print("\n" + "=" * 65)
    print(f"  结果: {passed} 通过  {failed} 失败  (共 {passed+failed})")
    if failed == 0:
        print("  ✅ 全部通过！系统运行正常。")
    else:
        print(f"  ⚠️  {failed} 个测试失败！需要排查。")
    print("=" * 65)

    sys.exit(0 if failed == 0 else 1)
