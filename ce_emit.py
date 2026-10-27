# -*- coding: utf-8 -*-
"""
生成代码：把「需求 + 钩子 + 参数表」套进对应世代的模板。

三种效果 × 四代 API：

  特性  v18+  {{REGISTRY}}::{{HOOK}}.add(:ID, proc { |参数来自游戏自己| … })
        legacy class PokeBattle_Battler; alias 原方法; 加分支
  道具  v18+  同上（BattleHandlers / Battle::ItemEffects），
        背包那种走 ItemHandlers::UseOnPokemon
  招式  v20+  class Battle::Move::<FunctionCode> < Battle::Move
        v18/19 class PokeBattle_Move_<FunctionCode> < PokeBattle_Move
        legacy class PokeBattle_Move_<FunctionCode> + 五参数 pbEffect

★ 参数表**永远**从游戏里现读（ce_locate.handler_tables），模板只负责骨架：
  v19 的 SpeedCalcAbility 是 |ability,battler,mult|，
  v20 的 SpeedCalc 也是 |ability,battler,mult|，但 OnSwitchIn 是四参数 ——
  写死一个版本必错。
"""
import difflib
import io
import os
import re

import ce_boot

ce_boot.bootstrap()

import ce_game as G      # noqa: E402
import ce_locate as L    # noqa: E402

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "templates")

# 延迟安装器：插件脚本在普通脚本**之后**才 eval，要覆盖方法的补丁必须等它跑完。
# slug 固定，装一次就够，多个补丁共用。
PLUGIN_HOOK_SLUG = "ce_plugin_hook"
PLUGIN_HOOK_CODE = """# ---- ce_plugin_hook ----
# 延迟安装器：这个游戏有插件，插件脚本在普通脚本之后才 eval。
# 需要覆盖引擎方法时，用 PkmnCE.after_plugins { ... } 把补丁推迟到插件加载完再打。
module PkmnCE
  class << self
    def after_plugins(&blk)
      (@after_plugins ||= []) << blk
      if defined?(PluginManager) && PluginManager.respond_to?(:runPlugins)
        hook_plugin_manager
      else
        run_after_plugins
      end
    end

    def run_after_plugins
      list = @after_plugins || []
      @after_plugins = []
      list.each { |b| b.call }
    end

    def hook_plugin_manager
      return if @hooked
      @hooked = true
      PluginManager.module_eval do
        class << self
          alias_method :__ce_orig_runPlugins, :runPlugins
          def runPlugins(*args)
            ret = __ce_orig_runPlugins(*args)
            PkmnCE.run_after_plugins
            ret
          end
        end
      end
    end
  end
end"""


# 招式效果方法 → 参数表（官方基准签名，不是猜的）
MOVE_METHOD_ARGS = {
    "pbEffect": "attacker, opponent, hitnum = 0, alltargets = nil, showanimation = true",
    "pbAdditionalEffect": "user, target",
    "pbEffectAfterHit": "attacker, opponent, turneffects",
    "pbEffectGeneral": "user",
    "pbEffectAgainstTarget": "user, target",
    "pbEffectWhenDealingDamage": "user, target",
    "pbEffectAfterAllHits": "user, target",
}
# v16/v17 的 pbAdditionalEffect 是两参数
LEGACY_MOVE_METHOD_ARGS = {
    "pbEffect": "attacker, opponent, hitnum = 0, alltargets = nil, showanimation = true",
    "pbAdditionalEffect": "attacker, opponent",
    "pbEffectAfterHit": "attacker, opponent, turneffects",
}

