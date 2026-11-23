"""当天处置：席位、候补生效条件、通知依据与改派。

判定只使用"当时已知"的凭证（记录时刻、回单收到时刻、通知确认时刻
均不晚于判定时刻），开场后到的资料不会倒填当时的分配。按期无回单
不等于收到否定答复，不能按否定分支把位置给出去。
"""
from collections import Counter, defaultdict
from itertools import combinations

from packet import format_time
from solve import PROVEN, solve_cached

# 候补处置结论代码
NOTIFIED = "notified"                    # 已发通知
CONFIRMABLE = "confirmable"              # 现在仍可确认（开场前）
CONFIRMABLE_NOW = "confirmable_now"      # 此前不行，现在可以确认
MISSED_UNNOTIFIED = "missed_unnotified"  # 本可确认但未通知，现已过开场
CONDITION_FAILED = "condition_failed"    # 回单已到，条件不成立
CONDITION_LATE = "condition_late"        # 条件成立时已错过开场
WAITING = "waiting"                      # 待回单（未到期或到期无回单，均非否定）
EXPIRED_PENDING = "expired_pending"      # 已开场，回单仍未到
BLOCKED = "blocked"                      # 条件满足但席位/前置/工位不满足
EXPIRED_BLOCKED = "expired_blocked"      # 直至开场仍不满足


def free_seats(model, unit_id, moment):
    """该单元所在工位（同 station+slot，容量取小）在 moment 时刻的空位。"""
    ids, capacity = model.capacity_group(unit_id)
    taken = sum(1 for notice in model.notices
                if notice.status == "confirmed" and notice.known <= moment and notice.unit in ids)
    return capacity - taken


def condition_state(model, proposal, now):
    """候补启动条件：返回 (none/pending/true/false, 时刻, 回单)。"""
    if proposal.review is None:
        return ("none", None, None)
    replies = [conf for conf in model.confirmations
               if conf.review == proposal.review and conf.known <= now]
    if not replies:
        return ("pending", None, None)
    first = min(replies, key=lambda conf: conf.known)
    return ("true" if first.kind == proposal.answer else "false", first.known, first)


def eligibility(model, person, unit_id, moment, cache):
    """在 moment 时刻能否把该单元操作位给这个人：返回 (可否, 原因列表)。"""
    reasons = []
    person_row = model.people[person]
    unit = model.units[unit_id]
    if person_row.needs == "low_counter" and not unit.accessible:
        reasons.append("低台需求不适用该工位")
    if unit.prereq:
        status, _ = solve_cached(model, moment, cache).goal_status(person, unit.prereq)
        if status != PROVEN:
            reasons.append(f"前置 {unit.prereq} 当时未证明（{status}）")
    if free_seats(model, unit_id, moment) < 1:
        reasons.append("此时段工位已无空位")
    return (not reasons, reasons)


def evaluate_proposal(model, proposal, now, cache=None):
    """评估一份候补在 now 时刻的处置结论。"""
    if cache is None:
        cache = {}
    window = model.window(proposal.unit)
    notice = next((n for n in model.notices
                   if n.person == proposal.person and n.unit == proposal.unit
                   and n.status == "confirmed"), None)
    cond, cond_time, reply = condition_state(model, proposal, now)
    result = {
        "id": proposal.id, "person": proposal.person, "unit": proposal.unit,
        "submitted": proposal.submitted, "window": window,
        "condition": cond, "condition_time": cond_time, "reply": reply,
        "notice": notice, "code": None,
    }
    if notice is not None:
        result.update(code=NOTIFIED, since=notice.known)
        return result
    if cond == "false":
        result.update(code=CONDITION_FAILED, since=cond_time)
        return result
    if cond == "pending":
        result["due"] = model.reviews[proposal.review].due
        result.update(code=WAITING if now < window else EXPIRED_PENDING)
        return result
    ready = max(proposal.submitted, cond_time if cond_time is not None else proposal.submitted)
    result["ready_at"] = ready
    if ready >= window:
        result.update(code=CONDITION_LATE)
        result["reroute"] = reroute(model, proposal, ready, cache)
        return result
    ok, reasons = eligibility(model, proposal.person, proposal.unit, ready, cache)
    if ok:
        result.update(code=CONFIRMABLE if now < window else MISSED_UNNOTIFIED, since=ready)
        return result
    if now < window:
        ok_now, reasons_now = eligibility(model, proposal.person, proposal.unit, now, cache)
        if ok_now:
            result.update(code=CONFIRMABLE_NOW, since=now, earlier_reasons=reasons)
            return result
        result.update(code=BLOCKED, reasons=reasons)
    else:
        result.update(code=EXPIRED_BLOCKED, reasons=reasons)
    return result


