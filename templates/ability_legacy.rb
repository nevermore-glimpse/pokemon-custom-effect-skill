# ---- {{SLUG}} ----
# {{DESC}}
# ★ v16 / v17 没有处理器表，只能覆盖 {{CLASS}} 里的方法。
# ★ 只加「新分支」，别删原逻辑：原方法照常调用，新特性在返回值上再改一道。
# ★ 想在方法里提前返回就直接 `return`（这是 def 不是 proc）。
class {{CLASS}}
  unless method_defined?(:{{ALIAS}})
    alias {{ALIAS}} {{ANCHOR}}
  end

  def {{ANCHOR}}(*args)
    ret = {{ALIAS}}(*args)
{{BODY}}
    ret
  end
end
