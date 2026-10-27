# -*- coding: utf-8 -*-
"""
在游戏脚本里定位「效果该挂在哪」。

三件事：
  1. scripts() / script_text()  —— 读脚本（解包 .rb 与 Scripts.rxdata 两处都收）
  2. handler_tables()           —— 从游戏**自己的**脚本里读出效果注册表
                                   （BattleHandlers / Battle::AbilityEffects /
                                     Battle::ItemEffects / ItemHandlers）
  3. func() / move_class()      —— 取某个函数 / 某个招式效果类的源码

★ 为什么不写死一张「版本 → 钩子名」的表：
  同人游戏经常自己往 Battle::AbilityEffects 里加处理器（`OnXxx = AbilityHandlerHash.new`），
  也会改名。从游戏脚本里现读，拿到的就是**这个游戏真有**的钩子。
★ 参数表也现读：拿同一个处理器里已有的 `.add(:XXX, proc { |a,b,c|` 抄参数名。
  不同版本的参数个数**确实不一样**（v19 登场三个参数、v20 四个），猜必错。
"""
import os
import re

import ce_boot

ce_boot.bootstrap()

import ce_core as C      # noqa: E402

_CACHE = {}


def scripts(game_dir, both=True):
    """
    游戏脚本 → [(mode, key, path, name, text), ...]

    ★ both=True 默认：解包 .rb 与 Scripts.rxdata 同时收 —— 改脚本要两处都改。
      只做「找东西」时可以传 False。
    """
    key = (os.path.abspath(str(game_dir)), bool(both))
    if key not in _CACHE:
        _CACHE[key] = list(C.iter_named_scripts(game_dir, both=both))
    return _CACHE[key]


def clear_cache():
    _CACHE.clear()
    C.clear_cache()


def text_by_name(game_dir):
    """{脚本名: [(mode, key, path, text), ...]}（同名脚本可能不止一份）。"""
    out = {}
    for mode, key, path, name, text in scripts(game_dir):
        out.setdefault(name, []).append((mode, key, path, text))
    return out


def script_text(game_dir, name):
    """按脚本名取源码（多份就全都接起来），找不到返回 ""。"""
    got = text_by_name(game_dir).get(name) or []
    return "\n".join(t for _m, _k, _p, t in got)


# ------------------------------------------------------------------
# 效果注册表
# ------------------------------------------------------------------
# `OnSwitchIn = AbilityHandlerHash.new` 这类声明；ItemHandlers 里是裸 HandlerHash
_HASH_DECL_RE = re.compile(
    r"^[ \t]*([A-Za-z_]\w*)[ \t]*=[ \t]*(\w*HandlerHash)\.new\b", re.M)

# 注册表的「容器」→ (限定前缀, 种类)
_CONTAINERS = (
    ("Battle::AbilityEffects", "Battle::AbilityEffects::", "ability"),
    ("Battle::ItemEffects", "Battle::ItemEffects::", "item"),
    ("BattleHandlers", "BattleHandlers::", None),   # 两种混在一起，按 Hash 类型分
    ("ItemHandlers", "ItemHandlers::", "item"),
)

_RE_MOVE_CLASS = re.compile(
    r"^class[ \t]+(Battle::Move::(\w+)|PokeBattle_Move_(\w+))"
    r"(?:[ \t]*<[ \t]*([\w:]+))?", re.M)

# 招式效果「该重写哪个方法」的候选（v18 起统一成这三个 + 几个衍生）
MOVE_EFFECT_METHODS = ("pbEffectGeneral", "pbEffectAgainstTarget",
                       "pbAdditionalEffect", "pbEffectWhenDealingDamage",
                       "pbEffectAfterAllHits")
# v16 / v17 只有一个大 pbEffect
LEGACY_MOVE_EFFECT_METHODS = ("pbEffect", "pbAdditionalEffect", "pbEffectAfterHit")


