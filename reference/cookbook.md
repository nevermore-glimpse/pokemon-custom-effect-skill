# 现成代码片段（照抄改 ID 即可）

全部基于官方 20.1 / 19.1 实测写法。**参数名以 `hooks` 现读的为准**，
下面的片段假设你已经用 `--hook` 选中了同名钩子。

三条通用规矩：
- 想「提前结束这段逻辑」用 `next`（proc 里）或 `return`（def 里），别用 `break`。
- 对玩家显示的文字包 `_INTL("…")`。
- 演出成对：`pbShowAbilitySplash` … `pbHideAbilitySplash`。

---

## 特性

### 1. 登场时降低对手攻击（v20 / v21）

钩子 `OnSwitchIn`，参数 `ability, battler, battle, switch_in`：

```ruby
battle.pbShowAbilitySplash(battler)
battle.allOtherSideBattlers(battler.index).each do |b|
  next if !b.near?(battler)
  next if !b.pbCanLowerStatStage?(:ATTACK, battler)
  b.pbLowerStatStage(:ATTACK, 1, battler)
end
battle.pbHideAbilitySplash(battler)
```

v18 / v19 用 `AbilityOnSwitchIn`，参数少一个（`ability, battler, battle`），
`PokeBattle_SceneConstants::USE_ABILITY_SPLASH` 代替 `Battle::Scene::USE_ABILITY_SPLASH`。

### 2. 天气下速度翻倍

钩子 `SpeedCalc`（v18/19：`SpeedCalcAbility`），参数 `ability, battler, mult`：

```ruby
next mult * 2 if [:Rain, :HeavyRain].include?(battler.effectiveWeather)
```

v19 及以前用 `battler.battle.pbWeather`。

### 3. 某属性招式增伤 30%

钩子 `DamageCalcFromUser`（v18/19：`DamageCalcUserAbility`），
参数 `ability, user, target, move, mults, baseDmg, type`：

```ruby
mults[:base_damage_multiplier] *= 1.3 if type == :FIRE
```

`mults` 是**哈希**（`[:base_damage_multiplier]` / `[:attack_multiplier]` /
`[:final_damage_multiplier]`），v19 起就是这样，不是数组。

### 4. 被打中时给对手上灼伤（30%）

钩子 `OnBeingHit`（v18/19：`TargetAbilityOnHit`），
参数 `ability, user, target, move, battle`（注意 `user` 是攻击方、`target` 是特性持有者）：

```ruby
next if !move.contactMove?
next if battle.pbRandom(100) >= 30
next if !user.pbCanBurn?(target, false)
battle.pbShowAbilitySplash(target)
user.pbBurn(target)
battle.pbHideAbilitySplash(target)
```

### 5. 回合结束回 1/16 血

钩子 `EndOfRoundEffect`，参数 `ability, battler, battle`：

```ruby
return if !battler.canHeal?
battle.pbShowAbilitySplash(battler)
battler.pbRecoverHP(battler.totalhp / 16)
battle.pbDisplay(_INTL("{1}'s {2} restored its HP a little!", battler.pbThis, battler.abilityName))
battle.pbHideAbilitySplash(battler)
```

### 6. v16 / v17（没有处理器表，alias 覆盖）

用 `--kind ability --hook pbSpeed`，生成的外壳已经包含 alias，正文只写：

```ruby
return ret * 2 if hasWorkingAbility?(:MYABILITY) && @battle.pbWeather == :Rain
```

先跑 `func --script PokeBattle_Battler --name pbSpeed`：
`status` 不是 `same` 就别 alias（作者改过签名，容易炸）。

---

## 道具

### 7. 背包里用：回 50 血

钩子 `UseOnPokemon`（`ItemHandlers`），参数按版本不同
（v20：`item, qty, pkmn, scene`；v18/19：`item, pkmn, scene`；v16：`item, pokemon, scene`）：

```ruby
if pkmn.hp >= pkmn.totalhp
  scene.pbDisplay(_INTL("It won't have any effect."))
  next false
end
pkmn.pbRecoverHP(50)
scene.pbRefresh
scene.pbDisplay(_INTL("{1}'s HP was restored.", pkmn.name))
next true
```

### 8. 战斗内持有：速度 ×1.5

钩子 `Battle::ItemEffects::SpeedCalc`（v18/19：`BattleHandlers::SpeedCalcItem`），
参数 `item, battler, mult`：

```ruby
next mult * 1.5 if battler.pbHasType?(:ELECTRIC)
```

### 9. 战斗内持有：每回合回血

钩子 `EndOfRoundHealing`，参数 `item, battler, battle`：

```ruby
next if !battler.canHeal?
battler.pbRecoverHP(battler.totalhp / 16)
battle.pbDisplay(_INTL("{1} restored a little HP using its {2}!",
                       battler.pbThis, battler.itemName))
```

---

## 招式

### 10. 命中后追加降防御（v20 / v21）

`--kind move --hook pbAdditionalEffect`，类名 `Battle::Move::<FunctionCode>`：

```ruby
return if !target.pbCanLowerStatStage?(:DEFENSE, user)
target.pbLowerStatStage(:DEFENSE, 1, user)
```

