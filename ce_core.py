# -*- coding: utf-8 -*-
"""
自包含核心：读写 RMXP 脚本、认版本、算函数指纹、查基准。

**这个文件不依赖主项目**，只用标准库 + 同目录 `_vendor/rmarshal.py`
（纯 Python 的 Ruby Marshal 实现）。所以整个 pokemon-custom-effect 目录
可以直接拷给别人用，装个 Python 3.8+ 就行，不用 pip install 任何东西。

为什么不用 pip 的 rubymarshal：那是主项目用的，别人的机器上不一定有；
`_vendor/rmarshal.py` 是我们自己的实现，对 Scripts.rxdata 能**字节级往返**
（读出来再写回，文件一模一样 —— 这是改脚本不弄坏游戏的前提）。

对外 API（其余模块只用这些）：

    读      iter_named_scripts / collect_scripts / rxdata_source / rxdata_title
    写      write_rxdata_entry / add_rxdata_script / delete_rxdata_entry
    位置    data_dir / scripts_dir / rxdata_path / scripts_containers / script_file_name
    版本    essentials_version
    指纹    scan_defs / scan_game_scripts
    基准    list_baselines / load_baseline / pick_baseline_version / best_baseline
    数据    pbs_dir / read_pbs_ids / read_dat_ids / data_ids
    源码    extract_func
"""
import gzip
import hashlib
import io
import json
import os
import re
import zlib

# 自带的最小 Marsch 实现（纯标准库）
import sys as _sys
_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor")
if _VENDOR not in _sys.path:
    _sys.path.insert(0, _VENDOR)
import rmarshal                                    # noqa: E402

RXDATA_NAME = "Scripts.rxdata"
BACKUP_NAME = "ScriptsBackup.rxdata"
PLUGIN_RXDATA_NAME = "PluginScripts.rxdata"
SCRIPTS_DIR_NAME = "Scripts"

# Scripts.rxdata 少于这个条数 → 多半只是「脚本已解包」留下的 loader 空壳
LOADER_MAX_ENTRIES = 10

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
BASELINE_GZ = os.path.join(DATA_DIR, "baselines.json.gz")


# ================================================================
# Marshal 读写
# ================================================================
def _bytes(value):
    """
    rmarshal 读出来的串 → 原始字节。

    ★ rmarshal 的 RStr 是把 Ruby 的字节串按 **utf-8 + surrogateescape** 解出来的
      （压缩过的脚本源码在 utf-8 眼里是乱码，非法字节全落在 surrogate 区）。
      编码回同一套参数就能 1:1 还原原始字节 —— 这是字节级往返的关键。
    """
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    text = str(value)
    try:
        return text.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        return text.encode("latin-1", "replace")


def _rs(text):
    """普通文本 → 能写进 rxdata 的 Ruby String（非 ASCII 自动带上 UTF-8 标记）。"""
    return rmarshal.RStr.smart(str(text))


def _rb(blob):
    """原始字节 → Ruby String（无编码标记，和游戏自己写的一致）。"""
    return rmarshal.RStr(bytes(blob).decode("utf-8", "surrogateescape"))


