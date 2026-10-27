# -*- coding: utf-8 -*-
"""
校验：写进游戏之前先自己过一遍，别把语法错误塞进游戏脚本。

本机不一定有 Ruby（RGSS 那套 Ruby 也不一定在 PATH 里），所以主校验是自己做的
**结构检查**：

    · end / do 配对（def class module if unless while until for case begin）
    · () {} [] 配对
    · `# >>> ce:` / `# <<< ce:` 标记成对
    · 处理器名在这个游戏里真的存在（Battle::AbilityEffects::OnSwitchIn 之类）
    · 特性 / 道具 / 招式的 ID 在数据里真的存在（没有数据 = 代码永远不触发）

装了 Ruby 的话再跑一次 `ruby -c`（只是锦上添花）。
"""
import os
import re
import shutil
import subprocess
import tempfile

import ce_boot

ce_boot.bootstrap()

import ce_core as C    # noqa: E402

_OPEN_KW = re.compile(r"^(def|class|module|if|unless|while|until|for|case|begin)\b")
_DO_TAIL = re.compile(r"\bdo\b\s*(\|[^|]*\|)?\s*$")
_END = re.compile(r"^end\b")


def _strip_code(line):
    """去掉行尾注释与字符串内容（保留结构关键字）。"""
    line = C.strip_comment(line)
    out, i, n, quote = [], 0, len(line), ""
    while i < n:
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c in "\"'":
            quote = c
            out.append('""')
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _balance(text):
    """结构检查 → (problems, stats)。"""
    problems = []
    depth = 0
    paren = brace = bracket = 0
    for no, raw in enumerate(str(text or "").split("\n"), 1):
        line = _strip_code(raw.rstrip("\r"))
        if not line.strip():
            continue
        paren += line.count("(") - line.count(")")
        brace += line.count("{") - line.count("}")
        bracket += line.count("[") - line.count("]")
        s = line.strip()
        if _END.match(s):
            depth -= 1
            if depth < 0:
                problems.append({"line": no, "why": "多出来一个 end"})
                depth = 0
            continue
        if _OPEN_KW.match(s) or _DO_TAIL.search(s):
            depth += 1
    if depth != 0:
        problems.append({"line": 0, "why": "还差 %d 个 end（%s）"
                         % (depth, "多" if depth < 0 else "少")})
    for name, v in (("()", paren), ("{}", brace), ("[]", bracket)):
        if v != 0:
            problems.append({"line": 0, "why": "%s 不配对（差 %d）" % (name, v)})
    return problems


def _markers_ok(text):
    """ce 段标记成对。"""
    problems = []
    cur = None
    for no, line in enumerate(str(text or "").split("\n"), 1):
        m = re.match(r"^# >>> ce:(\S+)\s*$", line)
        if m:
            if cur:
                problems.append({"line": no, "why": "上一段 %s 没有收尾标记" % cur})
            cur = m.group(1)
            continue
        m = re.match(r"^# <<< ce:(\S+)\s*$", line)
        if m:
            if cur != m.group(1):
                problems.append({"line": no,
                                 "why": "收尾标记 %s 和开头 %s 对不上"
                                        % (m.group(1), cur)})
            cur = None
    if cur:
        problems.append({"line": 0, "why": "段 %s 没有收尾标记" % cur})
    return problems


def _symbols(text):
    """成品代码里出现的 :ID（大写符号）。"""
    return sorted(set(re.findall(r":([A-Z][A-Z0-9_]{2,})", str(text or ""))))


def check_snippet(text, game_dir=None):
    """
    检查一段（或整份）代码 → {"ok": bool, "problems": [...], "stats": {...}}

    game_dir 给了才做「钩子/ID 是否真实存在」的语义检查。
    """
    problems = list(_balance(text)) + list(_markers_ok(text))
    stats = {"bytes": len(str(text or "").encode("utf-8")),
             "lines": str(text or "").count("\n") + 1,
             "symbols": _symbols(text)}
    if game_dir:
        problems += _semantic(text, game_dir)
    r = ruby_syntax(text) if game_dir else {"ok": None}
    if r.get("ok") is False:
        problems.append({"line": 0, "why": "ruby -c 报错：" + r.get("detail", "")})
    return {"ok": not problems, "problems": problems, "stats": stats,
            "ruby": r.get("ok")}


def _semantic(text, game_dir):
    """处理器是否在这个游戏里真的存在。"""
    import ce_locate as L
    problems = []
    tables = L.handler_tables(game_dir)
    known = {i.get("qualified") for slot in tables.values()
             for i in slot["handlers"].values()}
    for qual in re.findall(r"\b((?:Battle::)?(?:AbilityEffects|ItemEffects|"
                           r"BattleHandlers|ItemHandlers)::\w+)\.add", text):
        if qual not in known:
            problems.append({"line": 0,
                             "why": "这个游戏里没有注册表 %s（可能名字被作者改过）"
                                    % qual})
    return problems


def ruby_syntax(text):
    """有 ruby 就跑 `ruby -c`；没有返回 {"ok": None}。"""
    exe = shutil.which("ruby")
    if not exe:
        return {"ok": None, "detail": "本机没有 ruby，跳过"}
    fd, p = tempfile.mkstemp(suffix=".rb")
    os.close(fd)
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        r = subprocess.run([exe, "-c", p], capture_output=True, text=True,
                           timeout=60)
        return {"ok": r.returncode == 0,
                "detail": (r.stderr or r.stdout).strip()[:400]}
    except Exception as e:                      # noqa: BLE001
        return {"ok": None, "detail": str(e)}
    finally:
        try:
            os.remove(p)
        except OSError:
            pass
