# -*- coding: utf-8 -*-
"""
环境引导：让这个目录**单独拿走也能跑**。

三件事：
  1. 把技能自己的目录和 `_vendor/` 放进 sys.path（内置的 rmarshal 才能 import）
  2. 探测 Python 版本（3.8+），太老给一句人话
  3. 可选地接上主项目「宝可梦同人工具」—— 只有为了看**官方引擎源码**
     （`ce_cli class` / `func --official`）才需要它；没有也完全不影响主流程

找主项目的顺序：
    环境变量 PKMN_TOOLS_ROOT  →  上一级目录里有 game_scripts.py  →  没有

★ 不要在这里 import 主项目模块：没有主项目时 import 会直接炸。
"""
import os
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(SKILL_DIR, "_vendor")
PROJECT_ROOT = os.path.dirname(SKILL_DIR)

_REQUIRED = ("game_scripts", "essentials_base", "engine_src")

_ready = False
_host = None


def bootstrap():
    """准备 sys.path，返回技能目录。"""
    global _ready
    if _ready:
        return SKILL_DIR
    if sys.version_info < (3, 8):
        raise RuntimeError(
            "需要 Python 3.8 或更高版本（现在是 %s）" % sys.version.split()[0])
    for d in (VENDOR_DIR, SKILL_DIR):
        if d not in sys.path:
            sys.path.insert(0, d)
    _ready = True
    return SKILL_DIR


def host_project():
    """
    主项目根目录（有 game_scripts.py 的那一层），没有返回 None。

    ★ 只用于「读官方引擎源码做对照」。用户机器上没有主项目时，
      `func` / `class` 仍然能读**游戏自己的**代码，只是少一份官方对照。
    """
    global _host
    if _host is not None:
        return _host or None
    cands = [os.environ.get("PKMN_TOOLS_ROOT", ""), PROJECT_ROOT]
    for root in cands:
        if not root:
            continue
        if all(os.path.isfile(os.path.join(root, m + ".py")) for m in _REQUIRED):
            import logging
            logging.disable(logging.INFO)      # 主项目的 logger 会往 stdout 喷
            _host = root
            return root
    _host = ""
    return None


def info():
    """环境自检 → dict（`ce_cli doctor` 用）。"""
    import platform
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "skill_dir": SKILL_DIR,
        "vendor": os.path.isdir(VENDOR_DIR),
        "host_project": host_project() or "",
        "encoding": sys.getdefaultencoding(),
        "fs_encoding": sys.getfilesystemencoding(),
    }