def load_rxdata(path):
    """读任意 .rxdata / .dat → Python 对象；读不出来抛 RuntimeError。"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise RuntimeError("读不了 %s：%s" % (path, e)) from e
    try:
        return rmarshal.loads(raw)
    except Exception as e:                         # noqa: BLE001
        raise RuntimeError(
            "解析 %s 失败（不是标准的 Ruby Marshal 文件，或被加密/压缩过）：%s"
            % (path, e)) from e


def dump_rxdata(obj, path, backup=None):
    """
    写回 .rxdata（先写 .tmp 再原子替换）。返回备份文件名（没备份返回 ""）。

    ★ 一定先 dump 成 bytes 再落盘：中途异常不会留下半个文件。
    """
    blob = rmarshal.dumps(obj)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)
    return backup or ""


# ================================================================
# 路径
# ================================================================
def data_dir(game_dir):
    return os.path.join(game_dir, "Data")


def rxdata_path(game_dir):
    return os.path.join(data_dir(game_dir), RXDATA_NAME)


def plugin_rxdata_path(game_dir):
    return os.path.join(data_dir(game_dir), PLUGIN_RXDATA_NAME)


def _has_rb(d):
    try:
        for _dp, _dn, fs in os.walk(d):
            for f in fs:
                if str(f).lower().endswith(".rb"):
                    return True
    except OSError:
        return False
    return False


# ---- loader 形态：Scripts.rxdata 只有一条 load_scripts_from_folder(...) ----
_LOADER_CALL_RE = re.compile(r"^load_scripts_from_folder\(\s*(.+?)\s*\)\s*$", re.M)


def _resolve_loader_arg(arg, game_dir):
    parts = re.findall(r"['\"]([^'\"]+)['\"]", str(arg or ""))
    if not parts or "folder" in str(arg):
        return ""
    rel = os.path.join(*parts) if len(parts) > 1 else parts[0]
    return os.path.normpath(rel if os.path.isabs(rel)
                            else os.path.join(game_dir, rel))


def loader_scripts_dir(game_dir):
    """
    loader 形态下真正的脚本目录；不是这种形态返回 ""。

    ★ 只有 Data/Scripts 不存在时才会走到这里看 loader。
    """
    rx = rxdata_path(game_dir)
    if not os.path.isfile(rx):
        return ""
    try:
        obj = load_rxdata(rx)
    except RuntimeError:
        return ""
    if not isinstance(obj, list) or not obj or len(obj) > LOADER_MAX_ENTRIES:
        return ""
    for e in obj:
        text = rxdata_source(e)
        if "load_scripts_from_folder" not in text:
            continue
        for m in _LOADER_CALL_RE.finditer(text):
            p = _resolve_loader_arg(m.group(1), game_dir)
            if p and os.path.isdir(p) and _has_rb(p):
                return p
    return ""


def script_dirs(game_dir):
    """脚本目录列表（普通形态是 Data/Scripts；loader 形态是 loader 指的目录）。"""
    d = os.path.join(data_dir(game_dir), SCRIPTS_DIR_NAME)
    if os.path.isdir(d) and _has_rb(d):
        return [d]
    alt = loader_scripts_dir(game_dir)
    return [alt] if alt else []


def scripts_dir(game_dir):
    """新脚本该写去哪（找不到就返回 Data/Scripts 让调用方自己判断）。"""
    d = os.path.join(data_dir(game_dir), SCRIPTS_DIR_NAME)
    if os.path.isdir(d) and _has_rb(d):
        return d
    return loader_scripts_dir(game_dir) or d


def scripts_containers(game_dir):
    """
    脚本的**所有**落盘位置 → [("file", 目录), ("rxdata", 路径)]

    ★ 两处并存时两处都要写：v21 起很多同人游戏 Data/Scripts/*.rb 与
      Scripts.rxdata 都在，运行时读哪份看 Game.ini 的 `Scripts=`。
    """
    out = []
    sdir = scripts_dir(game_dir)
    if os.path.isdir(sdir) and _has_rb(sdir):
        out.append(("file", sdir))
    rx = rxdata_path(game_dir)
    if os.path.isfile(rx):
        out.append(("rxdata", rx))
    elif not out:
        bak = os.path.join(data_dir(game_dir), BACKUP_NAME)
        if os.path.isfile(bak):
            out.append(("rxdata", bak))
    return out


def _script_file_prefix(game_dir):
    """
    新脚本文件名要带的数字前缀（loader 形态可能过滤掉没有 4 位数字前缀的文件）。

    判据：Scripts.rxdata 是 loader（≤10 条）且正文里有 `f[/^\\d{4}/]` 这类过滤。
    """
    dirs = script_dirs(game_dir)
    if not dirs:
        return ""
    rx = rxdata_path(game_dir)
    if not os.path.isfile(rx):
        return ""
    try:
        obj = load_rxdata(rx)
    except RuntimeError:
        return ""
    if not isinstance(obj, list) or len(obj) > LOADER_MAX_ENTRIES:
        return ""
    joined = "\n".join(rxdata_source(e) for e in obj)
    if not re.search(r"!\s*f\[\s*/\^\\d\{4\}/", joined):
        return ""
    for root in dirs:
        for dp, _dn, fs in os.walk(root):
            for f in sorted(fs):
                m = re.match(r"^(\d{4})", f)
                if m and "main" in f.lower():
                    return m.group(1)
    return "9999"


