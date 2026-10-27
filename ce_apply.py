# -*- coding: utf-8 -*-
"""
写入：把生成好的效果代码落进游戏，可重复执行、可撤销。

落盘位置固定是**一个**脚本（不是每个效果一个文件）：

    标题 / 文件名：[ce] custom effects / ce_custom_effects.rb
    内容：每段代码用
              # >>> ce:<slug>
              …代码…
              # <<< ce:<slug>
          包着，同一个 slug 重写就是**替换**，不会一层层叠加。

为什么只放一个脚本、且必须排在 Main 之前：
    RGSS 从上往下执行脚本，读到 Main 就进游戏主循环 —— Main 后面的脚本永远不执行。
    → rxdata 形态用 ce_core.add_rxdata_script（插在 Main 之前）；
    → 解包形态自己算文件名，让它在 Main 前面（见 _file_path）；
    → 两处并存（v21 常见）两处都写。

★ 写之前一定备份；★ 写之后一定回读校验。
"""
import io
import os
import re
import shutil
import time

import ce_boot

ce_boot.bootstrap()

import ce_core as C      # noqa: E402

CE_TITLE = "[ce] custom effects"
CE_FILE_STEM = "ce_custom_effects"

HEADER = """#==============================================================================#
#  [pkmn-ce] 自定义效果（特性 / 道具 / 招式）
#
#  由「宝可梦同人工具 · 自定义效果」生成。
#  每段代码用 >>> ce:<slug> 和 <<< ce:<slug> 包着：
#    · 重新生成同一个 slug = 就地替换那一段，不会重复叠加
#    · 整段删掉也不影响别的段
#  这个脚本必须排在 Main 之前才会被执行。
#==============================================================================#
"""

MARK_START = "# >>> ce:%s"
MARK_END = "# <<< ce:%s"

_RX_MIN_ENTRIES = C.LOADER_MAX_ENTRIES     # rxdata 少于这个数 = 解包后的占位


# ------------------------------------------------------------------
# 文本块
# ------------------------------------------------------------------
def _markers(slug):
    return MARK_START % slug, MARK_END % slug


def block_of(slug, code):
    """代码 → 带标记的整段。"""
    a, b = _markers(slug)
    return "%s\n%s\n%s" % (a, str(code).rstrip("\n"), b)


def split_blocks(text):
    """整份脚本 → {slug: 段文本}（段文本含标记）。"""
    out = {}
    cur, buf = None, []
    for line in str(text or "").split("\n"):
        m = re.match(r"^# >>> ce:(\S+)\s*$", line)
        if m:
            cur, buf = m.group(1), [line]
            continue
        if cur is not None:
            buf.append(line)
            if re.match(r"^# <<< ce:%s\s*$" % re.escape(cur), line):
                out[cur] = "\n".join(buf)
                cur, buf = None, []
    return out


def upsert_text(text, slug, code, at_top=False):
    """
    把 slug 那段替换掉；没有就插入。返回新整份文本。

    ★ at_top=True 时新段插在**文件开头**（第一个 ce 段之前）。延迟安装器
      `ce_plugin_hook` 必须最先定义，否则前面的补丁调用 `PkmnCE.after_plugins`
      时模块还不存在。
    """
    text = text if text is not None else ""
    new_block = block_of(slug, code)
    blocks = split_blocks(text)
    if slug in blocks:
        return text.replace(blocks[slug], new_block, 1)
    if at_top:
        idx = text.find("# >>> ce:")
        if idx < 0:
            body = text.rstrip("\n")
            return (new_block + "\n\n" + body + "\n") if body else (
                new_block + "\n")
        head, rest = text[:idx], text[idx:]
        return head.rstrip("\n") + "\n\n" + new_block + "\n\n" + rest
    body = text.rstrip("\n")
    return (body + "\n\n" + new_block + "\n") if body else (new_block + "\n")


def drop_text(text, slug):
    """删掉 slug 那段；一段都不剩返回 ""。"""
    blocks = split_blocks(text)
    if slug not in blocks:
        return text
    out = text.replace(blocks[slug], "", 1)
    out = re.sub(r"\n{3,}", "\n\n", out).rstrip("\n")
    return "" if not split_blocks(out) else out + "\n"


