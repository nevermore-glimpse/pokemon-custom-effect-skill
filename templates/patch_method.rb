# ---- {{SLUG}} ----
# {{DESC}}
# ★ 覆盖已有方法：先 alias 原方法，再自己实现，原逻辑还能通过 {{ALIAS}} 调用。
#   官方没给钩子、又必须改判定逻辑时（例如「全场特性无效化」）才用这一种。
class {{CLASS}}
  unless method_defined?(:{{ALIAS}})
    alias {{ALIAS}} {{METHOD}}
  end

  def {{METHOD}}(*args)
{{BODY}}
  end
end
