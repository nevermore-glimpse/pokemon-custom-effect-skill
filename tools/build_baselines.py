# -*- coding: utf-8 -*-
"""
（开发用）从主项目重新生成 data/baselines.json.gz。

只有维护这个技能的时候才需要它 —— 普通使用者不用跑，文件已经随包分发。

    python pokemon-custom-effect/tools/build_baselines.py <主项目根>

输出结构：{"16": {脚本名: {函数: 指纹}}, "17": {...}, "21.1": {...}}
"""
import gzip
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
OUT = os.path.join(SKILL, "data", "baselines.json.gz")


def main(argv):
    root = argv[1] if len(argv) > 1 else os.path.dirname(SKILL)
    src = os.path.join(root, "scripts", "essentials_base")
    if not os.path.isdir(src):
        print("找不到 %s" % src)
        return 2
    out = {}
    for f in sorted(os.listdir(src)):
        if not f.lower().endswith(".json"):
            continue
        ver = f[:-5]
        if ver.startswith("v"):
            ver = ver[1:]
        with io.open(os.path.join(src, f), "r", encoding="utf-8") as fp:
            data = json.load(fp)
        scripts = data.get("scripts") if isinstance(data, dict) else None
        if isinstance(scripts, dict) and scripts:
            out[ver] = scripts
    if not out:
        print("一份基准都没读到")
        return 3
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = json.dumps(out, separators=(",", ":"), sort_keys=True).encode("utf-8")
    with open(OUT, "wb") as fp:
        fp.write(gzip.compress(payload, 9))
    print("写出 %s" % OUT)
    print("  版本：%s" % ", ".join(sorted(out)))
    print("  原始 %.1f KB → 压缩 %.1f KB"
          % (len(payload) / 1024.0, os.path.getsize(OUT) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
