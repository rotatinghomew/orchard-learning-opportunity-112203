"""查看本地业务资料的记录规模，不产生业务判定。"""
import argparse
from pathlib import Path

from packet import read_packet


def main():
    parser = argparse.ArgumentParser(description="查看演练资料清单")
    parser.add_argument("path", type=Path, nargs="?", default=Path("资料/演练.json"))
    arguments = parser.parse_args()
    try:
        packet = read_packet(arguments.path)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"无法读取资料：{exc}\n")
    for name, value in packet.items():
        kind = "记录" if isinstance(value, list) else "参数"
        print(f"{name}: {len(value)} {kind}")


if __name__ == "__main__":
    main()