def script_file_name(game_dir, name, index=1):
    """新脚本的文件名（遵守 loader 过滤规则，并排在 Main 前面）。"""
    safe = re.sub(r"[^0-9A-Za-z_]", "", str(name)) or "Script"
    base = _script_file_prefix(game_dir)
    if not base:
        return safe + ".rb"
    num = int(base) - 1
    return "%04d_%02d %s.rb" % (max(num, 0), int(index), safe)


# ================================================================
# 读脚本
# ================================================================
def _decompress_script(raw):
    """源码字节 → (解压后字节, 错误说明)；没压缩/解压失败原样返回。"""
    code = _bytes(raw)
    if not code:
        return code, ""
    try:
        return zlib.decompress(code), ""
    except zlib.error as e:
        return code, str(e)


def rxdata_source(entry):
    """rxdata 单个条目 → 源码文本（zlib 解压 + utf-8 解码）。"""
    if not isinstance(entry, (list, tuple)) or len(entry) < 3:
        return ""
    code, _err = _decompress_script(entry[2])
    if not code:
        return ""
    return code.decode("utf-8", "replace")


def rxdata_title(entry):
    """rxdata 单个条目 → 标题（脚本编辑器左边那一栏）。"""
    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
        return ""
    raw = _bytes(entry[1])
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def read_rxdata_entries(path):
    """
    读 Scripts.rxdata → ([(原始下标, 标题, 源码), ...], 总条目数)

    ★ 下标一律是**原始位置**，绝不重新编号 —— 写回时直接按它落回去。
      空标记条目（`[[ 章节 ]]`）也占位置，跳空后重新编号会写错条目。
    """
    try:
        obj = load_rxdata(path)
    except RuntimeError:
        return [], 0
    if not isinstance(obj, list):
        return [], 0
    out = []
    for i, e in enumerate(obj):
        text = rxdata_source(e)
        if not text:
            continue
        out.append((i, rxdata_title(e), text))
    return out, len(obj)


def write_rxdata_entry(path, index, new_text, expect=None):
    """
    把第 index 条脚本换成 new_text（就地写回）。返回 None。

    ★ expect 给定时先核对当前内容是否真等于它，不等就拒写 —— 防「把 A 脚本
      的代码写进 B 条目」这种会毁工程的损坏（下标算错 / 读写之间文件被换过）。
    """
    obj = load_rxdata(path)
    if not isinstance(obj, list) or not 0 <= index < len(obj):
        raise RuntimeError("脚本下标 %s 越界（共 %s 条）"
                           % (index, len(obj) if isinstance(obj, list) else 0))
    if expect is not None:
        cur = rxdata_source(obj[index])
        if cur != expect:
            raise RuntimeError(
                "要写的是第 %s 条「%s」，但内容已变（%d 字节 ≠ %d 字节），已拒绝写入"
                % (index, rxdata_title(obj[index]), len(cur), len(expect)))
    obj[index][2] = _rb(zlib.compress(str(new_text).encode("utf-8")))
    dump_rxdata(obj, path)


def add_rxdata_script(path, title, source, before_title="Main"):
    """
    新增一条脚本，返回它的下标。

    ★ 条目结构 = [编号, 标题, zlib 压缩源码]（和官方 scripts_extract.rb 一致）。
    ★ **插在 Main 之前**：RGSS 从上往下 eval，读到 Main 就进主循环，
      排在后面的脚本永远不执行。找不到 Main 就追加到末尾。
    """
    obj = load_rxdata(path)
    if not isinstance(obj, list):
        raise RuntimeError("%s 不是脚本列表，放弃新增" % os.path.basename(path))
    used = set()
    for e in obj:
        if isinstance(e, (list, tuple)) and e and isinstance(e[0], int):
            used.add(e[0])
    sid = (max(used) + 1) if used else 1
    while sid in used:
        sid += 1
    entry = [sid, _rs(title), _rb(zlib.compress(str(source).encode("utf-8")))]
    at = len(obj)
    if before_title:
        want = re.sub(r"[^0-9a-z]+", "", str(before_title).lower())
        for i, e in enumerate(obj):
            if isinstance(e, (list, tuple)) and len(e) >= 2 and \
                    re.sub(r"[^0-9a-z]+", "", rxdata_title(e).lower()) == want:
                at = i
                break
    obj.insert(at, entry)
    dump_rxdata(obj, path)
    return at


