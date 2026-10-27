# ---- {{SLUG}} ----
# {{DESC}}
# ★ 这个游戏装了插件，插件脚本在**普通脚本之后**才 eval —— 直接在这里定义会被插件覆盖。
#   所以延迟到 PluginManager.runPlugins 返回之后再打补丁。
PkmnCE.after_plugins do
  {{CLASS}}.class_eval do
    unless method_defined?(:{{ALIAS}})
      alias_method :{{ALIAS}}, :{{METHOD}}
    end

    def {{METHOD}}(*args)
{{BODY}}
    end
  end
end