# 「玩家说法 → 处理器名」的关键词表（顺序无关，命中越多越靠前）
HOOK_KEYWORDS = (
    (("登场", "上场", "换入", "出场"), ("OnSwitchIn", "pbAbilitiesOnSwitchIn")),
    (("下场", "换下", "离场"), ("OnSwitchOut",)),
    (("速度", "先手", "先制", "优先度", "优先"), ("SpeedCalc", "PriorityChange",
                                                "PriorityBracketChange")),
    (("增伤", "伤害提高", "威力提高", "加强伤害"), ("DamageCalcFromUser",
                                                   "DamageCalcUser")),
    (("减伤", "受伤减", "抵抗", "耐打"), ("DamageCalcFromTarget",)),
    (("命中", "命中率"), ("AccuracyCalcFromUser", "AccuracyCalcFromTarget")),
    (("暴击", "会心"), ("CriticalCalcFromUser", "CriticalCalcFromTarget")),
    (("免疫", "无效", "挡下"), ("MoveImmunity", "MoveBlocking",
                                "StatusImmunity", "MoveImmunityTarget")),
    (("被击中", "挨打", "受到攻击"), ("OnBeingHit", "TargetAbilityOnHit",
                                      "TargetItemOnHit")),
    (("攻击后", "打中后", "造成伤害"), ("OnDealingHit", "UserAbilityOnHit",
                                        "pbEffectsOnDealingDamage")),
    (("回合结束", "每回合"), ("EndOfRoundEffect", "EndOfRoundHealing",
                              "EndOfRoundWeather")),
    (("状态", "异常", "中毒", "麻痹", "睡眠", "灼伤", "冰冻"),
     ("OnStatusInflicted", "StatusImmunity", "StatusCure")),
    (("回复", "回血", "治疗"), ("EndOfRoundHealing", "OnHPDroppedBelowHalf",
                                "HPHealItem")),
    (("倒下", "濒死", "被打倒"), ("ChangeOnBattlerFainting", "OnBattlerFainting")),
    (("天气",), ("EndOfRoundWeather", "OnTerrainChange")),
    (("能力等级", "降能力", "升能力"), ("StatLossImmunity", "OnStatLoss",
                                        "OnStatGain")),
)

# v16 / v17 只能挂钩方法：给几个确认存在的锚点
LEGACY_ANCHORS = {
    "速度": ("PokeBattle_Battler", "pbSpeed"),
    "先制": ("PokeBattle_Battler", "pbSpeed"),
    "登场": ("PokeBattle_Battler", "pbAbilitiesOnSwitchIn"),
    "上场": ("PokeBattle_Battler", "pbAbilitiesOnSwitchIn"),
    "伤害": ("PokeBattle_Battler", "pbEffectsOnDealingDamage"),
    "攻击后": ("PokeBattle_Battler", "pbEffectsOnDealingDamage"),
}

# 招式 FunctionCode 建议值（避开官方 000-1FF 与描述式命名）
_DEFAULT_MOVE_CODE = {"legacy": "1F0", "v18": "1F0", "v19": "1F0"}