def delete_rxdata_entry(path, index):
    """删掉第 index 条脚本（返回被删的标题）。"""
    obj = load_rxdata(path)
    if not isinstance(obj, list) or not 0 <= index < len(obj):
        raise RuntimeError("脚本下标 %s 越界，放弃删除" % index)
    title = rxdata_title(obj[index])
    del obj[index]
    dump_rxdata(obj, path)
    return title


# ================================================================
# 脚本枚举
# ================================================================
_LEADING_INDEX_RE = re.compile(r"^\d+\s*[_\-\s]*")


def script_name(key, title=None):
    """
    脚本「名字」= RMXP 脚本编辑器左边那一栏。

      · rxdata 条目 → 直接用标题
      · 解包 .rb   → 文件名去掉 .rb 与编号前缀
                     （999_Main/999_Main.rb → Main、021_Compiler/001_Compiler.rb → Compiler）
    """
    if title:
        t = str(title).strip()
        if t:
            return t
    base = os.path.basename(str(key or "").replace("\\", "/"))
    base = re.sub(r"\.rb$", "", base, flags=re.I)
    base = _LEADING_INDEX_RE.sub("", base)
    return base.strip() or base


def collect_scripts(game_dir, allow_backup=True, both=False):
    """
    游戏脚本 → [(mode, key, path, title, text), ...]

      mode="file"   key=相对路径，path=真实文件，title=None
      mode="rxdata" key=**原始条目下标**，path=Scripts.rxdata，title=条目标题

    ★ both=False（只读场合）：Data/Scripts 有就读目录，否则读 rxdata。
    ★ both=True（要改脚本）：两处都收，同一个脚本会返回两条。
    """
    files = []
    for sdir in script_dirs(game_dir):
        for dirpath, dirnames, filenames in os.walk(sdir):
            dirnames.sort()
            for f in sorted(filenames):
                if not f.endswith(".rb"):
                    continue
                p = os.path.join(dirpath, f)
                rel = os.path.relpath(p, game_dir).replace("\\", "/")
                try:
                    with io.open(p, "r", encoding="utf-8", errors="replace") as fp:
                        files.append(("file", rel, p, None, fp.read()))
                except OSError:
                    pass

    ents = []
    rx = rxdata_path(game_dir)
    if os.path.isfile(rx):
        got, _total = read_rxdata_entries(rx)
        if len(got) >= LOADER_MAX_ENTRIES:
            ents = [("rxdata", i, rx, title, text) for i, title, text in got]

    if both:
        return files + ents
    if files:
        return files
    if ents:
        return ents
    if allow_backup:
        bak = os.path.join(data_dir(game_dir), BACKUP_NAME)
        if os.path.isfile(bak):
            got, _total = read_rxdata_entries(bak)
            return [("rxdata", i, bak, title, text) for i, title, text in got]
    return []


def iter_named_scripts(game_dir, allow_backup=False, both=False):
    """[(mode, key, path, 脚本名, 源码), ...]"""
    return [(m, k, p, script_name(k, t), text)
            for m, k, p, t, text in collect_scripts(
                game_dir, allow_backup=allow_backup, both=both)]


# ================================================================
# 版本
# ================================================================
_VERSION_RES = (
    re.compile(r"module\s+Essentials\b[\s\S]{0,4000}?\bVERSION\s*=\s*[\"']([^\"']+)"),
    re.compile(r"\bESSENTIALS_?VERSION\s*=\s*[\"']([^\"']+)"),
)


def essentials_version(game_dir):
    """读游戏里的 Essentials 版本号（读不到返回 ""）。"""
    for rx in _VERSION_RES:
        for _m, _k, _p, _n, text in collect_scripts(game_dir, allow_backup=False):
            m = rx.search(text)
            if m:
                return m.group(1).strip()
    return ""


# ================================================================
# 函数指纹
# ================================================================
_DEF_RE = re.compile(
    r"^([ \t]*)def\s+((?:self\s*\.\s*)?"
    r"[A-Za-z_][A-Za-z0-9_]*[?!]?|"
    r"(?:self\s*\.\s*)?(?:\[\]=?|<<|>>|[+\-*/%]=?|<=>|<=|>=|==|===|!=|!|~|&|\||\^))")
