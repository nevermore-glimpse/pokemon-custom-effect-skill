# -*- coding: utf-8 -*-
"""
自测：拿官方 20.1（解包形态）和 16（rxdata 形态）各跑一遍完整链路。

    python pokemon-custom-effect/tests/selftest.py [--keep]

★ 全程在 Temp/ 下复制副本上做，绝不碰 E:/Pokemon Essentials 原目录。
★ 用 D:/python/.venv/Scripts/python.exe 跑（managed python 没有 tkinter，
  但这里不需要 tkinter；主要是为了和主项目其他测试保持一致）。
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import ce_boot                                     # noqa: E402

ROOT = ce_boot.bootstrap()

import ce_apply as A                               # noqa: E402
import ce_emit as E                                # noqa: E402
import ce_game as G                                # noqa: E402
import ce_locate as L                              # noqa: E402
import ce_verify as V                              # noqa: E402
import ce_core as C                               # noqa: E402

SRC = "E:/Pokemon Essentials"
TMP = os.path.join(ROOT, "Temp")
fails = []


def check(name, cond, detail=""):
    print(("  [ok] " if cond else "  [FAIL] ") + name + (
        "" if cond else "  " + str(detail)))
    if not cond:
        fails.append(name)


def make_v20():
    """解包形态：Data/Scripts + 1 条占位 rxdata。"""
    d = os.path.join(TMP, "ce_self_v20")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "Data"))
    shutil.copytree(os.path.join(SRC, "pokemon-essentials-20.1", "Data",
                                 "Scripts"), os.path.join(d, "Data", "Scripts"))
    shutil.copyfile(os.path.join(SRC, "pokemon-essentials-20.1", "Data",
                                 "Scripts.rxdata"),
                    os.path.join(d, "Data", "Scripts.rxdata"))
    shutil.copytree(os.path.join(SRC, "pokemon-essentials-20.1", "PBS"),
                    os.path.join(d, "PBS"))
    return d


def make_v16():
    """rxdata 形态：只有 Scripts.rxdata。"""
    d = os.path.join(TMP, "ce_self_v16")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "Data"))
    shutil.copyfile(os.path.join(SRC, "pokemon-essentials-16", "Data",
                                 "Scripts.rxdata"),
                    os.path.join(d, "Data", "Scripts.rxdata"))
    return d


BODY_AB = """battle.pbShowAbilitySplash(battler)
battle.allOtherSideBattlers(battler.index).each do |b|
  next if !b.near?(battler)
  next if !b.pbCanLowerStatStage?(:ATTACK, battler)
  b.pbLowerStatStage(:ATTACK, 1, battler)
