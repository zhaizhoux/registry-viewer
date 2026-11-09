"""命令行入口：默认启动图形界面，也提供无界面的只读查询/导出命令。"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from typing import Any, List, Optional

from . import __version__
from .export import FORMATS, build_export
from .paths import PathError, normalize_path
from .registry import Registry, RegistryError
from .search import VALID_SCOPES, search
from .server import create_server


def _registry(view: str) -> Registry:
    return Registry(view)


def _print_error(exc: Exception) -> int:
    print("错误：%s" % exc, file=sys.stderr)
    return 2


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        server = create_server(
            host=args.host, port=args.port, token=args.token, quiet=args.quiet,
        )
    except ValueError as exc:
        return _print_error(exc)
    print("regview %s | 只读注册表查看器" % __version__)
    print("打开地址：%s" % server.url)  # type: ignore[attr-defined]
    print("仅监听 %s，按 Ctrl+C 停止。" % args.host)
    if not args.no_browser:
        timer = threading.Timer(0.5, lambda: webbrowser.open(server.url))  # type: ignore[attr-defined]
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        server.server_close()
    return 0


def cmd_roots(args: argparse.Namespace) -> int:
    for item in _registry(args.view).roots():
        print("%-5s %-22s %s" % (item["alias"], item["name"], item["description"]))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    data = _registry(args.view).node(args.path)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print("路径：%s" % data["path"])
    if data["error"]:
        print("读取失败：%s" % data["error"]["message"])
        return 1
    print("\n子键 (%d)：" % len(data["subkeys"]))
    for name in data["subkeys"]:
        print("  [+] %s" % name)
    print("\n值 (%d)：" % len(data["values"]))
    for value in data["values"]:
        print("  %-32s %-22s %s" % (value["name"] or "(默认)", value["type"], value["display"]))
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    detail = _registry(args.view).value_detail(args.path, args.name)
    if args.json:
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        return 0
    print("路径：%s" % detail["path"])
    print("名称：%s" % (detail["name"] or "(默认)"))
    print("类型：%s (%d 字节)" % (detail["type"], detail["size"]))
    print("数据：%s" % detail["full"])
    if detail.get("expanded") and detail["expanded"] != detail["full"]:
        print("展开：%s" % detail["expanded"])
    if detail.get("hex"):
        print("\n十六进制：\n%s" % detail["hex"])
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    result = search(
        _registry(args.view), args.query, args.root, scope=args.scope,
        limit=args.limit, max_keys=args.max_keys, time_limit=args.seconds,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print("在 %s 下扫描 %d 个键，命中 %d 条，耗时 %ss，跳过 %d 个受限键%s" % (
        result["root"], result["scanned"], result["count"], result["elapsed"],
        result["errors"], "（结果已截断：%s）" % result["truncated"] if result["truncated"] else "",
    ))
    for item in result["results"]:
        label = "键  " if item["kind"] == "key" else "值  "
        print("  %s%-24s %-18s %s" % (label, item["name"], item["type"], item["path"]))
        if item["detail"] and item["detail"] != "子键":
            print("      %s" % item["detail"][:160])
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    result = build_export(_registry(args.view), args.path, args.format, args.max_keys)
    print("导出 %s：%d 个键 / %d 个值 / %d 个受限键%s" % (
        args.format, result["stats"]["keys"], result["stats"]["values"],
        result["stats"]["errors"], "（已截断）" if result["stats"]["truncated"] else "",
    ), file=sys.stderr)
    if args.output:
        with open(args.output, "wb") as handle:
            handle.write(result["text"].encode(result["encoding"]))
        print("已写入：%s" % args.output, file=sys.stderr)
    else:
        # stdout 始终用 UTF-8，避免 utf-16 BOM 破坏终端
        sys.stdout.write(result["text"])
    return 0


def _add_view(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--view", choices=("default", "64", "32"), default="default",
                        help="注册表视图（64/32 位 WOW64 重定向）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regview",
        description="只读的 Windows 注册表图形化查看器（本地浏览器界面 + 命令行）",
        epilog="不带子命令时直接启动图形界面。所有操作均为只读，不会修改注册表。",
    )
    parser.add_argument("--version", action="version", version="regview " + __version__)
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="启动本地图形界面（默认）")
    serve.add_argument("--host", default="127.0.0.1", help="监听地址，仅允许本地回环")
    serve.add_argument("--port", type=int, default=0, help="端口，0 表示自动选择")
    serve.add_argument("--token", default="", help="自定义访问 token（默认随机生成）")
    serve.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    serve.add_argument("--quiet", action="store_true", help="不输出访问日志")
    serve.set_defaults(func=cmd_serve)

    roots = sub.add_parser("roots", help="列出五个根键")
    _add_view(roots)
    roots.set_defaults(func=cmd_roots)

    listing = sub.add_parser("list", help="列出某个键的子键和值")
    listing.add_argument("path", nargs="?", default="HKEY_CURRENT_USER")
    listing.add_argument("--json", action="store_true", help="输出 JSON")
    _add_view(listing)
    listing.set_defaults(func=cmd_list)

    get = sub.add_parser("get", help="查看某个值的完整内容")
    get.add_argument("path")
    get.add_argument("name", nargs="?", default="", help="值名，留空表示默认值")
    get.add_argument("--json", action="store_true", help="输出 JSON")
    _add_view(get)
    get.set_defaults(func=cmd_get)

    finder = sub.add_parser("search", help="搜索子键名 / 值名 / 值数据")
    finder.add_argument("query")
    finder.add_argument("--root", default="HKEY_CURRENT_USER", help="搜索起点")
    finder.add_argument("--scope", choices=VALID_SCOPES, default="both")
    finder.add_argument("--limit", type=int, default=100)
    finder.add_argument("--max-keys", type=int, default=5000)
    finder.add_argument("--seconds", type=float, default=6.0)
    finder.add_argument("--json", action="store_true", help="输出 JSON")
    _add_view(finder)
    finder.set_defaults(func=cmd_search)

    exporter = sub.add_parser("export", help="导出当前键及其子键")
    exporter.add_argument("path")
    exporter.add_argument("--format", choices=FORMATS, default="reg")
    exporter.add_argument("--output", default="", help="输出文件；缺省打印到 stdout")
    exporter.add_argument("--max-keys", type=int, default=2000)
    _add_view(exporter)
    exporter.set_defaults(func=cmd_export)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        # 无子命令：等价于 `serve`，方便一键启动图形界面
        args = parser.parse_args(["serve"] + list(argv or []))
    try:
        return int(args.func(args))
    except (RegistryError, PathError, ValueError, OSError) as exc:
        return _print_error(exc)


if __name__ == "__main__":
    sys.exit(main())