def _module_block(text, container):
    """从整份脚本里抠出 `module Xxx` 的块（找不到返回 ""）。"""
    pat = re.compile(r"^(?:module|class)[ \t]+" + re.escape(container) + r"\b", re.M)
    m = pat.search(text)
    return _block_from(text, m.start()) if m else ""


def _block_from(text, pos):
    """从 pos 所在的 module/class 行起，按缩进配对到它的 end。"""
    all_lines = text.split("\n")
    start = text[:pos].count("\n")
    indent = len(all_lines[start]) - len(all_lines[start].lstrip())
    depth = 0
    for j in range(start + 1, len(all_lines)):
        s = all_lines[j].strip()
        if not s or s.startswith("#"):
            continue
        ind = len(all_lines[j]) - len(all_lines[j].lstrip())
        if C.OPEN_RE.match(s) or C.DO_RE.search(s.rstrip()):
            if ind >= indent or C.DO_RE.search(s.rstrip()):
                depth += 1
        elif re.match(r"^end\b", s):
            if depth == 0 and ind <= indent:
                return "\n".join(all_lines[start:j + 1])
            depth -= 1
    return "\n".join(all_lines[start:])


def _kind_of_hash(hash_class, default):
    if hash_class == "AbilityHandlerHash":
        return "ability"
    if hash_class == "ItemHandlerHash":
        return "item"
    if hash_class == "MoveHandlerHash":
        return "move"
    return default


# 一次扫完所有 `.add( / .addIf( / .copy(`，建「限定名 → 参数表」索引
#   `BattleHandlers::SpeedCalcAbility.add(:CHLOROPHYLL,\n  proc { |ability,battler,mult|`
#   ★ 声明和注册**经常不在同一个脚本里**（v19 的 SpeedCalcAbility 声明在
#     BattleHandlers、注册在 BattleHandlers_Abilities），所以必须先拼全文再扫。
_ADD_RE = re.compile(
    r"([A-Za-z_][\w:]*(?:::\w+)+)\.(addIf|add|copy)\(\s*:?(\w+)?")


def _add_index(game_dir):
    """{限定名: {"args": [...], "sample": str, "how": str}}（带缓存）。"""
    ck = ("adds", os.path.abspath(str(game_dir)))
    if ck in _CACHE:
        return _CACHE[ck]
    blob = "\n".join(t for _m, _k, _p, _n, t in scripts(game_dir))
    idx = {}
    for m in _ADD_RE.finditer(blob):
        qual, how, sample = m.group(1), m.group(2), m.group(3) or ""
        old = idx.get(qual)
        # ★ addIf/copy 的第一个 proc 常常是「过滤器」（`|item|`），
        #   拿它当注册参数会少一半参数 —— 有普通 add 就一定要用 add 的。
        if old and (old["how"] == "add" or how != "add"):
            continue
        tail = blob[m.end():m.end() + 400]
        am = re.search(r"proc\s*(?:\(\s*)?\{?\s*\|([^|]*)\|", tail)
        args = [x.strip() for x in am.group(1).split(",") if x.strip()] if am else []
        idx[qual] = {"args": args, "sample": sample, "how": how}
    _CACHE[ck] = idx
    return idx


def handler_tables(game_dir, only=None):
    """
    读出这个游戏**实际存在**的效果注册表。

    返回 {kind: {container, prefix, script, handlers: {名字: {...}}}}

      kind      = "ability" / "item" / "move"
      handlers[名字] = {"args": [...], "sample": 已有条目, "qualified": 限定名}

    ★ 同一 kind 可能在多个容器里都有（v20 战斗效果在 Battle::ItemEffects，
      背包道具在 ItemHandlers），handlers 是**合并**的，各自的 qualified 不同。
    """
    out = {}
    adds = _add_index(game_dir)
    for mode, key, path, name, text in scripts(game_dir):
        for container, prefix, forced in _CONTAINERS:
            if container not in text:
                continue
            if not re.search(r"^(?:module|class)[ \t]+"
                             + re.escape(container) + r"\b", text, re.M):
                continue
            block = _module_block(text, container)
            if not block:
                continue
            for hm in _HASH_DECL_RE.finditer(block):
                hname, hclass = hm.group(1), hm.group(2)
                kind = forced or _kind_of_hash(hclass, None)
                if not kind or (only and kind != only):
                    continue
                slot = out.setdefault(kind, {
                    "container": container, "prefix": prefix,
                    "script": name, "handlers": {}})
                if hname in slot["handlers"]:
                    continue
                qual = prefix + hname
                info = adds.get(qual) or {}
                slot["handlers"][hname] = {
                    "args": info.get("args") or [],
                    "sample": info.get("sample", ""),
                    "how": info.get("how", ""),
                    "hash": hclass,
                    "qualified": qual,
                    "container": container,
                    "script": name,
                }
    return out


