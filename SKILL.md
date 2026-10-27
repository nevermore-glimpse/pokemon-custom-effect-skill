---
name: pokemon-custom-effect
description: 给 Pokémon Essentials 同人游戏加「自定义效果」代码 —— 特性效果、道具效果、招式效果，以及没有钩子时的方法级补丁。自动识别引擎世代（v16~v21.1）、读出游戏自己的效果注册表与参数签名、把代码写成一段可回滚的脚本插到 Main 之前。当用户说要加特性/道具/招式效果、改战斗逻辑、挂 BattleHandlers/AbilityEffects、或者问「这个效果该写在哪」时使用。
---

# 宝可梦同人工具 · 自定义效果

给游戏加一段效果代码，走完整条链：**认引擎 → 认钩子 → 读参数 → 生成 → 校验 → 落盘**。

工具不猜：钩子名、参数个数、招式类名全部从**这个游戏自己的脚本**里读出来；
引擎版本先看版本号，再用函数指纹对官方基准（9 个版本内置）。

## 环境

- **Python 3.8+，零第三方依赖**。整个 `pokemon-custom-effect/` 目录拷走就能用，
  不需要 pip install、不需要本仓库其它代码。
- 内置 `_vendor/rmarshal.py`（Ruby Marshal 读写）和 `data/baselines.json.gz`
  （9 个版本的函数指纹基准，约 800KB）。
- `python ce_cli.py doctor` 自查：Python 版本、内置依赖、能不能读目标游戏。
- 想额外看「官方引擎源码」做对照时才需要主项目（`PKMN_TOOLS_ROOT` 指过去即可），
  没有也完全不影响改效果。

## 铁律

1. **不要手写注册语句去试。** 先 `hooks` 拿现成的钩子名和参数名 ——
   v19 的登场处理器 3 个参数、v20 的 4 个；同人游戏的参数名还可能被改成
   `power` 而不是官方的 `baseDmg`。猜错就是 `ArgumentError` 或静默不触发。
2. **优先挂处理器**，别改引擎原函数。v18+ 走
   `BattleHandlers::X.add` / `Battle::AbilityEffects::X.add` /
   `Battle::ItemEffects::X.add`；v16/v17 没有处理器，只能 alias。
3. **只有「没有钩子的全局判定」才用 `--kind patch`**（例如让对手特性失效要改
   `Battle::Battler#abilityActive?`）。patch 必须 alias 原方法再调用它，
   **不能把原逻辑删掉重写**。
   ★ **有插件的游戏必须 `--defer`（默认 auto）**：插件脚本在普通脚本之后才加载，
   插件里同名 `def` 会把我们的覆盖顶掉。`install` 的 `plugin_overrides`
   字段会列出「哪些插件也定义了这个方法」，非空就一定要延迟。
4. **产物只写进一个脚本**：`[ce] custom effects`，插在 Main 之前，每段用
   `# >>> ce:<slug>` / `# <<< ce:<slug>` 包着。重跑同 slug = 替换，不会堆。
5. **改之前一定有备份**，改之后一定回读校验。`install` 自动做这两件事。
6. **没有数据就没有效果。** 特性/道具/招式的 ID 必须先存在于
   `PBS/abilities.txt` / `items.txt` / `moves.txt`（或 `.dat`），
   否则代码挂上去也永远不触发。`check` 会告诉你缺哪条、要补什么。
7. **对玩家显示的文本一律 `_INTL("…")`**，否则翻译不了。
8. **想改官方已有特性的行为**：用同一个 ID 再注册一次
   （`HandlerHash#add` 是覆盖写）。注意那是**替换**不是叠加。

## 工作流

```bash
CE="python <技能目录>/ce_cli.py"
```

### 1. 认引擎

```bash
$CE doctor <游戏目录>          # 环境 + 游戏一起看
$CE scan   <游戏目录> --deep   # family（16/17/18/19/20/21）、脚本容器、PBS、注册表
```

版本号读不出来时会按指纹兜底，`baseline_why` 里写得明明白白。

### 2. 认钩子

```bash
$CE hooks <游戏目录> --kind ability --want "登场时降低对手攻击"
# → best.hook = OnSwitchIn, args = ability,battler,battle,switch_in

$CE hooks <游戏目录> --kind ability     # 列出全部可用钩子
$CE hooks <游戏目录> --kind move --want "命中后追加灼伤"
```

`--kind`：`ability` / `item` / `move`（招式返回「重写哪个方法」）。

### 3. 确认 ID 存在

```bash
$CE check <游戏目录> --kind ability --id MYABILITY
# exists=false 时 hint 里直接给 PBS 该追加的那几行
```

新招式还要看 `function_code`：`FunctionCode` 必须写成它给的那个值。

### 4. 写代码（写到临时文件）

