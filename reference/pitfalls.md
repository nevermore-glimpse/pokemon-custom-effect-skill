# 踩坑清单

写代码前扫一眼，能省掉一整轮「改了没效果」。

## 生效相关

1. **必须在 Main 之前执行。** RGSS 从上往下 eval 脚本，读到 `999_Main` 就进主循环。
   `ce_apply` 已经处理：rxdata 插在 Main 条目之前，解包形态把文件名算成
   `998_ce_custom_effects.rb` 这种排在 Main 前面的编号。别自己改成 `zzz_`。
2. **Main 可能是个目录**（v20.1 / v21 是 `999_Main/999_Main.rb`），
   找 Main 要往下走一层，不能只看顶层文件。
3. **两处并存时只改一处 = 改了没效果。** v21 起很多游戏
   `Data/Scripts/**.rb`（解包源码）和 `Data/Scripts.rxdata`（运行时那份）都有，
   到底读哪份看 `Game.ini` 的 `Scripts=`。工具默认两处都写。
4. **`Scripts.rxdata` 少于 10 条 = 解包后留下的空壳**，往里写不会被执行。
   工具会跳过并说明原因。
5. **ID 不存在 = 代码永远不触发。** 特性要在 `PBS/abilities.txt`、招式在
   `moves.txt`、道具在 `items.txt`。改完 PBS 还要用游戏自己的「编译数据」
   重编译一次（v19+ 是编译成 `Data/*.dat`；v16~v18 是标记待重编译）。
6. **招式的 `FunctionCode` 必须和类名对上**：
   v20+ `FunctionCode = PokeCE` ↔ `class Battle::Move::PokeCE`；
   v18/19 `FunctionCode = 1F0` ↔ `class PokeBattle_Move_1F0`。
   数字开头的码在 v20+ 会被拼成 `Battle::Move::Effect<码>`。

## 代码写法

7. **proc 里只能 `next`，不能 `return`。** 在 proc 里 `return` 抛 `LocalJumpError`。
   alias 出来的 def 里才用 `return`。
8. **v19 和 v20 的处理器参数个数不一样。** 例如登场：
   v19 `AbilityOnSwitchIn` 是 `(ability, battler, battle)`，
   v20 `OnSwitchIn` 是 `(ability, battler, battle, switch_in)`。
   照抄别的版本的教程 → `ArgumentError`。
9. **`mults` 是哈希**：`mults[:base_damage_multiplier] *= 1.5`。
   v19 起就是哈希了，网上 v18 时代的 `mults[1] *= 1.5` 是错的。
10. **常量名换代改过**：v19 `PokeBattle_SceneConstants::USE_ABILITY_SPLASH`，
    v20+ `Battle::Scene::USE_ABILITY_SPLASH`。技能演出分支里会用到。
11. **`pbShowAbilitySplash` 必须配 `pbHideAbilitySplash`。** 中间 `next` 掉会
    把特性名残留在战斗画面上。
12. **天气取值**：v20+ `battler.effectiveWeather`，v19 及以前
    `battler.battle.pbWeather`。
13. **属性/道具 ID 全大写，前面带冒号**：`:MYABILITY`。工具会自动补冒号。
14. **对玩家显示的文本用 `_INTL("…")`**，否则翻译工具抓不到。

## 老引擎（v16 / v17）

15. 这两代**没有** `BattleHandlers`，只能 alias 覆盖方法。
    先用 `func --script PokeBattle_Battler --name pbSpeed` 看 `status`；
    不是 `same` 说明作者改过，alias 前先读一遍真实源码。
16. `alias` 要加 `unless method_defined?(:__ce_orig_xxx)` 守卫，
    否则重进游戏 / 重复加载会无限套娃（栈溢出）。
17. v16 的 `ItemHandlers::UseOnPokemon` 参数是 `item, pokemon, scene`
    （没有 `qty`），v18 起才有 `qty`。

## 工程卫生

18. 生成的东西只在 `[ce] custom effects` 这一个脚本里，按 `# >>> ce:<slug>` 分段。
    **slug 必须唯一** —— 两段用同一个 slug 会互相替换。