OPEN_RE = re.compile(
    r"^(module|class|def|if|unless|while|until|for|case|begin)\b")
DO_RE = re.compile(r"\bdo\b\s*(\|[^|]*\|)?\s*$")
_ONE_LINE_DEF = re.compile(r"^([ \t]*)def\b.*\bend\b\s*$")


def strip_comment(line):
    """去掉行尾注释（`#` 在引号里 / 紧贴代码时不删）。"""
    pos = -1
    for i, c in enumerate(line):
        if c in "\"'`":
            pos = i
            break
        if c == "#":
            break
    idx = line.find("#")
    if idx < 0:
        return line
    if 0 <= pos < idx:
        return line
    if idx > 0 and line[idx - 1] not in " \t":
        return line
    return line[:idx].rstrip()


def _normalize_body(lines):
    out = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        line = strip_comment(line).strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def fingerprint(text):
    """函数体 → 12 位指纹（先去掉注释与缩进差异，避免只改注释被误判）。"""
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:12]


def scan_defs(text):
    """
    一份 Ruby 源码 → {限定名: 指纹}（`Compiler.main` / `Battle::Move.pbEffect`）。

    ★ 用「缩进配对 end」定位函数结尾：Essentials 官方脚本缩进严格，
      魔改过的也基本沿用；基线与实际扫描用同一套算法，偶有偏差也是两边一起偏。
    """
    lines = text.split("\n")
    stack = []
    out = {}
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r")
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())

        if re.match(r"^end\b", stripped):
            while stack and stack[-1][0] >= indent:
                stack.pop()
            continue

        if _ONE_LINE_DEF.match(line):
            continue
        m = _DEF_RE.match(line)
        if m:
            fname = re.sub(r"\s+", "", m.group(2))
            qual = ".".join([s[1] for s in stack] + [fname])
            stack.append((indent, fname, True))
            depth = 0
            end_i = len(lines)
            for j in range(i + 1, len(lines)):
                s2 = lines[j].strip()
                ind2 = len(lines[j]) - len(lines[j].lstrip())
                if OPEN_RE.match(s2) or DO_RE.search(s2.rstrip()):
                    if ind2 >= indent or DO_RE.search(s2.rstrip()):
                        depth += 1
                elif re.match(r"^end\b", s2):
                    if depth == 0 and ind2 <= indent:
                        end_i = j
                        break
                    depth -= 1
            out[qual] = fingerprint(_normalize_body(lines[i + 1:end_i]))
            continue

        m = re.match(r"^(module|class)\s+([A-Za-z_][\w:]*)", stripped)
        if m:
            stack.append((indent, m.group(2), False))
            continue

        if OPEN_RE.match(stripped) or DO_RE.search(line.rstrip()):
            stack.append((indent, "_", False))
    return out


_SCAN_CACHE = {}


def scan_game_scripts(game_dir):
    """
    整份游戏脚本 → {脚本名: {限定名: 指纹}}（带缓存）。

    ★ 同名脚本（同人游戏会把一个名字用两次）**合并**，先出现的指纹优先；
      只留第一份会把第二份的函数整个认成「缺失」。
    """
    key = os.path.abspath(str(game_dir))
    if key in _SCAN_CACHE:
        return _SCAN_CACHE[key]
    out = {}
    for _m, _k, _p, name, text in iter_named_scripts(game_dir):
        funcs = scan_defs(text)
        if name in out:
            for fname, fp in funcs.items():
                out[name].setdefault(fname, fp)
        else:
            out[name] = funcs
    _SCAN_CACHE[key] = out
    return out


def clear_cache():
    _SCAN_CACHE.clear()
    _BASE_CACHE.clear()


# ================================================================
# 官方基准（函数指纹表，data/baselines.json.gz）
# ================================================================
_BASE_CACHE = {}
_base_loaded = None


