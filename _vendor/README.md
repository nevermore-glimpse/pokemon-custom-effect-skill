# _vendor

`rmarshal.py` —— Ruby Marshal（RXData）读写实现，纯标准库。

来源：从「宝可梦同人工具」主项目原样拷入（同 LICENSE）。
放在这里是为了让整个 `pokemon-custom-effect/` 目录**单独拷走也能用**，
不需要装 `rubymarshal` 之类的第三方包。

已验证：对 `Scripts.rxdata` 能字节级往返（读出来再写回，文件完全一致），
16 / 18 / 21.1 与多个同人游戏都实测过。
