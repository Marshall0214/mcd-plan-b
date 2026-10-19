from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sys

from .mcp import Client, MCPError, payload
from .planner import InputError, plan, render


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2)
    token = os.environ.get("MCD_MCP_TOKEN")
    if token:
        content = content.replace(token, "[REDACTED]")
    target.write_text(content + "\n", encoding="utf-8")


def cents(value):
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or number * 100 != (number * 100).to_integral_value():
            raise InvalidOperation
        return int(number * 100)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("预算须为非负金额，最多两位小数。") from None


def parser():
    p = argparse.ArgumentParser(description="麦麦补位：保留点餐需求，寻找可解释的 Plan B")
    commands = p.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="无需 Token 的离线演示")
    demo.add_argument("--scenario", choices=["unavailable", "budget", "combo", "impossible"], default="budget")
    demo.add_argument("--json", action="store_true")
    local = commands.add_parser("plan", help="求解标准化候选购物篮")
    local.add_argument("--input", required=True)
    local.add_argument("--json", action="store_true")
    live = commands.add_parser("live", help="只读查询真实门店、餐品与整单报价")
    live.add_argument("--city", required=True)
    live.add_argument("--keyword", required=True)
    live.add_argument("--budget", type=cents, default=3000, metavar="元")
    live.add_argument("--stores", type=int, default=2)
    live.add_argument("--max-quotes", type=int, default=12)
    live.add_argument("--same-store", action="store_true")
    live.add_argument("--main", default="板烧鸡腿堡")
    live.add_argument("--drink", default="无糖可口可乐中杯")
    live.add_argument("--baseline-file", help="已核实历史原单 JSON（store_code、items）；可包含当前下架的餐品")
    live.add_argument("--output", default="private/live-bundle.json")
    live.add_argument("--json", action="store_true")
    mcp = commands.add_parser("mcp", help="发现真实工具 Schema，或执行只读工具")
    operations = mcp.add_subparsers(dest="operation", required=True)
    ts = operations.add_parser("tools")
    ts.add_argument("--output", default="private/tools.json")
    call = operations.add_parser("call")
    call.add_argument("name")
    call.add_argument("--args-file", required=True)
    call.add_argument("--output", required=True, help="原始业务响应可能含个人信息，请保存到 private/")
    return p


def run(args):
    if args.command == "demo":
        from .demo import demo_bundle
        bundle = demo_bundle(args.scenario)
    elif args.command == "plan":
        bundle = read_json(args.input)
    else:
        if args.command == "mcp" and args.operation == "call":
            from .mcp import READ_TOOLS
            if args.name not in READ_TOOLS:
                raise InputError("CLI 不执行创建订单、领券、购卡、兑换、抽奖或取消订单。")
        client = Client()
        client.initialize()
        if args.command == "mcp":
            if args.operation == "tools":
                result = client.tools()
                save_json(args.output, result)
                print(f"已发现 {len(result)} 个工具；Schema 已保存：{args.output}")
            else:
                result = client.call(args.name, read_json(args.args_file))
                save_json(args.output, {"tool": args.name, "response": payload(result)})
                print(f"只读查询结果已保存：{args.output}")
            return 0
        from .live import live_bundle
        bundle = live_bundle(client, city=args.city, keyword=args.keyword, budget_cents=args.budget,
                             store_limit=args.stores, max_quotes=args.max_quotes,
                             allow_store_change=not args.same_store, main_name=args.main, drink_name=args.drink,
                             baseline_input=read_json(args.baseline_file) if args.baseline_file else None,
                             on_progress=lambda name: print("正在查询：" + name, file=sys.stderr))
        save_json(args.output, bundle)
        print("本地查询凭据已保存：" + args.output, file=sys.stderr)
    result = plan(bundle)
    if bundle.get("failures"):
        print(f"有 {len(bundle['failures'])} 次查询未成功，结果仅覆盖成功的候选，详情见本地凭据。", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render(result))
    return 0 if result["status"] == "ok" else 2


def main(argv=None):
    # Consistent Chinese output even in Windows terminals with a legacy encoding.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        return run(args)
    except (InputError, MCPError, KeyError, TypeError, ValueError, OSError) as exc:
        message = str(exc)
        token = os.environ.get("MCD_MCP_TOKEN")
        if token:
            message = message.replace(token, "[REDACTED]")
        print("错误：" + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