def read_template(name):
    with io.open(os.path.join(TEMPLATE_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def _indent(text, n=4):
    pad = " " * n
    lines = str(text or "").strip("\n").split("\n")
    return "\n".join((pad + ln) if ln.strip() else ""
                     for ln in lines)


def _fill(tpl, mapping):
    out = tpl
    for k, v in mapping.items():
        out = out.replace("{{%s}}" % k, str(v))
    return out


# ------------------------------------------------------------------
# 钩子推荐
# ------------------------------------------------------------------
def guess_hook(game_dir, kind, want, family=None):
    """
    按中文需求推荐处理器 → [{"hook","args","qualified","score","note"}, ...]

    kind = ability / item / move
    ★ 招式没有处理器，返回的是「重写哪个方法」的候选。
    """
    fam = family or G.profile(game_dir)["family"]
    want = str(want or "")
    if kind == "move":
        methods = G.MOVE_METHODS.get(fam, ("pbEffect",))
        out = []
        for m in methods:
            score = 0
            if any(k in want for k in ("追加", "额外", "附加")) and "Additional" in m:
                score += 3
            if any(k in want for k in ("全体", "所有目标", "对目标")) and \
                    "AgainstTarget" in m:
                score += 2
            out.append({"hook": m, "score": score,
                        "args": (LEGACY_MOVE_METHOD_ARGS if fam in ("16", "17")
                                 else MOVE_METHOD_ARGS).get(m, "")})
        out.sort(key=lambda x: -x["score"])
        return out

    tables = L.handler_tables(game_dir, only=kind)
    handlers = (tables.get(kind) or {}).get("handlers") or {}
    prefix = (tables.get(kind) or {}).get("prefix") or ""

    cands = []
    for kw, hooks in HOOK_KEYWORDS:
        if not any(k in want for k in kw):
            continue
        for h in hooks:
            for name, info in handlers.items():
                core = name.replace("Ability", "").replace("Item", "")
                if h.lower() in core.lower() or core.lower() in h.lower():
                    cands.append({
                        "hook": name,
                        "args": info.get("args") or [],
                        "qualified": info.get("qualified") or prefix + name,
                        "sample": info.get("sample", ""),
                        "score": len(h) + 1,
                        "container": (tables.get(kind) or {}).get("container"),
                    })
    # 同分去重
    seen, out = set(), []
    for c in sorted(cands, key=lambda x: -x["score"]):
        if c["hook"] in seen:
            continue
        seen.add(c["hook"])
        out.append(c)

    if not out and fam in ("16", "17") and kind in ("ability", "item"):
        for kw, (cls, meth) in LEGACY_ANCHORS.items():
            if kw in want:
                out.append({"hook": meth, "args": "", "qualified": "",
                            "score": 1, "legacy_anchor": True, "class": cls,
                            "note": "v16/v17 没有处理器表，只能 alias 覆盖这个方法"})
                break
    return out


# ------------------------------------------------------------------
# 招式 FunctionCode
# ------------------------------------------------------------------
def move_class_name(family, code):
    """招式效果类名（v20 起命名空间是 Battle::Move）。"""
    code = str(code)
    if family in ("20", "21"):
        return ("Battle::Move::Effect" + code) if code[:1].isdigit() \
            else ("Battle::Move::" + code)
    return "PokeBattle_Move_" + code


def move_code_taken(game_dir, family, code):
    """这个 FunctionCode 是否已经被某个招式效果类占用。"""
    return bool(L.move_class(game_dir, str(code)))


def suggest_move_code(game_dir, family):
    """给一个没被占用的 FunctionCode。"""
    if family in ("20", "21"):
        base = "PokeCE"
        n = 0
        while True:
            code = base if n == 0 else "%s%d" % (base, n)
            if not move_code_taken(game_dir, family, code):
                return code
            n += 1
    n = 0x1F0
    while move_code_taken(game_dir, family, "%03X" % n):
        n += 1
    return "%03X" % n


# ------------------------------------------------------------------
# 渲染
# ------------------------------------------------------------------
def render(kind, family, hook, target_id, slug, body, desc="",
           args=None, code=None, parent=None, game_dir=None, defer=False):
    """
    返回成品 Ruby 片段（一段，带 ce:<slug> 标记）。

      kind     ability / item / move
      family   16 / 17 / 18 / 19 / 20 / 21
      hook     ability、item：处理器名（OnSwitchIn / UseOnPokemon …）
               move：重写的方法名（pbEffectGeneral …）
      target_id  特性 / 道具 / 招式的 ID（带不带冒号都行）
      slug     这一段的唯一名字，重跑同 slug 会就地替换
      body     代码正文（不带缩进也行，统一缩进 4 格）
      args     参数名列表（现读的）；不给就按签名默认
      code     move 专用：FunctionCode
      parent   move 专用：父类
    """
    fam = str(family)
    ident = str(target_id or "").strip()
    ident = ident if ident.startswith(":") else ":" + ident if ident else ""
    body_txt = _indent(body)
    desc = desc or slug

    if kind == "move":
        if not code and game_dir:
            code = suggest_move_code(game_dir, fam)
        code = str(code or suggest_move_code_default(fam))
        cls = move_class_name(fam, code)
        tpl_name = "move_class.rb"
        method = hook or (G.MOVE_METHODS.get(fam) or ("pbEffect",))[0]
        if fam in ("16", "17"):
            margs = LEGACY_MOVE_METHOD_ARGS.get(method, "")
        else:
            margs = MOVE_METHOD_ARGS.get(method, "user")
        parent = parent or ("Battle::Move" if fam in ("20", "21")
                            else "PokeBattle_Move")
        return _fill(read_template(tpl_name), {
            "SLUG": slug, "DESC": desc, "CLASS": cls, "PARENT": parent,
            "METHOD": method, "ARGS": margs, "BODY": body_txt, "CODE": code,
        })

    if kind == "snippet":
        # 原样落一段代码（模块定义、自检、调试打印都行）
        return _fill(read_template("snippet.rb"), {
            "SLUG": slug, "DESC": desc, "BODY": str(body or "").strip("\n"),
        })

    if kind == "patch":
        # 覆盖已有方法（alias 原方法后自己实现）。不需要 ID，也不需要钩子表。
        cls = parent or "Object"
        meth = hook or ""
        if not meth:
            raise ValueError("patch 需要 --hook 指定方法名（例如 abilityActive?）")
        alias_name = "__ce_orig_" + re.sub(r"[?!]$", "", meth)
        if defer:
            # 有插件的游戏：插件在我们之后加载，必须延迟到 runPlugins 之后
            return _fill(read_template("patch_deferred.rb"), {
                "SLUG": slug, "DESC": desc, "CLASS": cls, "METHOD": meth,
                "ALIAS": alias_name, "BODY": _indent(body, 6),
            })
        return _fill(read_template("patch_method.rb"), {
            "SLUG": slug, "DESC": desc, "CLASS": cls, "METHOD": meth,
            "ALIAS": alias_name, "BODY": body_txt,
        })

    if kind == "move":
        methods = G.MOVE_METHODS.get(str(family), ("pbEffect",))
        if hook and hook not in methods:
            raise ValueError(
                "v%s 的招式效果只有这几个方法可重写：%s（给的是 %r）"
                % (family, " / ".join(methods), hook))
    argl, qual = _resolve_hook(game_dir, kind, hook, args)
    if kind in ("ability", "item") and str(family) not in ("16", "17"):
        if game_dir and not qual:
            raise ValueError(
                "这个游戏里没有效果处理器 %r。%s" % (hook, _hook_hint(game_dir, kind, hook)))
        if not argl:
            raise ValueError(
                "处理器 %s 抄不到参数表（游戏里没人用过它），请用 --args 明确给出" % qual)

    if kind == "item" and str(hook).startswith(("Use", "Can", "Confirm")):
        return _fill(read_template("item_field.rb"), {
            "SLUG": slug, "DESC": desc, "HOOK": hook, "ID": ident,
            "ARGS": ", ".join(argl), "BODY": body_txt,
        })

    if kind == "ability" and fam in ("16", "17"):
        cls = (args or {}).get("class") if isinstance(args, dict) else None
        anchor = hook or "pbSpeed"
        return _fill(read_template("ability_legacy.rb"), {
            "SLUG": slug, "DESC": desc, "CLASS": cls or "PokeBattle_Battler",
            "ANCHOR": anchor, "ALIAS": "__ce_orig_%s" % anchor,
            "BODY": body_txt,
        })

    # v18+ 的处理器（特性 / 道具战斗效果）
    return _fill(read_template("handler.rb"), {
        "SLUG": slug, "DESC": desc, "QUAL": qual or hook, "ID": ident,
        "ARGS": ", ".join(argl or []), "BODY": body_txt,
    })


def _hook_hint(game_dir, kind, hook):
    """给个「你是不是想找」的候选，别让人对着空结果猜。"""
    tables = L.handler_tables(game_dir, only=kind)
    names = sorted(((tables.get(kind) or {}).get("handlers") or {}))
    near = difflib.get_close_matches(str(hook), names, n=4, cutoff=0.4) or names[:8]
    if not names:
        return "这个世代的 %s 没有处理器表（v16/v17 只能 alias 覆盖方法）" % kind
    return "候选：%s" % " / ".join(near)


def _resolve_hook(game_dir, kind, hook, args):
    """
    钩子名 → (参数名列表, 完整限定名)

    ★ 光给 `OnSwitchIn` 生成出来的代码是 `OnSwitchIn.add(...)` —— 根本不存在。
      必须补成 `Battle::AbilityEffects::OnSwitchIn` / `BattleHandlers::OnSwitchIn`。
    ★ 参数名也从游戏里现读，不猜。
    """
    hook = str(hook or "")
    if "::" in hook:
        short, qual = hook.split("::")[-1], hook
    else:
        short, qual = hook, ""
    argl = list(args) if args else []
    if not game_dir:
        return argl, qual
    tables = L.handler_tables(game_dir, only=kind)
    slot = tables.get(kind) or {}
    info = (slot.get("handlers") or {}).get(short)
    if info:
        if not qual:
            qual = info.get("qualified") or ((slot.get("prefix") or "") + short)
        if not argl:
            argl = info.get("args") or []
    return argl, qual


def suggest_move_code_default(family):
    return _DEFAULT_MOVE_CODE.get(str(family), "1F0")


# ------------------------------------------------------------------
# 数据（PBS）提示
# ------------------------------------------------------------------
PBS_TEMPLATES = {
    # v20+ 章节式
    "section": {
        "ability": "[{id}]\nName = {name}\nDescription = {desc}\n",
        "item": "[{id}]\nName = {name}\nPocket = 1\nPrice = 0\n"
                "Description = {desc}\n",
        "move": "[{id}]\nName = {name}\nType = NORMAL\nCategory = Physical\n"
                "BaseDamage = 40\nAccuracy = 100\nTotalPP = 20\n"
                "Target = NearOther\nFunctionCode = {code}\n"
                "Flags = CanProtect\nDescription = {desc}\n",
    },
    # v16~v19 CSV 式（列顺序：编号,ID,名字,…）
    "csv": {
        "ability": None,   # CSV 的列数按版本变，不自动生成，只提示手填
        "item": None,
        "move": None,
    },
}


def pbs_hint(game_dir, kind, target_id, code=None, name=None, desc=None):
    """
    这个 ID 在游戏数据里存不存在 → dict

      {"exists": True/False/None, "source": "PBS/abilities.txt", "hint": "…"}
      exists=None 表示查不出来（既没 PBS 也没 .dat）。
    """
    ids, source = G.data_ids(game_dir, kind)
    tid = str(target_id or "").lstrip(":").upper()
    info = {"id": tid, "kind": kind, "source": source, "hint": ""}
    if ids is None:
        info["exists"] = None
        info["hint"] = ("找不到 PBS 也没有 Data/%s.dat —— 这个 ID 是否合法无法确认，"
                        "代码先挂着，游戏里若报「Undefined …」就是数据没建" % kind)
        return info
    info["exists"] = tid in ids
    if info["exists"]:
        return info
    style = (G.pbs_info(game_dir).get("style") or "section")
    tpl = (PBS_TEMPLATES.get(style) or {}).get(kind)
    if not tpl:
        info["hint"] = ("PBS/%s 里没有 %s —— 需要先加一条数据（CSV 格式，"
                        "按同文件已有行的列数补），否则效果代码永远不会触发"
                        % (G.PBS_FILES.get(kind, kind), tid))
        return info
    row = tpl.format(id=tid, name=name or tid.title(),
                     desc=desc or "Custom %s" % kind, code=code or "")
    info["hint"] = ("PBS/%s 里没有 %s，把下面这段追加进去，再用游戏的"
                    "「编译数据」重编译一次：\n%s"
                    % (G.PBS_FILES.get(kind, kind), tid, row))
    info["pbs_row"] = row
    return info
