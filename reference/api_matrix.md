# 三世代 × 三种效果的落点速查

数据来源：官方 Essentials 16 / 18 / 19.1 / 20.1 / 21.1 源码实测（不是凭记忆写的）。
**参数表一定要用 `hooks` 现读** —— 下面只是抄下来方便你快速判断，同人游戏可能改过。

## 一、特性 / 道具效果

### family 20 / 21（v20、20.1、21、21.1）

注册表在 `Battle::AbilityEffects`（脚本 `Battle_AbilityEffects`）与
`Battle::ItemEffects`（`Battle_ItemEffects`），声明形如：

```ruby
module Battle::AbilityEffects
  SpeedCalc = AbilityHandlerHash.new
  OnSwitchIn = AbilityHandlerHash.new
```

| 钩子 | 参数（v20.1 实测） | 干什么 |
|---|---|---|
| `OnSwitchIn` | `ability, battler, battle, switch_in` | 登场 |
| `OnSwitchOut` | `ability, battler, endOfBattle` | 下场 |
| `SpeedCalc` | `ability, battler, mult` | 速度倍率（改返回值） |
| `WeightCalc` | `ability, battler, w` | 体重倍率 |
| `DamageCalcFromUser` | `ability, user, target, move, mults, baseDmg, type` | 自己打出去的伤害倍率 |
| `DamageCalcFromTarget` | `ability, user, target, move, mults, baseDmg, type` | 自己挨打的伤害倍率 |
| `AccuracyCalcFromUser` | `ability, mods, user, target, move, type` | 命中率修正 |
| `CriticalCalcFromUser` | `ability, user, target, c` | 会心等级 |
| `OnBeingHit` | `ability, user, target, move, battle` | 被打中（含自己） |
| `OnDealingHit` | `ability, user, target, move, battle` | 打中别人 |
| `MoveImmunity` | `ability, user, target, move, type, battle, show_message` | 免疫某类招式 |
| `MoveBlocking` | `ability, bearer, user, targets, move, battle` | 挡下指向队友的招式 |
| `PriorityChange` | `ability, battler, move, pri` | 优先度修正 |
| `PriorityBracketChange` | `ability, battler, battle` | 同优先度内排序 |
| `StatusImmunity` | `ability, battler, status` | 免疫某种异常 |
| `OnStatusInflicted` | `ability, battler, user, status` | 被挂上异常时 |
| `StatusCure` | `ability, battler` | 自动治愈 |
| `StatLossImmunity` | `ability, battler, stat, battle, showMessages` | 某项能力不会被降 |
| `OnStatLoss` | `ability, battler, stat, user` | 被降能力时 |
| `EndOfRoundEffect` | `ability, battler, battle` | 回合结束 |
| `EndOfRoundHealing` | `ability, battler, battle` | 回合结束回复 |
| `OnHPDroppedBelowHalf` | `ability, battler, move_user, battle` | HP 掉到一半以下 |
| `ChangeOnBattlerFainting` | `ability, battler, fainted, battle` | 有人倒下 |
| `ModifyMoveBaseType` | `ability, user, move, type` | 改招式属性 |
| `OnEndOfUsingMove` | `ability, user, targets, move, battle` | 用完招式 |
| `AfterMoveUseFromTarget` | `ability, target, user, move, switched_battlers, battle` | 被招式打完之后 |

道具同名钩子放在 `Battle::ItemEffects`，参数把第一个 `ability` 换成 `item`。
注意个别道具钩子参数**少一个**（`OnSwitchIn` 是 `item, battler, battle`，
`OnBeingHit` 是 `item, user, target, move, battle`）。

### family 18 / 19（v18、19、19.1）

注册表在 `BattleHandlers`（脚本 `BattleHandlers`），名字带后缀：

