# -*- coding: utf-8 -*-
"""
命令行入口（给 AI / 人用同一套）：

    python pokemon-custom-effect/ce_cli.py <命令> <游戏目录> [参数]

命令一览
--------
    scan     <game> [--deep]                体检：版本、引擎世代、脚本容器、PBS
    hooks    <game> --kind ability [--want 登场时降攻击] [--all]
                                            可用的效果钩子 + 参数表（现读游戏）
    func     <game> --script PokeBattle_Battler --name pbSpeed
                                            某函数源码 + 与官方基准比对
    state    <game> --script Battle_AbilityEffects
                                            某脚本整体 vs 官方基准（作者改过多少）
    class    <game> --name StatUpMove       取某个招式效果类的源码
    grep     <game> --pattern REGEX         在全部脚本里搜
    check    <game> --kind ability --id X   这个 ID 在 PBS / .dat 里存不存在
    render   <game> --kind ability --id X --hook OnSwitchIn --body b.rb
                                            只生成代码，不落盘
    install  <game> --kind ... --slug my_ability --body b.rb
                                            生成 + 校验 + 写进游戏（默认 dry-run 关闭）
    remove   <game> --slug my_ability       只删这一段
    list     <game>                         现在装了哪些段
    verify   <game> [--file f]              语法/结构校验

所有命令都输出 JSON（UTF-8），方便直接贴给模型看。
"""
import argparse
import io
import json
import sys

import ce_boot

ce_boot.bootstrap()

import ce_apply as A      # noqa: E402
import ce_emit as E       # noqa: E402
import ce_game as G       # noqa: E402
import ce_locate as L     # noqa: E402
import ce_verify as V     # noqa: E402


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    return 0


def _read_body(args):
    if args.inline:
        return args.inline
    if not args.body:
        raise SystemExit("缺 --body <文件> 或 --inline <代码>")
    with io.open(args.body, "r", encoding="utf-8") as f:
        return f.read()


def _args_list(text):
    if not text:
        return None
    return [x.strip() for x in str(text).split(",") if x.strip()]


# ------------------------------------------------------------------
def cmd_doctor(args):
    """环境自检：Python 版本、自带依赖、有没有主项目、能不能读这个游戏。"""
    info = ce_boot.info()
    res = {"env": info, "official_src": L.official_available()}
    if args.game:
        p = G.profile(args.game, deep=True)
        res["game"] = {k: p[k] for k in ("root", "version", "family",
                                         "baseline", "baseline_why",
                                         "script_count", "warnings")}
        res["game"]["containers"] = p["containers"]
        res["game"]["handlers"] = {k: {"container": v["container"],
                                       "count": v["count"]}
                                   for k, v in (p.get("handlers") or {}).items()}
    return out(res)


def cmd_scan(args):
    return out(G.profile(args.game, deep=args.deep))


def cmd_hooks(args):
    fam = G.profile(args.game)["family"]
    if args.want:
        got = E.guess_hook(args.game, args.kind, args.want, fam)
        if args.all:
            return out({"kind": args.kind, "want": args.want,
                        "candidates": got})
        return out({"kind": args.kind, "want": args.want,
                    "best": got[0] if got else None, "candidates": got[:5]})
    tables = L.handler_tables(args.game, only=args.kind)
    slot = tables.get(args.kind) or {}
    return out({"kind": args.kind,
                "container": slot.get("container", ""),
                "count": len(slot.get("handlers") or {}),
                "handlers": [{"hook": h, "args": i["args"],
                              "sample": i["sample"], "how": i["how"]}
                             for h, i in sorted((slot.get("handlers") or {}).items())]})


def cmd_func(args):
    res = G.func_check(args.game, args.script, args.name)
    if args.official:
        res["official_source"] = L.engine_ref(res.get("baseline") or "",
                                              args.script, args.name)
        if not res["official_source"]:
            res["official_note"] = ("拿不到官方源码（没装主项目「宝可梦同人工具」，"
                                    "或这个版本没内置）")
    return out(res)


def cmd_state(args):
    return out(G.script_state(args.game, args.script))


def cmd_class(args):
    got = L.move_class(args.game, args.name)
    if not got:
        return out({"error": "找不到招式效果类 %s" % args.name})
    return out(got)


def cmd_grep(args):
    hits = L.grep(args.game, args.pattern, limit=args.limit)
    return out({"pattern": args.pattern, "count": len(hits), "hits": hits})


