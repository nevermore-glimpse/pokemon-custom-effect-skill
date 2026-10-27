# -*- coding: utf-8 -*-
"""
游戏档案：版本 → 引擎世代（family）、脚本容器、引擎改动情况、数据 ID。

「引擎世代」决定代码怎么写，只有四档：

    family   版本              特性 / 道具效果 API            招式效果类
    legacy   16 / 17           ❌ 没有处理器，只能 alias 挂钩   PokeBattle_Move_XXX
    v18      18                BattleHandlers::Xxx.add         PokeBattle_Move_XXX
    v19      19 / 19.1         BattleHandlers::Xxx.add         PokeBattle_Move_XXX
    v20      20 / 20.1 / 21 / 21.1
                               Battle::AbilityEffects::X.add   Battle::Move::Xxx
                               Battle::ItemEffects::X.add

★ 判定不只看版本号：同人游戏经常把版本号改掉、或者拿老引擎套新数据。
  版本号读不出来 / 和基准对不上时，按**函数指纹重合度**挑基准，再按基准世代走。
"""
import os
import re

import ce_boot

ce_boot.bootstrap()

import ce_core as C      # noqa: E402

FAMILIES = ("16", "17", "18", "19", "20", "21")

# 招式效果「重写哪个方法」——v18 起是三件套，v16/v17 只有一个大 pbEffect
_M_LEGACY = ("pbEffect", "pbAdditionalEffect", "pbEffectAfterHit")
_M_MODERN = ("pbEffectGeneral", "pbEffectAgainstTarget", "pbAdditionalEffect")
MOVE_METHODS = {
    "16": _M_LEGACY, "17": _M_LEGACY,
    "18": _M_MODERN, "19": _M_MODERN, "20": _M_MODERN, "21": _M_MODERN,
}


def game_funcs(game_dir):
    """整份游戏脚本的函数指纹 → {脚本名: {限定名: 指纹}}（ce_core 里有缓存）。"""
    return C.scan_game_scripts(os.path.abspath(str(game_dir)))


def family_of(version):
    """版本号 → 引擎世代（16 / 17 / 18 / 19 / 20 / 21）。认不出返回 ""。"""
    m = re.match(r"^(\d+)", str(version or "").strip())
    if not m:
        return ""
    major = m.group(1)
    return major if major in FAMILIES else ""


def _baseline_of(game_dir, version):
    """(基准版本, 是否完全相同, 判定依据)。"""
    if version:
        bver, exact = C.pick_baseline_version(version)
        if bver:
            base = C.load_baseline(bver) or {}
            if base:
                cur = C.flat_funcs(game_funcs(game_dir))
                want = C.flat_funcs(base)
                hit = sum(1 for k, h in want.items() if cur.get(k) == h)
                ratio = hit / float(len(want)) if want else 0.0
                if ratio >= 0.5:
                    return bver, exact, "版本号 %s（指纹重合 %.0f%%）" % (
                        version, ratio * 100)
    cur = game_funcs(game_dir)
    auto, ratio = C.best_baseline(cur) if cur else (None, 0.0)
    if auto:
        return auto, False, "按函数指纹认出 v%s（重合 %.0f%%）" % (auto, ratio * 100)
    if not C.list_baselines():
        return "", False, "没带基准数据（data/baselines.json.gz 缺失），也读不出版本号"
    return "", False, "认不出引擎世代"


def profile(game_dir, deep=False):
    """体检报告 → dict。deep=True 时顺便读注册表（多花 0.5~1 秒）。"""
    root = os.path.abspath(str(game_dir or ""))
    if not os.path.isdir(root):
        raise FileNotFoundError("游戏目录不存在：%s" % game_dir)

    version = C.essentials_version(root)
    bver, exact, why = _baseline_of(root, version)
    family = family_of(bver or version)

    containers = []
    for mode, path in C.scripts_containers(root):
        if mode == "rxdata":
            _got, total = C.read_rxdata_entries(path)
            n = total
        else:
            n = 0
            for _dp, _dn, fs in os.walk(path):
                n += sum(1 for f in fs if str(f).endswith(".rb"))
        containers.append({"mode": mode, "path": path, "entries": n})

    names = {name for _m, _k, _p, name, _t
             in C.iter_named_scripts(root, both=False)}

    out = {
        "root": root,
        "version": version,
        "baseline": bver,
        "baseline_exact": bool(exact),
        "baseline_why": why,
        "family": family,
        "move_methods": list(MOVE_METHODS.get(family, ("pbEffect",))),
        "containers": containers,
        "script_count": len(names),
        "data_dir": C.data_dir(root),
        "pbs": pbs_info(root),
        "plugin": {
            "has_manager": C.has_plugin_manager(root),
            "install_mode": ("plugins" if (C.has_plugin_manager(root)
                                           and os.path.isdir(
                                               os.path.join(root, "Plugins")))
                             else "scripts"),
        },
        "warnings": [],
    }
    if not containers:
        out["warnings"].append(
            "找不到任何脚本容器（Data/Scripts 与 Scripts.rxdata 都没有）")
    if not out["pbs"].get("dir"):
        out["warnings"].append(
            "没有 PBS 目录：新增特性/道具/招式无法自动建数据，只能挂到已有 ID 上")
    if not family:
        out["warnings"].append(
            "认不出 Essentials 版本 —— 先跑 `func` 看看关键函数在不在")

    if deep:
        import ce_locate as L
        tables = L.handler_tables(root)
        out["handlers"] = {
            kind: {"container": slot["container"],
                   "count": len(slot["handlers"]),
                   "names": sorted(slot["handlers"])}
            for kind, slot in tables.items()
        }
        out["moves"] = L.move_containers(root)
    return out