def list_blocks(game_dir):
    """游戏里现在装了哪些段 → [{"slug","lines"}]。"""
    text = read_ce_script(game_dir)
    return [{"slug": s, "lines": len(b.split("\n"))}
            for s, b in sorted(split_blocks(text).items())]


# ------------------------------------------------------------------
# 备份
# ------------------------------------------------------------------
def _backup(path):
    if not path or not os.path.isfile(path):
        return ""
    dst = "%s.ce-%s.bak" % (path, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copyfile(path, dst)
    return dst


# ------------------------------------------------------------------
# 目标位置
# ------------------------------------------------------------------
def _main_name(name):
    return re.sub(r"^\d+[_\-\s]*", "",
                  str(name).rsplit(".", 1)[0]).lower() == "main"


def _file_path(game_dir, create=False):
    """解包形态要写的 .rb 路径（已存在就返回它）。"""
    sdir = C.scripts_dir(game_dir)
    if not os.path.isdir(sdir):
        return ""
    for dp, _dn, fs in os.walk(sdir):
        for f in sorted(fs):
            if f.lower().endswith(".rb") and CE_FILE_STEM in f.lower():
                return os.path.join(dp, f)
    if not create:
        return ""
    # loader 形态：文件名必须带 4 位数字前缀
    if C._script_file_prefix(game_dir):            # noqa: SLF001
        return os.path.join(sdir, C.script_file_name(game_dir, CE_FILE_STEM))
    # 普通形态：让文件名排在 Main 前面
    # ★ Main 可能是个**目录**（v20.1 / v21 是 999_Main/999_Main.rb），
    #   所以得往下走一层找，不能只看顶层。
    main = ""
    for dp, dns, fs in os.walk(sdir):
        dns.sort()
        for f in sorted(fs):
            if f.lower().endswith(".rb") and _main_name(f):
                cand = os.path.join(dp, f)
                if not main or cand.count(os.sep) < main.count(os.sep):
                    main = f
        if main:
            break
    m = re.match(r"^(\d+)", main or "")
    if m:
        digits = m.group(1)
        name = "%0*d_%s.rb" % (len(digits), max(int(digits) - 1, 0), CE_FILE_STEM)
    else:
        name = "00_%s.rb" % CE_FILE_STEM    # 数字开头 → 排在所有字母文件之前
    return os.path.join(sdir, name)


def targets(game_dir):
    """
    本次要写的位置 → [{"mode","path","skip","reason"}]

    ★ rxdata 少于 10 条的是「脚本已解包」留下的空壳，写进去也不会被执行。
    """
    out = []
    for mode, path in C.scripts_containers(game_dir):
        if mode == "rxdata":
            _got, total = C.read_rxdata_entries(path)
            if total and total < _RX_MIN_ENTRIES:
                out.append({"mode": mode, "path": path, "skip": True,
                            "reason": "只有 %d 条，是解包后的占位，不往里写" % total})
                continue
        out.append({"mode": mode, "path": path, "skip": False, "reason": ""})
    return out


# ------------------------------------------------------------------
# 读现状
# ------------------------------------------------------------------
def read_ce_script(game_dir):
    """读现有的 [ce] 脚本正文（哪处有就用哪处）。"""
    for mode, path in C.scripts_containers(game_dir):
        if mode == "rxdata":
            for _i, title, text in (C.read_rxdata_entries(path)[0] or []):
                if title == CE_TITLE:
                    return text
        else:
            p = _file_path(game_dir)
            if p and os.path.isfile(p):
                return io.open(p, "r", encoding="utf-8",
                               errors="replace").read()
    return ""


# ------------------------------------------------------------------
# 写
# ------------------------------------------------------------------
def upsert(game_dir, slug, code, dry=False, at_top=False):
    """装一段效果代码 → {"slug","targets","verified","dry"}。"""
    slug = str(slug or "").strip()
    if not slug or not re.match(r"^[A-Za-z0-9_.\-]+$", slug):
        raise ValueError("slug 只能是字母数字和 . _ -（现在 %r）" % slug)
    reps = []
    for t in targets(game_dir):
        if t["skip"]:
            reps.append({"mode": t["mode"], "path": t["path"],
                         "action": "skipped", "reason": t["reason"]})
        elif t["mode"] == "rxdata":
            reps.append(_upsert_rxdata(t["path"], slug, code, dry, at_top))
        else:
            reps.append(_upsert_file(game_dir, slug, code, dry, at_top))
    ok = any(r.get("action") in ("created", "updated", "unchanged") for r in reps)
    return {"slug": slug, "dry": bool(dry), "targets": reps,
            "verified": bool(ok and not dry)}


def _upsert_rxdata(path, slug, code, dry, at_top=False):
    rep = {"mode": "rxdata", "path": path, "backup": ""}
    obj = C.load_rxdata(path)
    if not isinstance(obj, list):
        rep.update(action="failed", reason="不是脚本数组")
        return rep
    at = next((i for i, e in enumerate(obj)
               if C.rxdata_title(e) == CE_TITLE), None)
    rep["entries_before"] = len(obj)
    if at is None:
        if dry:
            rep["action"] = "would-create"
            return rep
        rep["backup"] = _backup(path)
        C.add_rxdata_script(path, CE_TITLE,
                            upsert_text(HEADER, slug, code, at_top=at_top))
        rep["action"] = "created"
        return rep

    old = C.rxdata_source(obj[at])
    new = upsert_text(old, slug, code, at_top=at_top)
    if new == old:
        rep["action"] = "unchanged"
        return rep
    if dry:
        rep["action"] = "would-update"
        return rep
    rep["backup"] = _backup(path)
    C.write_rxdata_entry(path, at, new, expect=old)
    rep.update(action="updated", index=at)
    return rep


def _upsert_file(game_dir, slug, code, dry, at_top=False):
    rep = {"mode": "file", "path": ""}
    p = _file_path(game_dir, create=True)
    if not p:
        rep.update(action="failed", reason="找不到 Data/Scripts 目录")
        return rep
    rep["path"] = p
    exists = os.path.isfile(p)
    old = io.open(p, "r", encoding="utf-8", errors="replace").read() \
        if exists else HEADER
    new = upsert_text(old, slug, code, at_top=at_top)
    if new == old:
        rep["action"] = "unchanged"
        return rep
    if dry:
        rep["action"] = "would-update" if exists else "would-create"
        return rep
    if exists:
        rep["backup"] = _backup(p)
        rep["action"] = "updated"
    else:
        rep["action"] = "created"
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    return rep


def remove(game_dir, slug, dry=False):
    """删掉一段；一段不剩就把整个 ce 脚本也删了。"""
    reps = []
    for t in targets(game_dir):
        if t["skip"]:
            continue
        if t["mode"] == "rxdata":
            path = t["path"]
            obj = C.load_rxdata(path)
            at = next((i for i, e in enumerate(obj)
                       if C.rxdata_title(e) == CE_TITLE), None) \
                if isinstance(obj, list) else None
            if at is None:
                continue
            old = C.rxdata_source(obj[at])
            new = drop_text(old, slug)
            if dry:
                reps.append({"mode": "rxdata", "path": path,
                             "action": "would-remove"})
            elif not new:
                bak = _backup(path)
                C.delete_rxdata_entry(path, at)
                reps.append({"mode": "rxdata", "path": path,
                             "action": "removed-all", "backup": bak})
            else:
                bak = _backup(path)
                C.write_rxdata_entry(path, at, new, expect=old)
                reps.append({"mode": "rxdata", "path": path,
                             "action": "updated", "backup": bak})
        else:
            p = _file_path(game_dir)
            if not p or not os.path.isfile(p):
                continue
            new = drop_text(io.open(p, "r", encoding="utf-8",
                                    errors="replace").read(), slug)
            if dry:
                reps.append({"mode": "file", "path": p, "action": "would-remove"})
                continue
            bak = _backup(p)
            if not new:
                os.remove(p)
                reps.append({"mode": "file", "path": p,
                             "action": "removed-all", "backup": bak})
            else:
                with io.open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(new)
                reps.append({"mode": "file", "path": p,
                             "action": "updated", "backup": bak})
    return {"slug": slug, "dry": bool(dry), "targets": reps}


def check_installed(game_dir, slug):
    """回读确认某段真的落盘了 → (在不在, 共几段)。"""
    blocks = split_blocks(read_ce_script(game_dir))
    return slug in blocks, len(blocks)