def move_containers(game_dir):
    """招式效果类所在命名空间 → {container, script, count, samples}。"""
    out = {}
    for mode, key, path, name, text in scripts(game_dir):
        for m in _RE_MOVE_CLASS.finditer(text):
            full = m.group(1)
            if full.startswith("Battle::Move::"):
                container, stem = "Battle::Move", m.group(2)
            else:
                container, stem = "PokeBattle_Move", m.group(3)
            if not stem:
                continue
            slot = out.setdefault(container, {
                "container": container, "script": name, "count": 0,
                "samples": [], "parents": []})
            slot["count"] += 1
            if len(slot["samples"]) < 8:
                slot["samples"].append(stem)
            if m.group(4) and len(slot["parents"]) < 8:
                slot["parents"].append(m.group(4))
    return out


# ------------------------------------------------------------------
# 取源码
# ------------------------------------------------------------------
def func(game_dir, script, fname):
    """取游戏里某个函数 → {"mode","key","path","name","source","line"}；找不到 None。"""
    for mode, key, path, name, text in scripts(game_dir):
        if name != script:
            continue
        src = C.extract_func(text, fname)
        if not src:
            continue
        at = text.find(src)
        return {"mode": mode, "key": key, "path": path, "name": name,
                "source": src, "line": text[:at].count("\n") + 1 if at >= 0 else 0}
    return None


def extract_class(text, class_name):
    """抠出 `class <class_name>` 整块（含嵌套 end）；找不到返回 ""。"""
    pat = re.compile(r"^([ \t]*)(?:class|module)[ \t]+"
                     + re.escape(class_name) + r"\b", re.M)
    m = pat.search(text)
    return _block_from(text, m.start()) if m else ""


def move_class(game_dir, name):
    """找招式效果类（`Battle::Move::Xxx` / `PokeBattle_Move_Xxx`）→ 源码块。"""
    want = ("Battle::Move::" + name, "PokeBattle_Move_" + name, name)
    for mode, key, path, sname, text in scripts(game_dir):
        for w in want:
            src = extract_class(text, w)
            if src:
                return {"script": sname, "mode": mode, "path": path,
                        "class": w, "source": src}
    return None


def grep(game_dir, pattern, limit=60, flags=0):
    """在游戏脚本里搜正则 → [{"script","line","text","mode"}, ...]"""
    rx = re.compile(pattern, flags)
    out = []
    for mode, key, path, name, text in scripts(game_dir):
        for i, line in enumerate(text.split("\n"), 1):
            if rx.search(line):
                out.append({"script": name, "line": i, "mode": mode,
                            "text": line.strip()[:300]})
                if len(out) >= limit:
                    return out
    return out


def engine_ref(version, script, fname):
    """
    官方同版本某函数的源码（写补丁时当参照）。

    ★ 需要主项目（scripts/essentials_src）。没有主项目返回 "" ——
      这时用 `class` / `func` 读游戏自己的代码一样能改。
    """
    if not ce_boot.host_project():
        return ""
    try:
        import engine_src as ES
        return ES.func_source(version, script, fname)
    except Exception:                              # noqa: BLE001
        return ""


def official_available():
    """能不能读官方引擎源码（有主项目才行）。"""
    return bool(ce_boot.host_project())