# ------------------------------------------------------------------
# 引擎改动检查（函数指纹 vs 官方基准）
# ------------------------------------------------------------------
def func_check(game_dir, script, fname, baseline=None):
    """
    游戏里某个函数 vs 官方基准 → dict

      status: same / changed / missing_game / missing_base / no_baseline
    """
    bver = baseline
    if bver is None:
        p = profile(game_dir)
        bver = p["baseline"]
    scripts = game_funcs(game_dir)
    base = (C.load_baseline(bver) or {}) if bver else {}
    fp_base = (base.get(script) or {}).get(fname)
    fp_game = (scripts.get(script) or {}).get(fname)
    # ★ 限定名可能是 `Battle::Move.from_pokemon_move`（模块里定义的），
    #   只给短名时要能对上 —— 按后缀再找一遍。
    if fp_game is None:
        for k, v in (scripts.get(script) or {}).items():
            if k.split(".")[-1] == fname:
                fp_game = v
                break
    if fp_base is None:
        for k, v in (base.get(script) or {}).items():
            if k.split(".")[-1] == fname:
                fp_base = v
                break
    got = _func_source(game_dir, script, fname)
    if fp_game is None:
        status = "missing_game"
    elif fp_base is None:
        status = "no_baseline" if base else "missing_base"
    else:
        status = "same" if fp_game == fp_base else "changed"
    return {"script": script, "func": fname, "status": status,
            "fp_game": fp_game, "fp_base": fp_base, "baseline": bver,
            "line": (got or {}).get("line", 0),
            "source": (got or {}).get("source", "")}


def _func_source(game_dir, script, fname):
    import ce_locate as L
    return L.func(game_dir, script, fname)


def script_state(game_dir, script, baseline=None):
    """
    某个脚本整体 vs 官方基准 → {"total","same","changed","changed_funcs"}

    ★ 用途：确认「这个游戏的战斗引擎还是不是原版」。作者改过引擎时，
      挂处理器仍然安全（处理器是官方留的口子），但 alias 覆盖函数要小心。
    """
    bver = baseline
    if bver is None:
        bver = profile(game_dir)["baseline"]
    base = (C.load_baseline(bver) or {}).get(script) or {}
    cur = game_funcs(game_dir).get(script) or {}
    changed = sorted(f for f, fp in base.items() if cur.get(f) not in (None, fp))
    return {"script": script, "baseline": bver, "total": len(base),
            "same": len(base) - len(changed), "changed": len(changed),
            "changed_funcs": changed[:40], "game_funcs": len(cur)}


# ------------------------------------------------------------------
# 数据 ID
# ------------------------------------------------------------------
PBS_FILES = C.PBS_FILES

_SECTION_RE = C._SECTION_RE


def pbs_info(game_dir):
    """PBS 目录 + 每个数据文件有多少条 ID。"""
    d = C.pbs_dir(os.path.abspath(str(game_dir)))
    out = {"dir": d, "style": "", "counts": {}}
    if not d:
        return out
    for kind in ("ability", "item", "move"):
        ids = C.read_pbs_ids(game_dir, kind)
        if ids is None:
            continue
        out["counts"][kind] = len(ids)
        if not out["style"]:
            out["style"] = "section" if _is_section_file(
                os.path.join(d, C.PBS_FILES[kind])) else "csv"
    return out


def _is_section_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(4000)
    except OSError:
        return False
    return bool(_SECTION_RE.search(head))


def read_pbs_ids(game_dir, kind):
    """PBS 里某类数据的 ID 集合；文件不存在返回 None。"""
    return C.read_pbs_ids(game_dir, kind)


def pbs_info_dir(game_dir):
    return C.pbs_dir(os.path.abspath(str(game_dir)))


def read_dat_ids(game_dir, kind):
    """从 Data/<kind>.dat 读 ID（没有 PBS 的成品游戏用）。读不到返回 None。"""
    return C.read_dat_ids(game_dir, kind)


def plugin_defines(game_dir, method):
    """
    插件里有没有重新定义这个方法 → ["插件/文件", ...]

    ★ 我们的脚本是普通脚本，**先于插件** eval；插件里 `def abilityActive?` 会把
      我们的覆盖顶掉（实测：登神 + Generation 9 Pack）。有这个命中就必须
      用 --defer（delayed 到 PluginManager.runPlugins 之后）打补丁。
    """
    if not method:
        return []
    rx = re.compile(r"^[ \t]*def[ \t]+" + re.escape(str(method)) + r"(?![\w?!])",
                    re.M)
    return ["%s / %s" % (plugin, fname)
            for plugin, fname, text in C.plugin_scripts(game_dir)
            if rx.search(text)]


def data_ids(game_dir, kind):
    """某类数据的全部 ID → (集合 or None, 来源说明)。先 PBS 后 .dat。"""
    return C.data_ids(game_dir, kind)