def _all_baselines():
    """
    读全部基准 → {版本: {脚本名: {函数: 指纹}}}

    ★ 文件是 gzip 后的一整份 JSON（9 个版本，压缩前 2.7MB，压缩后 ~300KB）。
      没有这个文件也不影响主流程：版本号能读出来就不需要基准，
      只是少了「作者改过引擎吗」这一层判断。
    """
    global _base_loaded
    if _base_loaded is not None:
        return _base_loaded
    _base_loaded = {}
    if os.path.isfile(BASELINE_GZ):
        try:
            with gzip.open(BASELINE_GZ, "rb") as f:
                raw = json.loads(f.read().decode("utf-8"))
            if isinstance(raw, dict):
                _base_loaded = raw
        except Exception:                          # noqa: BLE001
            _base_loaded = {}
    return _base_loaded


def _vkey(text):
    try:
        return tuple(int(x) for x in str(text).split("."))
    except ValueError:
        return (999,)


def list_baselines():
    """内置的基准版本列表（按版本号排序）。"""
    return sorted(_all_baselines(), key=_vkey)


def load_baseline(version):
    """{脚本名: {函数: 指纹}}；没有这个版本返回 None。"""
    return _all_baselines().get(str(version))


def flat_funcs(scripts):
    """{脚本: {函数: 指纹}} → {"脚本.函数": 指纹}。"""
    return {"%s.%s" % (name, fname): fp
            for name, funcs in (scripts or {}).items()
            for fname, fp in funcs.items()}


def pick_baseline_version(version):
    """按版本号挑最接近的基准 → (版本 or None, 是否完全相同)。"""
    ver = (version or "").strip()
    known = list_baselines()
    if not known:
        return None, False
    if ver in known:
        return ver, True
    try:
        cur = tuple(int(x) for x in ver.split(".")[:2])
    except (ValueError, AttributeError):
        return known[-1], False
    same_major = [v for v in known
                  if _vkey(v)[:1] == cur[:1] and _vkey(v) <= cur]
    if same_major:
        return same_major[-1], False
    lower = [v for v in known if _vkey(v) <= cur]
    return (lower[-1] if lower else known[-1]), False


def best_baseline(scripts, min_ratio=0.5):
    """版本号靠不住时按指纹重合度挑基准 → (版本 or None, 重合比例)。"""
    cur = flat_funcs(scripts)
    best, best_r = None, 0.0
    for v in list_baselines():
        want = flat_funcs(load_baseline(v))
        if not want:
            continue
        same = sum(1 for k, h in want.items() if cur.get(k) == h)
        r = same / float(len(want))
        if r > best_r:
            best, best_r = v, r
    if best_r < min_ratio:
        return None, best_r
    return best, best_r


# ================================================================
# 取某个函数的源码
# ================================================================
def extract_func(text, func):
    """
    从脚本文本里抠出某个函数（def … end，含嵌套）；找不到返回 ""。

    ★ 方法名可能以 `?` / `!` 结尾（`abilityActive?`）——不能用 `\\b` 收尾，
      否则 `?` 与后面的 `(` 之间没有词边界，永远匹配不到。
    ★ 只给 `abilityActive` 也能找到 `abilityActive?`（先精确，再试带后缀的）。
    """
    name = str(func).split(".")[-1].strip()
    if not name:
        return ""
    cands = [name]
    if not name[-1] in "?!":
        cands += [name + "?", name + "!"]
    lines = text.split("\n")
    for cand in cands:
        rx = re.compile(r"^([ \t]*)def\s+(?:self\s*\.\s*)?"
                        + re.escape(cand) + r"(?![\w?!])")
        for i, ln in enumerate(lines):
            m = rx.match(ln)
            if not m:
                continue
            base = len(m.group(1))
            j = i + 1
            while j < len(lines):
                s2 = lines[j]
                st = s2.strip()
                if not st or st.startswith("#"):
                    j += 1
                    continue
                if re.match(r"^[ \t]*end[ \t]*\r?$", s2):
                    if (len(s2) - len(s2.lstrip(" \t"))) <= base:
                        break
                j += 1
            return "\n".join(lines[i:min(j + 1, len(lines))])
    return ""


# ================================================================
# 数据 ID（PBS / .dat）
# ================================================================
PBS_FILES = {"ability": "abilities.txt", "item": "items.txt",
             "move": "moves.txt", "species": "pokemon.txt"}

_SECTION_RE = re.compile(r"^\[([A-Za-z_]\w*)\]", re.M)
_CSV_RE = re.compile(r"^\s*\d+\s*,\s*([A-Za-z_]\w*)\s*,", re.M)