end
battle.pbHideAbilitySplash(battler)
"""

BODY_LEGACY = "return ret * 2 if hasWorkingAbility?(:SWIFTSWIM)\n"


def test_v20():
    print("\n== v20.1（解包形态）")
    g = make_v20()
    p = G.profile(g, deep=True)
    check("识别版本 20.1", p["version"] == "20.1", p["version"])
    check("世代 20", p["family"] == "20", p["family"])
    check("读到 AbilityEffects 注册表",
          (p["handlers"].get("ability") or {}).get("container")
          == "Battle::AbilityEffects")
    check("招式效果类在 Battle::Move",
          "Battle::Move" in (p.get("moves") or {}))
    check("PBS 章节式", p["pbs"].get("style") == "section", p["pbs"])

    hooks = E.guess_hook(g, "ability", "登场时降低对手攻击")
    check("推荐出 OnSwitchIn", hooks and hooks[0]["hook"] == "OnSwitchIn",
          hooks[:1])
    check("参数表 4 个", hooks and hooks[0]["args"] ==
          ["ability", "battler", "battle", "switch_in"], hooks[0]["args"])

    code = E.render("ability", "20", "OnSwitchIn", "INTIMIDATE", "t_ab",
                    BODY_AB, desc="测试", game_dir=g)
    check("补全限定名", "Battle::AbilityEffects::OnSwitchIn.add" in code)
    check("结构校验通过", V.check_snippet(code, g)["ok"],
          V.check_snippet(code, g)["problems"])

    rep = A.upsert(g, "t_ab", code)
    check("写入成功", rep["verified"], rep)
    ok, n = A.check_installed(g, "t_ab")
    check("回读有这一趴", ok and n == 1, (ok, n))
    f = [t for t in rep["targets"] if t["mode"] == "file"][0]
    check("脚本名排在 Main 前", os.path.basename(f["path"]).startswith("998"),
          f["path"])

    rep2 = A.upsert(g, "t_ab", code)
    check("同 slug 重写 = 替换不是叠加", A.check_installed(g, "t_ab")[1] == 1,
          rep2)

    A.upsert(g, "t_ab2", code.replace("t_ab", "t_ab2"))
    check("两段并存", A.check_installed(g, "t_ab")[1] == 2)
    A.remove(g, "t_ab")
    ok, n = A.check_installed(g, "t_ab")
    check("删一段后剩一段", (not ok) and n == 1, (ok, n))
    A.remove(g, "t_ab2")
    check("全删后脚本文件没了",
          not os.path.isfile(A._file_path(g)), A._file_path(g))

    # 招式
    mv = E.render("move", "20", "pbEffectGeneral", "TACKLE", "t_mv",
                  "target.pbLowerStatStage(:DEFENSE, 1, user)\n", game_dir=g)
    check("招式类名 Battle::Move::PokeCE", "class Battle::Move::PokeCE" in mv, mv)
    code_taken = E.move_code_taken(g, "20", "PokeCE")
    check("PokeCE 没被占用", not code_taken)


def test_v16():
    print("\n== v16（rxdata 形态）")
    g = make_v16()
    p = G.profile(g)
    check("世代 16", p["family"] == "16", (p["version"], p["family"]))
    check("只有 rxdata 容器",
          [c["mode"] for c in p["containers"]] == ["rxdata"])
    check("没有特性处理器表",
          "ability" not in (L.handler_tables(g) or {}))

    hook = E.guess_hook(g, "ability", "速度翻倍")
    check("老引擎给出 alias 锚点",
          hook and hook[0]["hook"] == "pbSpeed", hook[:1])

    before = C.read_rxdata_entries(C.rxdata_path(g))[1]
    code = E.render("ability", "16", "pbSpeed", "SWIFTSWIM", "t_legacy",
                    BODY_LEGACY, desc="测试", game_dir=g)
    check("生成 alias 外壳",
          "alias __ce_orig_pbSpeed pbSpeed" in code
          and "method_defined?(:__ce_orig_pbSpeed)" in code, code)
    check("结构校验通过", V.check_snippet(code, g)["ok"],
          V.check_snippet(code, g)["problems"])

    A.upsert(g, "t_legacy", code)
    ents = C.read_rxdata_entries(C.rxdata_path(g))[0]
    total = C.read_rxdata_entries(C.rxdata_path(g))[1]
    check("条目 +1", total == before + 1, (before, total))
    ce_at = [i for i, t, _x in ents if t == A.CE_TITLE]
    main_at = [i for i, t, _x in ents if t.strip().lower() == "main"]
    check("插在 Main 前面", ce_at and main_at and ce_at[0] < main_at[0],
          (ce_at, main_at))

    A.remove(g, "t_legacy")
    check("删完条目还原", C.read_rxdata_entries(C.rxdata_path(g))[1] == before)


def test_doctor():
    print("\n== 引擎指纹 / 基准")
    g = os.path.join(TMP, "ce_self_v20")
    st = G.script_state(g, "Battle_AbilityEffects")
    check("官方 20.1 战斗脚本零改动",
          st["changed"] == 0 and st["total"] > 0, st)
    fc = G.func_check(g, "Battle_Move", "from_pokemon_move")
    check("from_pokemon_move 与基准一致", fc["status"] == "same", fc["status"])


def main():
    test_v20()
    test_v16()
    test_doctor()
    print("\n%s" % ("全部通过" if not fails else "失败 %d 项：%s"
                    % (len(fails), ", ".join(fails))))
    if "--keep" not in sys.argv:
        for d in ("ce_self_v20", "ce_self_v16"):
            shutil.rmtree(os.path.join(TMP, d), ignore_errors=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