19. 每次写入都在 `Data/` 下留 `Scripts.rxdata.ce-<时间戳>.bak`。
    确认没问题后可以删，别跟着游戏一起发布。
20. **别手改引擎原函数**（v18+）。处理器是官方留的口子，改原函数会在
    作者更新游戏 / 装别的插件时冲突。
21. 同人游戏加了插件（`Plugins/` 目录）时，我们的脚本仍然排在插件之后、
    Main 之前 —— 效果注册是同名覆盖，靠后注册的生效。
    要「改成别人的效果而不是新增」，才需要看插件的加载顺序。

## 没有钩子的效果，只能 patch

22. **全局压制类**（让对手特性失效、让全场道具失效）引擎**没有**处理器，
    只能覆盖判定入口：v20+ 是 `Battle::Battler#abilityActive?`，
    v19 及以前是 `PokeAbilityActive?`/`PokeBattle_Battler` 里的同名逻辑。
    用 `--kind patch --parent Battle::Battler --hook abilityActive?`。
23. **patch 里一定会递归**：你覆盖的 `abilityActive?` 里如果调用
    `hasActiveAbility?` / `pbCheckGlobalAbility`，它们又会走回来。
    必须加个全局守卫（`$ce_xxx_guard`）在「查别人」的那一段前后开关，
    并在守卫为真时直接放行。
24. patch 里拿「别人」的原始能力 id 用 `b.ability_id`（Symbol），
    不要用 `b.ability`（v20+ 返回 `GameData::Ability` 对象）。
    还要检查 `!b.effects[PBEffects::GastroAcid]` —— 被胃酸压制的不算。

## 插件加载在我们之后（最坑的一条）

29. **`PluginManager.runPlugins` 在 Main 里、在所有普通脚本之后才执行。**
    我们写进 `[ce] custom effects` 的代码**先**跑，插件后跑 ——
    插件里只要 `def abilityActive?`，我们的覆盖就整个失效。
    ★ 实测：《宝可梦传说：登神》的 `Generation 9 Pack` 重写了
    `Battle::Battler#abilityActive?`，导致「对手特性无效化」完全没效果，
    而表面上补丁明明装上了。
30. 所以 **patch 一律用 `--defer`（默认 auto）**：它先装一个
    `ce_plugin_hook` 延迟安装器（套住 `PluginManager.runPlugins`），
    把真正的 `class_eval` 推迟到插件加载完之后再执行。
31. `install --kind patch` 会顺带报 `plugin_overrides`：列出哪些插件里也定义了
    同一个方法。看到非空就必须延迟。

## 时机问题

25. **我们的脚本跑在 `Game.initialize` 之前。** 这个时机
    `GameData::Ability.get(:X)` 会报 `Unknown ID`（数据还没读），
    不是「数据没编译成功」。要读数据就显式 `GameData.load_all`。
26. 同理，脚本里不要做「依赖玩家/存档/地图」的事，只做
    「注册处理器 / 定义类 / 覆盖方法」。

## 同人游戏会改名字

27. 参数名不是官方那套：实测《宝可梦传说：登神》里
    `DamageCalcFromUser` 的第 6 个参数叫 `power`（官方 `baseDmg`），
    `mults` 的键也是 `:power_multiplier`（官方 `:base_damage_multiplier`）。
    **永远以 `hooks` 现读为准**，别凭官方文档写死。
28. `def self.xxx` 的方法要用限定名找（`GameData.load_all`），
    `func --name load_all --script GameData` 能取到源码。

## 改官方已有特性 / 道具的行为

`HandlerHash#add` 是 `@hash[id] = proc`（**覆盖**，不是追加），所以
**用同一个 ID 再 add 一次就能顶掉官方实现**：

```bash
$CE install <游戏> --kind ability --id STURDY --hook AbilityOnSwitchIn ...
```

我们的脚本排在 `011_Battle` 之后、Main 之前，注册时机天然靠后 → 覆盖成立。
但要清楚：**同一 ID 的官方逻辑整个不跑了**（不是「叠加」），
原逻辑想保留就把它抄进新 proc 里。

`copy(:A, :B)` 只在目标为空时才复制，别指望用它覆盖。
