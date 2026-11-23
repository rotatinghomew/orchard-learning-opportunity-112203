"""研学操作凭证与预约席位：班后课程证明与当天处置。

用法：
    python3 main.py [资料包]                  输出班后证明与当天处置总览
    python3 main.py [资料包] proof            仅班后课程证明
    python3 main.py [资料包] plan [--at HH:MM]  仅当天处置（可指定判定时刻）
    python3 main.py [资料包] child 匿名号      个人：通知、依据、班后证明分列
    python3 main.py [资料包] merge 新到资料    并入新到资料，列出证明与候补变化
"""
import argparse
import sys
from pathlib import Path

from model import build_model
from packet import format_time, merge_packets, parse_time, read_packet
from report import child_report, merge_report, plan_report, proof_report
from solve import solve

DEFAULT_PACKET = Path("资料/演练.json")


def _load(path):
    try:
        doc = read_packet(path)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"无法读取资料：{exc}")
    try:
        return doc, build_model(doc)
    except ValueError as exc:
        raise SystemExit(f"资料不符合约定：{exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("packet", type=Path, nargs="?", default=DEFAULT_PACKET, help="资料包路径")
    parser.add_argument("command", nargs="?", default="report",
                        choices=("report", "proof", "plan", "child", "merge"), help="要输出的内容")
    parser.add_argument("target", nargs="?", help="child 的匿名号或 merge 的新到资料路径")
    parser.add_argument("--at", dest="at", default=None, help="处置判定时刻（HH:MM），默认资料中最晚时刻")
    arguments = parser.parse_args(argv)

    doc, model = _load(arguments.packet)
    now = parse_time(arguments.at) if arguments.at else model.latest_time()

    if arguments.command == "child":
        if not arguments.target:
            parser.exit(2, "child 需要指定匿名号\n")
        try:
            print(child_report(model, solve(model), arguments.target, now))
        except ValueError as exc:
            parser.exit(2, f"{exc}\n")
        return
    if arguments.command == "merge":
        if not arguments.target:
            parser.exit(2, "merge 需要指定新到资料路径\n")
        try:
            extra = read_packet(arguments.target)
        except (OSError, ValueError) as exc:
            parser.exit(2, f"无法读取新到资料：{exc}\n")
        merged_model = _load_from_doc(merge_packets(doc, extra), arguments.packet)
        print(merge_report(model, solve(model), merged_model, solve(merged_model), now))
        return
    if arguments.command in ("report", "proof"):
        print(proof_report(model, solve(model)))
        if arguments.command == "proof":
            return
        print()
    if arguments.command in ("report", "plan"):
        print(plan_report(model, now))


def _load_from_doc(doc, source):
    try:
        return build_model(doc)
    except ValueError as exc:
        raise SystemExit(f"合并后的资料不符合约定（{source}）：{exc}")


if __name__ == "__main__":
    main()