再把这招的 `FunctionCode` 改成 `ce_cli` 给你的那个码（`PBS/moves.txt`）。
`pbAdditionalEffect` 受招式 `EffectChance` 控制，别忘了填。

### 11. 自身 HP 越低威力越高（v20 / v21）

`--hook pbEffectGeneral`：

```ruby
case user.hp * 3 / user.totalhp
when 0 then @power = 150
when 1 then @power = 90
else        @power = 60
end
```

### 12. v16 / v17 的招式

只有一个 `pbEffect(attacker, opponent, hitnum = 0, alltargets = nil, showanimation = true)`，
正文里用 `attacker` / `opponent`，收尾一般要 `return 0` 之类的返回值 ——
抄同类官方效果（`class --name PokeBattle_Move_0A0`）最稳。

---

## 拿不准的时候

```bash
$CE class <游戏> --name <同类官方效果类名>   # 官方怎么写的（这个版本）
$CE func  <游戏> --script Battle_AbilityEffects --name pbShowAbilitySplash
$CE grep  <游戏> --pattern "pbCanLowerStatStage"
```

比照抄别的版本的教程靠谱得多 —— v19 → v20 改了一大堆方法名和常量名。

---

## 完整案例：交错之魂（对手特性无效 + 电/火招式 +20%）

实测环境：《宝可梦传说：登神 v0.1.1.3》，Essentials 21.1，
`Battle::AbilityEffects` + 407 条脚本 + PBS 章节式。三步走完，游戏正常启动、
数据正常编译。

### ① 加数据（一次性）

`PBS/abilities.txt` 末尾按同样的格式追加（这份文件是 CRLF，别用 LF 混进去）：

```
#-------------------------------
[SOULOFTHECROSSING]
Name = 交错之魂
Description = 使对手的特性无效化，并提高电属性和火属性招式的威力。
```

改完不用手动编译 —— Essentials 启动时 `Compiler.main` 会比对 PBS 与 `.dat`
的 mtime，文本更新了就自动重编译（这份游戏编译一次约 1 分钟）。

### ② 增伤：走处理器

```bash
$CE install <游戏> --kind ability --id SOULOFTHECROSSING \
    --hook DamageCalcFromUser --slug soul_boost --body boost.rb
```

```ruby
mults[:power_multiplier] *= 1.2 if [:ELECTRIC, :FIRE].include?(type)
```

★ 登神把官方的 `baseDmg` 改名成了 `power`，`mults` 的键也从
`[:base_damage_multiplier]` 改成了 `[:power_multiplier]` —— 这些是
`hooks` / 官方样例现读出来的，照抄网上教程会写错键名、加成静默失效。

### ③ 特性无效化：没有钩子，只能 patch（**必须延迟**）

```bash
$CE install <游戏> --kind patch --parent Battle::Battler \
    --hook "abilityActive?" --slug soul_suppress --body suppress.rb
```

```ruby
ret = __ce_orig_abilityActive(*args)
return ret if !ret
return ret if $pkmn_ce_soul_guard                    # 防递归
return ret if fainted?
return ret if @ability_id == :SOULOFTHECROSSING      # 自己不被同类压制

$pkmn_ce_soul_guard = true
begin
  holder = @battle && @battle.allOtherSideBattlers(@index).find { |b|
    b.ability_id == :SOULOFTHECROSSING && !b.effects[PBEffects::GastroAcid]
  }
  return false if holder
ensure
  $pkmn_ce_soul_guard = false
end
ret
```

这条游戏装了 `Generation 9 Pack`，它把 `abilityActive?` 整个重写了，而插件在
普通脚本**之后**才 eval —— 不延迟就等于白打。`install` 会报
`plugin_overrides: ["Generation 9 Pack / [001] Battle/[002] Battle_Battler.rb"]`，
看到它就说明必须延迟（`--defer auto` 已经默认处理）。

为什么是 `abilityActive?`：引擎所有特性触发都先过它
（`hasActiveAbility?` 也只是它的包装），改这一处等于全场生效，
不用挨个处理器去堵。守卫变量是必须的 —— 里面的
`allOtherSideBattlers` 一旦间接问到 `hasActiveAbility?` 就会绕回来。

### ④ 发动提示（像威吓那样的演出）

`--kind ability --hook OnSwitchIn`，正文只写演出：

```ruby
next if !switch_in
battle.pbShowAbilitySplash(battler)
battle.pbDisplay(_INTL("{1} 的{2}发动了！对手的特性被无效化！",
                       battler.pbThis, battler.abilityName))
battle.pbHideAbilitySplash(battler)
```

`pbShowAbilitySplash` 负责那条特性名横幅（受 `Battle::Scene::USE_ABILITY_SPLASH`
控制），`pbDisplay` 负责正文，`pbHideAbilitySplash` 必须配对，
否则特性名会一直挂在画面上。

### 验证

- `ce_cli verify` 结构检查（end/括号/标记）。
- 启动一次游戏：能进读档界面、无 `errorlog.txt` = 数据编译和脚本加载都没炸。
- `Data/abilities.dat` 里能搜到 `:SOULOFTHECROSSING` + 中文名 = 数据链路通。