def cmd_check(args):
    fam = G.profile(args.game)["family"]
    code = args.code
    if args.kind == "move" and not code:
        code = E.suggest_move_code(args.game, fam)
    info = E.pbs_hint(args.game, args.kind, args.id, code=code)
    if args.kind == "move":
        info["function_code"] = code
        info["class_name"] = E.move_class_name(fam, code)
        info["code_taken"] = E.move_code_taken(args.game, fam, code)
    return out(info)


def _defer(args, prof):
    """要不要把补丁延迟到插件加载之后（auto = 有插件系统就延迟）。"""
    mode = getattr(args, "defer", "auto")
    if mode == "auto":
        return bool((prof.get("plugin") or {}).get("has_manager"))
    return mode == "on"


def _need_id(args):
    if args.kind not in ("patch", "snippet") and not args.id:
        raise SystemExit("--kind %s 必须给 --id" % args.kind)


def cmd_render(args):
    _need_id(args)
    prof = G.profile(args.game)
    fam = prof["family"]
    code = args.code
    if args.kind == "move" and not code:
        code = E.suggest_move_code(args.game, fam)
    defer = _defer(args, prof)
    text = E.render(args.kind, fam, args.hook, args.id, args.slug,
                    _read_body(args), desc=args.desc or "",
                    args=_args_list(args.args), code=code,
                    parent=args.parent, game_dir=args.game, defer=defer)
    chk = V.check_snippet(text, args.game)
    res = {"family": fam, "kind": args.kind, "slug": args.slug,
           "defer": defer, "code": text, "verify": chk}
    if args.kind == "move":
        res["function_code"] = code
        res["class_name"] = E.move_class_name(fam, code)
    if args.kind in ("ability", "item"):
        res["data"] = E.pbs_hint(args.game, args.kind, args.id)
    if args.kind == "patch":
        res["patched"] = "%s#%s" % (args.parent or "?", args.hook or "?")
        ov = G.plugin_defines(args.game, args.hook)
        res["plugin_overrides"] = ov
        if ov and not defer:
            res["warning"] = ("这些插件里也定义了 %s：%s。插件在普通脚本之后加载，"
                              "现在这个补丁会被顶掉 —— 去掉 --defer off 重装（或让"
                              "--defer 保持 auto）" % (args.hook, "；".join(ov)))
    if args.out:
        with io.open(args.out, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        res["out"] = args.out
    return out(res)


def cmd_install(args):
    _need_id(args)
    prof = G.profile(args.game)
    fam = prof["family"]
    code = args.code
    if args.kind == "move" and not code:
        code = E.suggest_move_code(args.game, fam)
    defer = _defer(args, prof)
    text = E.render(args.kind, fam, args.hook, args.id, args.slug,
                    _read_body(args), desc=args.desc or "",
                    args=_args_list(args.args), code=code,
                    parent=args.parent, game_dir=args.game, defer=defer)
    chk = V.check_snippet(text, args.game)
    res = {"family": fam, "slug": args.slug, "defer": defer, "verify": chk,
           "code": text, "applied": None,
           "data": E.pbs_hint(args.game, args.kind, args.id) if
           args.kind in ("ability", "item") else None}
    if args.kind == "move":
        res["function_code"] = code
        res["class_name"] = E.move_class_name(fam, code)
    if args.kind == "patch":
        ov = G.plugin_defines(args.game, args.hook)
        res["plugin_overrides"] = ov
        if ov and not defer:
            res["warning"] = (
                "这些插件里也定义了 %s：%s。插件在普通脚本之后加载，"
                "现在这个补丁会被顶掉 —— 用 --defer on 重装"
                % (args.hook, "；".join(ov)))
    if chk["ok"] or args.force:
        if defer:
            # 先装延迟安装器（只装一次，多个补丁共用）
            A.remove(args.game, E.PLUGIN_HOOK_SLUG, dry=args.dry)
            res["hook"] = A.upsert(args.game, E.PLUGIN_HOOK_SLUG,
                                   E.PLUGIN_HOOK_CODE, dry=args.dry,
                                   at_top=True)
        res["applied"] = A.upsert(args.game, args.slug, text, dry=args.dry)
        ok, n = A.check_installed(args.game, args.slug)
        res["readback"] = {"block_present": ok, "blocks": n}
    else:
        res["applied"] = {"skipped": "校验没过，加 --force 可强行写入"}
    return out(res)


def cmd_remove(args):
    return out(A.remove(args.game, args.slug, dry=args.dry))


def cmd_list(args):
    return out({"script": A.read_ce_script(args.game)[:200],
                "blocks": A.list_blocks(args.game)})


def cmd_verify(args):
    if args.file:
        with io.open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = A.read_ce_script(args.game)
        if not text:
            return out({"error": "游戏里还没有 [ce] 脚本"})
    return out(V.check_snippet(text, args.game))


# ------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="ce_cli", description="宝可梦同人工具 · 自定义效果（特性/道具/招式）")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_)
        s.add_argument("game", help="游戏根目录（有 Game.ini / Data 的目录）")
        s.set_defaults(func=fn)
        return s

    s = sub.add_parser("doctor", help="环境自检（Python / 自带依赖 / 主项目 / 游戏）")
    s.add_argument("game", nargs="?", default="", help="顺便体检这个游戏（可选）")
    s.set_defaults(func=cmd_doctor)

    s = add("scan", cmd_scan, "体检：版本 / 引擎世代 / 脚本容器 / PBS")
    s.add_argument("--deep", action="store_true", help="顺便读效果注册表")

    s = add("hooks", cmd_hooks, "列出可用的效果钩子（或按需求推荐）")
    s.add_argument("--kind", default="ability",
                   choices=["ability", "item", "move"])
    s.add_argument("--want", default="", help="中文需求，例如「登场时降低对手攻击」")
    s.add_argument("--all", action="store_true", help="列出全部候选")

    s = add("func", cmd_func, "某函数源码 + 与官方基准比对")
    s.add_argument("--script", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--official", action="store_true",
                   help="顺便给出官方源码（需要主项目）")

    s = add("state", cmd_state, "某脚本整体 vs 官方基准")
    s.add_argument("--script", required=True)

    s = add("class", cmd_class, "取招式效果类源码")
    s.add_argument("--name", required=True)

    s = add("grep", cmd_grep, "在全部脚本里搜正则")
    s.add_argument("--pattern", required=True)
    s.add_argument("--limit", type=int, default=60)

    s = add("check", cmd_check, "ID 是否存在于 PBS / .dat")
    s.add_argument("--kind", required=True, choices=["ability", "item", "move"])
    s.add_argument("--id", required=True)
    s.add_argument("--code", default="", help="招式 FunctionCode（不给就自动挑）")

    def body_opts(s):
        s.add_argument("--kind", required=True,
                       choices=["ability", "item", "move", "patch", "snippet"])
        s.add_argument("--id", default="", help="特性/道具/招式 ID（patch 不需要）")
        s.add_argument("--hook", default="")
        s.add_argument("--slug", required=True)
        s.add_argument("--body", default="", help="代码正文文件")
        s.add_argument("--inline", default="", help="代码正文（直接给字符串）")
        s.add_argument("--args", default="", help="参数名，逗号分隔（不给就现读）")
        s.add_argument("--code", default="", help="招式 FunctionCode")
        s.add_argument("--parent", default="",
                       help="招式父类；patch 时是要覆盖的类（如 Battle::Battler）")
        s.add_argument("--desc", default="", help="这段代码的说明（写进注释）")

    s = add("render", cmd_render, "只生成代码，不落盘")
    body_opts(s)
    s.add_argument("--out", default="")
    s.add_argument("--defer", default="auto", choices=["auto", "on", "off"],
                   help="patch 延迟到插件加载之后（auto：有插件就延迟）")

    s = add("install", cmd_install, "生成 + 校验 + 写进游戏")
    body_opts(s)
    s.add_argument("--dry", action="store_true")
    s.add_argument("--force", action="store_true", help="校验没过也写")
    s.add_argument("--defer", default="auto", choices=["auto", "on", "off"],
                   help="patch 延迟到插件加载之后（auto：有插件就延迟）")

    s = add("remove", cmd_remove, "只删一段")
    s.add_argument("--slug", required=True)
    s.add_argument("--dry", action="store_true")

    add("list", cmd_list, "现在装了哪些段")

    s = add("verify", cmd_verify, "校验语法/结构")
    s.add_argument("--file", default="")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        return out({"error": str(e)})
    except Exception as e:                              # noqa: BLE001
        return out({"error": "%s: %s" % (type(e).__name__, e)})


if __name__ == "__main__":
    sys.exit(main())