只写**方法体 / proc 体**，外壳由模板生成：

```ruby
battle.pbShowAbilitySplash(battler)
battle.allOtherSideBattlers(battler.index).each do |b|
  next if !b.near?(battler)
  next if !b.pbCanLowerStatStage?(:ATTACK, battler)
  b.pbLowerStatStage(:ATTACK, 1, battler)
end
battle.pbHideAbilitySplash(battler)
```

参数名用 `hooks` 返回的那几个。招式用 `user` / `target`；
v16/v17 的 `pbEffect` 用 `attacker` / `opponent`。

### 5. 生成 + 校验 + 落盘

```bash
$CE install <游戏目录> \
    --kind ability --id MYABILITY --hook OnSwitchIn \
    --slug my_ability --body /tmp/body.rb --desc "登场时降低对手攻击"
```

没有钩子、必须改判定的：

```bash
$CE install <游戏目录> --kind patch --parent Battle::Battler \
    --hook "abilityActive?" --slug my_patch --body /tmp/patch.rb
# 有插件会自动加 --defer（延迟到 PluginManager.runPlugins 之后）；
# 输出里的 plugin_overrides 会告诉你哪些插件也定义了这个方法
```

先 `--dry` 看 `applied.targets` 是不是想写的位置。校验不过不写，`--force` 才硬写。

### 6. 收尾

```bash
$CE list   <游戏目录>             # 现在装了哪些段
$CE remove <游戏目录> --slug xxx  # 只删这一段（备份照旧）
$CE verify <游戏目录>             # 整份脚本结构检查
```

## 引擎世代速查

| family | 版本 | 特性 / 道具效果 | 招式效果类 | 数据 API |
|---|---|---|---|---|
| 16 / 17 | 16~17.x | ❌ 无处理器，alias 覆盖 `PokeBattle_Battler#…` | `PokeBattle_Move_XXX` + `pbEffect(attacker, opponent, …)` | `PBAbilities::` / `PBItems::` |
| 18 / 19 | 18、19、19.1 | `BattleHandlers::XxxAbility.add` | `PokeBattle_Move_XXX` + `pbEffectGeneral(user)` | 18 用 `PBItems::`，19 用 `GameData::` |
| 20 / 21 | 20、20.1、21、21.1 | `Battle::AbilityEffects::X.add`<br>`Battle::ItemEffects::X.add` | `Battle::Move::<FunctionCode>` + `pbEffectGeneral(user)` | `GameData::` |

v18 起招式效果方法统一为 `pbEffectGeneral(user)` /
`pbEffectAgainstTarget(user, target)` / `pbAdditionalEffect(user, target)`。

## 常用工具

```bash
$CE func  <游戏> --script Battle_Battler --name "abilityActive?" --official  # 源码 + 与官方基准比对
$CE state <游戏> --script Battle_AbilityEffects                            # 这脚本被作者改过几个函数
$CE class <游戏> --name StatUpMove                                         # 取某个招式效果类
$CE grep  <游戏> --pattern "pbShowAbilitySplash"                           # 全脚本搜索
```

- `func.status = changed` → 作者动过这个函数，patch/alias 前先读它真实源码。
- 想抄官方写法，`class` / `func` 取到的是**这个游戏对应版本**的代码，比抄网上别的版本靠谱。

## 文档

- `reference/api_matrix.md` —— 三世代 × 三种效果的注册表与参数表（实测）
- `reference/cookbook.md` —— 常见需求的可用代码（照抄改 ID 即可）
- `reference/pitfalls.md` —— 踩过的坑，写代码前先扫一眼

## 目录

```
pokemon-custom-effect/
├── ce_cli.py      命令行（doctor / scan / hooks / func / class / grep /
│                  check / render / install / remove / list / verify）
├── ce_core.py     自包含核心：rxdata 读写、脚本枚举、版本识别、函数指纹、基准、PBS/.dat
├── ce_game.py     版本 → 世代；引擎改动比对；数据 ID
├── ce_locate.py   读游戏里的注册表、参数签名、函数/类源码
├── ce_emit.py     模板渲染 + 钩子推荐 + PBS 提示
├── ce_apply.py    落盘（rxdata / .rb / 两处都写）+ 备份 + 幂等 + 回读
├── ce_verify.py   结构校验（end 配对、括号、标记、注册表存在性、可选 ruby -c）
├── ce_boot.py     环境引导（找主项目是可选的）
├── _vendor/       内置 rmarshal.py（Ruby Marshal 读写，纯标准库）
├── data/          baselines.json.gz（9 个版本的函数指纹基准）
├── templates/     .rb 模板（处理器 / 招式类 / 老引擎 alias / 方法补丁）
├── reference/     速查表
├── tools/         维护脚本（重新生成基准包）
└── tests/         自测
```
