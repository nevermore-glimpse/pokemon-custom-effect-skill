<div align="center">

# 宝可梦同人工具 · 自定义效果（Skill）

一个装在 AI 编程助手里的**技能（Skill）**：你用自然语言说「给游戏加个登场降特攻的特性」，agent 就会自动认引擎、读钩子、生成可回滚的 Ruby 效果代码并写进你的 Pokémon Essentials 同人游戏。覆盖引擎世代 v16 ~ v21.1。

![type](https://img.shields.io/badge/type-Skill-purple)
![python](https://img.shields.io/badge/python-3.8%2B-blue)
![dependencies](https://img.shields.io/badge/dependencies-0-lightgrey)
![engines](https://img.shields.io/badge/engines-v16~v21.1-orange)
![license](https://img.shields.io/badge/license-MIT-green)

</div>

## 这是什么

这是安装在**AI 编程助手（agent harness）里的技能**。它把一套「识别引擎 → 识别钩子 → 读参数 → 生成 → 校验 → 回归」的能力打包好，由 agent 在对话中替你驱动。

- **你**：在 agent 里用大白话提需求，比如「给 XYZ 特性加一个登场降低对手特攻的效果」「让这个道具命中后追加灼伤」。agent 加载本技能后，会自动跑完整条链路。
- **agent 工具（workbuddy / deepseek harness / qoder / zcode 等）**：加载本技能后，获得给宝可梦同人游戏改战斗逻辑的能力。
- **底层引擎**：技能通过同目录的 `ce_cli.py`读写游戏脚本；所有判断都基于**本游戏的脚本**。

## 支持的 Agent 工具

本技能是「即插即用」的目录结构（一个 `SKILL.md` 入口 + 同目录的 Python 脚本与数据），不绑定特定加载器。把整个仓库目录放进对应 harness 的自定义技能目录即可。

| Agent 工具             | 技能目录（示例）                                                                                                | 备注                    |
|----------------------|---------------------------------------------------------------------------------------------------------|-----------------------|
| **WorkBuddy**        | 用户级 `~/.workbuddy/skills/pokemon-custom-effect/`<br>项目级 `<项目>/.workbuddy/skills/pokemon-custom-effect/` | 用户级对所有项目生效；项目级仅当前仓库生效 |
| **DeepSeek Harness** | 安装skills插件，用skills插件安装技能                                                                                | 目录名与加载方式以插件为准         |
| **Qoder**            | 对应 harness 的 skills / 自定义技能目录                                                                           | 同上                    |
| **ZCode**            | 对应 harness 的 skills / 自定义技能目录                                                                           | 同上                    |
| **其它agent工具**        | 对应 harness 的 skills / 自定义技能目录                                                                           | 同上                    |

> 各 harness 的目录约定与启用方式可能不同，安装前请查阅对应工具的官方文档。本技能只依赖 `SKILL.md` 入口与同目录文件，不依赖任何特定加载器。

## 安装

1. 克隆（或下载）本仓库：
   ```bash
   git clone https://github.com/nevermore-glimpse/pokemon-custom-effect-skill.git
   ```
2. 把整个 `pokemon-custom-effect/` 目录，按上表放进你所用 harness 的技能目录（以 WorkBuddy 用户级为例）：
   ```bash
   cp -r pokemon-custom-effect-skill ~/.workbuddy/skills/pokemon-custom-effect-skill
   ```
3. 重启 / 刷新 agent，确认技能已被加载（在对话里说一句「帮我给宝可梦游戏加个特性效果」应触发本技能）。


## 怎么用

装好后，直接在 agent 对话里用自然语言提需求即可，以下是典型触发方式：

| 你想做的事 | 对 agent 说的话（示例）                                 |
|---|-------------------------------------------------|
| 加特性效果 | 「给游戏目录 D:/MyGame 里的 MYABILITY 加一个登场降低对手特攻的特性」   |
| 加道具效果 | 「让道具 MYITEM 命中后追加灼伤」                            |
| 加招式效果 | 「新招式用一个登场时降攻击的效果，FunctionCode 你帮我挑」             |
| 改战斗判定 | 「让对手的特性失效，需要改 `Battle::Battler#abilityActive?`」 |
| 问该写哪 | 「这个效果该写在哪个钩子里？」                                 |

agent 会自行执行：识别引擎（`scan`）、识别钩子（`hooks`）、确认 ID（`check`）、生成并落盘（`install`）、收尾校验（`verify`）。

### 底层命令（调试 / 高级用法）

如果你要自己排查或写自动化，技能底层就是 `ce_cli.py`，所有命令输出 UTF-8 JSON：

```bash
CE="python <技能目录>/ce_cli.py"

$CE doctor <游戏目录>            # 环境 + 游戏一起自查
$CE scan   <游戏目录> --deep     # 版本 / 引擎世代 / 脚本容器 / PBS / 注册表
$CE hooks  <游戏目录> --kind ability --want "登场时降低对手特攻"   # 推荐钩子+参数
$CE check  <游戏目录> --kind ability --id MYABILITY              # ID 是否存在于 PBS/.dat
$CE install <游戏目录> --kind ability --id MYABILITY --hook OnSwitchIn \
    --slug my_ability --body /tmp/body.rb --desc "登场时降低对手特攻"
$CE list   <游戏目录>            # 现在装了哪些段
$CE remove <游戏目录> --slug my_ability
$CE verify <游戏目录>            # 整份脚本结构检查
```

完整命令清单见 [`ce_cli.py`](ce_cli.py) 内 `--help`；`render` 可只生成代码不落盘，`install` 默认写盘（`--dry` 预览、`--force` 强写）。

## 工作原理


- **识别引擎**：`scan` 读版本号与脚本容器；读不出时按函数指纹判定 `family`（16/17/18/19/20/21）。
- **识别钩子**：`hooks` 从游戏真实注册表列出可用钩子与参数，或按中文需求推荐（如「登场时降特攻」→ `OnSwitchIn`）。
- **生成**：`render` / `install` 用模板渲染外壳，你只写方法体；产物包进 `[ce] custom effects` 脚本、插在 Main 之前，每段用 `# >>> ce:<slug>` / `# <<< ce:<slug>` 标记。
- **校验与回滚**：`install` 自动备份并回读校验；`remove` 只删一段；`verify` 做结构检查（`end` 配对、括号、标记、注册表存在性，可选 `ruby -c`）。

## 引擎世代速查

| family | 版本 | 特性 / 道具效果 | 招式效果类 | 数据 API |
|---|---|---|---|---|
| 16 / 17 | 16~17.x | ❌ 无处理器，alias 覆盖 `PokeBattle_Battler#…` | `PokeBattle_Move_XXX` + `pbEffect(attacker, opponent, …)` | `PBAbilities::` / `PBItems::` |
| 18 / 19 | 18、19、19.1 | `BattleHandlers::XxxAbility.add` | `PokeBattle_Move_XXX` + `pbEffectGeneral(user)` | 18 用 `PBItems::`，19 用 `GameData::` |
| 20 / 21 | 20、20.1、21、21.1 | `Battle::AbilityEffects::X.add`<br>`Battle::ItemEffects::X.add` | `Battle::Move::<FunctionCode>` + `pbEffectGeneral(user)` | `GameData::` |

v18 起招式效果方法统一为 `pbEffectGeneral(user)` / `pbEffectAgainstTarget(user, target)` / `pbAdditionalEffect(user, target)`。

## 注意事项（技能内置铁律）

这些规则 agent 在生成代码时会自动遵守，了解它们有助于你审查代码：

1. **用钩子注册语句去试**：先 `hooks` 拿现成钩子名和参数名（同人游戏常把官方参数名改掉，如 `baseDmg` → `power`），猜错就是 `ArgumentError` 或静默不触发。
2. **优先挂处理器，不改引擎原函数**：v18+ 走 `BattleHandlers::X.add` / `Battle::AbilityEffects::X.add` / `Battle::ItemEffects::X.add`；v16/v17 只能 alias。
3. **只有「无钩子的全局判定」才用 patch**：必须 alias 原方法再调用，**不能把原逻辑删掉重写**；有插件的游戏自动 `--defer`（延迟到插件加载之后），`plugin_overrides` 会列出冲突插件。
4. **产物只写进一个脚本**：`[ce] custom effects`，重跑同 slug = 替换，不会堆。
5. **改前必备份、改后必回读校验**；`install` 自动完成这两步。
6. **没有数据就没有效果**：特性/道具/招式 ID 必须先存在于 `PBS/*.txt`（或 `.dat`），`check` 会告诉你缺哪条、要补什么。
7. **对玩家显示的文本一律 `_INTL("…")`**，否则翻译不了。
8. **改官方已有特性行为**：同一 ID 再注册一次是**替换**不是叠加。

## 文档

- [`reference/api_matrix.md`](reference/api_matrix.md) —— 三世代 × 三种效果的注册表与参数表（实测）
- [`reference/cookbook.md`](reference/cookbook.md) —— 常见需求的可用代码（照抄改 ID 即可）
- [`reference/pitfalls.md`](reference/pitfalls.md) —— 遇到的问题，写代码前先扫一眼

## FAQ

**Q1：装完技能，agent 说找不到 / 没触发？**
A：确认目录名与结构正确（根目录要有 `SKILL.md`，且 `ce_*.py`、`_vendor/`、`data/`、`templates/` 都在同一目录内）；重启 agent 后再试一句触发语。WorkBuddy 用户级放 `~/.workbuddy/skills/`，项目级放 `<项目>/.workbuddy/skills/`。

**Q2：agent 生成的代码不触发，或报 `ArgumentError`？**
A：多半是钩子名或参数名对不上这个游戏的真实定义。技能内部会先 `hooks` 现读，但如果你的游戏被重度魔改，建议用 `render` 先看生成代码、核对参数名。

**Q3：补丁在插件环境里失效？**
A：插件脚本在普通脚本之后加载，同名 `def` 会顶掉我们的补丁。技能检测到插件系统会默认 `--defer`，输出 `plugin_overrides` 列出冲突插件；非空就一定要延迟。

**Q4：效果毫无反应但没报错？**
A：ID 必须先在 `PBS/*.txt`（或 `.dat`）里存在，否则永远不触发。让 agent 跑 `check`，缺的 ID 会在 `hint` 里给出要补的 PBS 行。

**Q5：需要 Python 环境吗？本技能依赖什么？**
A：需要 Python 3.8+，但**零第三方依赖**（`_vendor/rmarshal.py` 已内置 Ruby Marshal 读写）。不需要 `pip install`。

## 贡献

欢迎提交 issue 与 PR。动手前建议先读 [`reference/pitfalls.md`](reference/pitfalls.md) 与 [`reference/api_matrix.md`](reference/api_matrix.md)。问题反馈请到 [GitHub Issues](https://github.com/[用户名]/pokemon-custom-effect/issues)。

## 许可证

本项目基于 [MIT License](LICENSE) 发布（Copyright © 2026 nevermore-glimpse）。可自由使用、修改、分发，须保留版权与许可声明；软件按「原样」提供，作者不对任何后果负责。

---