def pbs_dir(game_dir):
    d = os.path.join(str(game_dir), "PBS")
    return d if os.path.isdir(d) else ""


def read_pbs_ids(game_dir, kind):
    """PBS 里某类数据的 ID 集合；文件不存在返回 None（≠ 空集）。"""
    d = pbs_dir(game_dir)
    fname = PBS_FILES.get(kind)
    if not d or not fname:
        return None
    p = os.path.join(d, fname)
    if not os.path.isfile(p):
        return None
    try:
        with io.open(p, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    return set(_SECTION_RE.findall(text)) | set(_CSV_RE.findall(text))


def read_dat_ids(game_dir, kind):
    """
    Data/<kind>.dat 里的 ID 集合（没有 PBS 的成品游戏用）。读不到返回 None。

    ★ 只认「全大写符号名」—— 那才是 ID；对象里的其它字符串不是。
    """
    p = os.path.join(data_dir(game_dir), kind + ".dat")
    if not os.path.isfile(p):
        return None
    try:
        obj = load_rxdata(p)
    except RuntimeError:
        return None
    out = set()

    def walk(node, depth=0):
        if depth > 6 or len(out) > 20000:
            return
        if isinstance(node, rmarshal.RHash):
            for k, v in node.items():
                name = k if isinstance(k, str) else getattr(k, "name", None)
                if isinstance(name, str) and re.match(r"^[A-Z][A-Z0-9_]*$", name):
                    out.add(name)
                walk(v, depth + 1)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v, depth + 1)
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(k, depth + 1)
                walk(v, depth + 1)
        elif isinstance(node, rmarshal.RObject):
            for v in node.ivars.values():
                walk(v, depth + 1)

    walk(obj)
    return out or None


def data_ids(game_dir, kind):
    """某类数据的全部 ID → (集合 or None, 来源说明)。先 PBS 后 .dat。"""
    ids = read_pbs_ids(game_dir, kind)
    if ids is not None:
        return ids, "PBS/" + PBS_FILES.get(kind, "")
    ids = read_dat_ids(game_dir, kind)
    if ids is not None:
        return ids, "Data/%s.dat" % kind
    return None, ""


# ================================================================
# 插件脚本（Data/PluginScripts.rxdata）
# ================================================================
def read_plugin_entries(path):
    """
    读 PluginScripts.rxdata → [(插件名, 文件名, 源码), ...]

    ★ 结构：[[插件名, 元数据, [[文件名, zlib源码], ...]], ...]
    ★ **插件脚本在主脚本之后才 eval**（Main 里 PluginManager.runPlugins），
      所以插件会覆盖我们在普通脚本里定义的方法 —— 这是 patch 必须延迟的原因。
    """
    try:
        obj = load_rxdata(path)
    except RuntimeError:
        return []
    if not isinstance(obj, list):
        return []
    out = []
    for e in obj:
        if not isinstance(e, (list, tuple)) or len(e) < 3:
            continue
        plugin = (_bytes(e[0])).decode("utf-8", "replace")
        files = e[2]
        if not isinstance(files, (list, tuple)):
            continue
        for scr in files:
            if not isinstance(scr, (list, tuple)) or len(scr) < 2:
                continue
            text = rxdata_source([0, scr[0], scr[1]])
            if text:
                out.append((plugin, (_bytes(scr[0])).decode("utf-8", "replace"),
                            text))
    return out


def plugin_scripts(game_dir):
    """这个游戏所有插件脚本 → [(插件名, 文件名, 源码)]；没有插件返回 []。"""
    p = plugin_rxdata_path(game_dir)
    if not os.path.isfile(p):
        return []
    key = ("plugins", os.path.abspath(str(game_dir)))
    if key not in _SCAN_CACHE:
        _SCAN_CACHE[key] = read_plugin_entries(p)
    return _SCAN_CACHE[key]


def has_plugin_manager(game_dir):
    """
    有没有插件系统（v18 起有）。看脚本里有没有 PluginManager，读不出来才看目录。
    """
    readable = False
    for _m, _k, _p, _n, text in collect_scripts(game_dir, allow_backup=False):
        readable = True
        if "module PluginManager" in text or "def self.compilePlugins" in text:
            return True
    if readable:
        return False
    return os.path.isdir(os.path.join(game_dir, "Plugins"))