| v20 名字 | v18 / v19 名字 |
|---|---|
| `OnSwitchIn` | `AbilityOnSwitchIn` / `ItemOnSwitchIn` |
| `OnSwitchOut` | `AbilityOnSwitchOut` |
| `SpeedCalc` | `SpeedCalcAbility` / `SpeedCalcItem` |
| `DamageCalcFromUser` | `DamageCalcUserAbility` / `DamageCalcUserItem` |
| `DamageCalcFromTarget` | `DamageCalcTargetAbility` / `DamageCalcTargetItem` |
| `OnBeingHit` | `TargetAbilityOnHit` / `TargetItemOnHit` |
| `OnDealingHit` | `UserAbilityOnHit` |
| `MoveImmunity` | `MoveImmunityTargetAbility` |
| `OnStatusInflicted` | `AbilityOnStatusInflicted` |
| `PriorityChange` | `PriorityChangeAbility` / `PriorityChangeItem` |

★ **v19 的 `AbilityOnSwitchIn` 只有 3 个参数** `ability, battler, battle`
（v20 是 4 个，多一个 `switch_in`）。照抄 v20 代码到 v19 会 `ArgumentError`。

### family 16 / 17

没有处理器表。只能重开 `PokeBattle_Battler` / `PokeBattle_Battle` / `PokeBattle_Move`，
`alias` 原方法后加分支：

```ruby
class PokeBattle_Battler
  unless method_defined?(:__ce_orig_pbSpeed)
    alias __ce_orig_pbSpeed pbSpeed
  end

  def pbSpeed(*args)
    ret = __ce_orig_pbSpeed(*args)
    return ret * 2 if hasWorkingAbility?(:MYABILITY) && @battle.pbWeather == :Rain
    ret
  end
end
```

可用的锚点（v17 实测存在）：`pbSpeed`、`pbAbilitiesOnSwitchIn`、
`pbEffectsOnDealingDamage`、`pbAbilityCureCheck`。
`hasWorkingAbility?(:SYMBOL)` 在这两代可用（内部走 `isConst?`）。
先跑 `func --script PokeBattle_Battler --name pbSpeed` 确认作者没改过它。

## 二、招式效果

| family | 类名 | 要重写的方法 |
|---|---|---|
| 20 / 21 | `class Battle::Move::<FunctionCode> < Battle::Move` | `pbEffectGeneral(user)`<br>`pbEffectAgainstTarget(user, target)`<br>`pbAdditionalEffect(user, target)` |
| 18 / 19 | `class PokeBattle_Move_<FunctionCode> < PokeBattle_Move` | 同上（方法名一样） |
| 16 / 17 | `class PokeBattle_Move_<FunctionCode> < PokeBattle_Move` | `pbEffect(attacker, opponent, hitnum = 0, alltargets = nil, showanimation = true)` |

FunctionCode 与类名的对应关系（官方代码里就这么查的）：

- v20+：`Battle::Move.from_pokemon_move` → 数字开头的码拼成
  `Battle::Move::Effect<码>`，非数字开头直接 `Battle::Move::<码>`
- v19：`sprintf("PokeBattle_Move_%s", code)`，码是 3 位（`000`~`1FF` 官方占用）
- v16/17/18：同 v19

→ 新招式：`FunctionCode = PokeCE`（v20+）或 `FunctionCode = 1F0`（v18/v19，
`ce_cli` 会自动挑一个没被占用的）。

## 三、背包 / 场上道具（所有版本都有）

```ruby
ItemHandlers::UseOnPokemon.add(:MYITEM, proc { |item, qty, pkmn, scene| ... })
```

各版本参数不一样，**必须现读**：

| 版本 | `UseOnPokemon` 参数 |
|---|---|
| 16 | `item, pokemon, scene` |
| 18 / 19 | `item, pkmn, scene` |
| 20 / 21 | `item, qty, pkmn, scene` |

其它常用：`UseInField`（`item`）、`UseFromBag`（`item`）、`UseText`（`item`）、
`CanUseInBattle`（v20：`item, pokemon, battler, move, firstAction, battle, scene, showMessages`）、
`UseInBattle`（`item, battler, battle`）。
