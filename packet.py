"""资料包的读取、合并与时刻工具。仅做结构处理，不产生业务判定。"""
import copy
import json
from pathlib import Path

RECORD_KINDS = ("count", "solo", "assisted", "watch")
ANSWER_KINDS = ("solo", "assisted", "watch")


def parse_time(text):
    """把 HH:MM 形式的当日时刻解析为分钟数。"""
    if not isinstance(text, str) or ":" not in text:
        raise ValueError(f"时刻格式应为 HH:MM：{text!r}")
    hours, minutes = text.split(":", 1)
    if not (hours.isdigit() and minutes.isdigit()):
        raise ValueError(f"时刻格式应为 HH:MM：{text!r}")
    hour, minute = int(hours), int(minutes)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"时刻超出当日范围：{text!r}")
    return hour * 60 + minute


def format_time(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def read_packet(path):
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or any(not isinstance(value, (list, dict)) for value in data.values()):
        raise ValueError("资料包必须是由记录列表或参数对象组成的 JSON 对象")
    return data


def merge_packets(base, extra):
    """把新到资料并入既有资料包。

    列表按键合追加（reviews/proposals 按 id、people 按 person 覆盖同名项，
    其余按内容去重），curriculum 逐键更新。返回新对象，不改入参。
    """
    merged = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, list):
            target = merged.setdefault(key, [])
            if not isinstance(target, list):
                raise ValueError(f"无法合并字段 {key}：类型不一致")
            for item in value:
                if key == "people" and isinstance(item, dict) and "person" in item:
                    target[:] = [row for row in target if row.get("person") != item["person"]]
                    target.append(item)
                elif key in ("reviews", "proposals") and isinstance(item, dict) and "id" in item:
                    target[:] = [row for row in target if row.get("id") != item["id"]]
                    target.append(item)
                elif item not in target:
                    target.append(item)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(copy.deepcopy(value))
        else:
            merged[key] = copy.deepcopy(value)
    return merged