def reroute(model, proposal, moment, cache):
    """条件成立但原单元已开场：列出仍可预约的后续工位与已关闭的替换范围。"""
    target = model.units[proposal.unit].target
    replacements = set(model.replace.get(proposal.unit, ()))
    later, alternative, closed = [], [], []
    for unit_id, unit in model.units.items():
        if unit_id == proposal.unit:
            continue
        if model.window(unit_id) <= moment:
            if unit_id in replacements:
                closed.append(unit_id)
            continue
        ok, reasons = eligibility(model, proposal.person, unit_id, moment, cache)
        entry = {"unit": unit_id, "window": model.window(unit_id), "ok": ok,
                 "reasons": reasons, "same_target": unit.target == target,
                 "replacement": unit_id in replacements}
        if unit.target == target:
            later.append(entry)
        elif unit_id in replacements:
            alternative.append(entry)
    later.sort(key=lambda item: item["window"])
    alternative.sort(key=lambda item: item["window"])
    return {"later": later, "alternative": alternative, "closed": sorted(closed)}


def sharing(model, now):
    """待回单候补的席位共用分析。

    两份候补只有根据已知凭证和登记的核对内容确实不会一起生效才可共用：
    同一份核对单只回一份回单，因此同一核对单的不同回答互斥。
    """
    pending = [p for p in model.proposals
               if p.review is not None and now < model.window(p.unit)
               and condition_state(model, p, now)[0] == "pending"]
    groups = defaultdict(list)
    for proposal in pending:
        groups[model.capacity_group(proposal.unit)[0]].append(proposal)
    report = []
    for ids, props in sorted(groups.items(), key=lambda item: sorted(item[0])):
        exclusive = [(a.id, b.id) for a, b in combinations(props, 2)
                     if a.review == b.review and a.answer != b.answer]
        by_review = defaultdict(Counter)
        for proposal in props:
            by_review[proposal.review][proposal.answer] += 1
        max_simultaneous = sum(max(answers.values()) for answers in by_review.values())
        seats = free_seats(model, props[0].unit, now)
        report.append({
            "units": sorted(ids),
            "proposals": [p.id for p in props],
            "exclusive_pairs": exclusive,
            "max_simultaneous": max_simultaneous,
            "free_seats": seats,
            "guaranteed": max_simultaneous <= seats,
        })
    return report


def seat_conflicts(model, evaluations, now):
    """多份"可确认"候补竞争同一工位空位时给出提示。"""
    ready = [item for item in evaluations
             if item["code"] in (CONFIRMABLE, CONFIRMABLE_NOW)]
    groups = defaultdict(list)
    for item in ready:
        groups[model.capacity_group(item["unit"])[0]].append(item)
    conflicts = []
    for ids, items in groups.items():
        seats = free_seats(model, items[0]["unit"], now)
        if len(items) > seats:
            conflicts.append({"units": sorted(ids), "proposals": [i["id"] for i in items],
                              "free_seats": seats})
    return conflicts


def notice_basis(model, notice, cache=None):
    """核对一张通知在发出时刻的依据：返回 (是否有据, 依据条目)。"""
    if cache is None:
        cache = {}
    moment = notice.known
    unit = model.units[notice.unit]
    person = model.people[notice.person]
    items, ok = [], True
    if person.needs == "low_counter" and not unit.accessible:
        ok = False
        items.append("低台需求不适用该工位")
    if unit.prereq:
        status, evidence = solve_cached(model, moment, cache).goal_status(notice.person, unit.prereq)
        if status == PROVEN:
            proven = [row for row in evidence if row[1] == PROVEN]
            unit_id, _, reason, when = proven[0]
            stamp = format_time(when) if when is not None else "时刻不详"
            items.append(f"前置 {unit.prereq} 当时已证明：{unit_id}（{reason}，{stamp}）")
        else:
            ok = False
            items.append(f"前置 {unit.prereq} 当时未证明（{status}）")
    ids, capacity = model.capacity_group(notice.unit)
    others = sum(1 for n in model.notices
                 if n is not notice and n.status == "confirmed"
                 and n.known <= moment and n.unit in ids)
    if capacity - others < 1:
        ok = False
        items.append("通知时该时段工位已无空位")
    else:
        items.append(f"通知时该时段工位尚有空位（余 {capacity - others}）")
    if moment >= model.window(notice.unit):
        ok = False
        items.append("通知不早于开场时刻")
    return ok, items
