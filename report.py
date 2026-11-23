"""把核对与处置结果渲染为中文报告。"""
from packet import format_time
from solve import (EXCLUDED, NO_RECORD, POSSIBLE, PROVEN, class_map, coverage)
import decide

STATUS_LABEL = {
    PROVEN: "已证明",
    POSSIBLE: "凭证不足（可能）",
    EXCLUDED: "凭证排除",
    NO_RECORD: "无凭证",
}


def _names(ids):
    return "、".join(ids) if ids else "无"


def _fmt(moment):
    return format_time(moment) if moment is not None else "时刻不详"


# ---------- 班后课程证明 ----------

def proof_report(model, result):
    lines = []
    if model.warnings:
        lines.append("== 资料提示 ==")
        for warning in model.warnings:
            lines.append(f"  ！{warning}")
        lines.append("")
    if result.scenarios == 0:
        lines.append("== 计数表核对 ==")
        lines.append("  记录互相矛盾：没有任何一种人选能同时解释全部记录，请复查原始凭证。")
        return "\n".join(lines)

    lines.append("== 计数表核对（仅列出能同时解释全部记录的情形，不补齐名单）==")
    lines.append(f"  全部记录共有 {result.scenarios} 种可同时成立的情形；以下为各情形一致的结论。")
    for index, record in enumerate(result._count_records):
        unit = model.units[record.unit]
        detail = result.count_detail(index)
        head = (f"  {record.unit}（{unit.target}，{_fmt(record.when)}，"
                f"{record.did}/{len(record.people)} 人独立操作）：")
        lines.append(head)
        lines.append(f"    确定独立操作：{_names(detail['forced'])}")
        if detail["possible"]:
            lines.append(f"    其余名额候选（凭证不足，不能断定）：{_names(detail['possible'])}")
        for person, reason in sorted(detail["excluded"].items()):
            lines.append(f"    不计入：{person}（{reason}）")
    watch_records = [r for r in model.records if r.kind == "watch"]
    for record in watch_records:
        unit = model.units[record.unit]
        lines.append(f"  {record.unit}（{unit.target}演示，{_fmt(record.when)}）："
                     f"{len(record.people)} 人观看，不构成独立操作凭证。")
    lines.append("")

    for adjusted in (False, True):
        title = "按名册班别" if not adjusted else "按转组后归属"
        if adjusted and not model.transfers:
            continue
        lines.append(f"== 分母与覆盖（{title}，班别 × 可及性需求）==")
        table = coverage(model, result, adjusted=adjusted)
        needs_label = {"low_counter": "低台需求", "none": "一般需求"}
        for (class_id, needs), cell in sorted(table.items()):
            lines.append(f"  {class_id} 班 · {needs_label.get(needs, needs)}：{len(cell['people'])} 人"
                         f"（{_names(cell['people'])}）")
            for goal in model.goals:
                proven = cell["goals"][goal]["proven"]
                possible = cell["goals"][goal]["possible"]
                line = f"    {goal}：已证明 {len(proven)} 人"
                if proven:
                    line += f"（{_names(proven)}）"
                if possible:
                    line += f"；另有 {len(possible)} 人凭证不足（{_names(possible)}）"
                lines.append(line)
            lines.append(f"    顺序完成全程：{len(cell['chain'])} 人（{_names(cell['chain'])}）")
            repeats = {}
            for person, count in sorted(cell["repeats"].items()):
                repeats.setdefault(count, []).append(person)
            parts = [f"{count} 次 {len(people)} 人（{_names(sorted(people))}）"
                     for count, people in sorted(repeats.items(), reverse=True)]
            lines.append(f"    重复体验（已证明独立操作次数）：{'；'.join(parts)}")
        lines.append("")

    lines.append("== 顺序完成链（同一孩子按先后独立完成全部目标）==")
    completers, partials = [], []
    for person_id in sorted(model.people):
        done, steps, missing = result.chain(person_id)
        if done:
            completers.append((person_id, steps))
        elif steps:
            partials.append((person_id, steps, missing))
    for person_id, steps in completers:
        path = " → ".join(f"{goal}（{unit} {_fmt(moment)}）" for goal, unit, moment in steps)
        lines.append(f"  {person_id}：全程证明 ✓  {path}")
    for person_id, steps, missing in partials:
        path = " → ".join(f"{goal}（{unit}）" for goal, unit, _ in steps)
        lines.append(f"  {person_id}：仅证明到 {path}；缺 {'、'.join(missing)}")
    lines.append("  注：分选、测量各自覆盖人数不等于同一批孩子走完了两段；"
                 "无凭证或凭证不足不等于缺席。")
    lines.append("")

    if model.transfers:
        lines.append("== 转组凭证（收到时间；迟知不倒改之前对外通知）==")
        classes = class_map(model)
        for transfer in sorted(model.transfers, key=lambda item: item.known):
            lines.append(f"  {transfer.person}：{transfer.from_group}→{transfer.to_group}，"
                         f"{_fmt(transfer.known)} 收到（名册班别 {classes[transfer.person]}）")
            seen_units = set()
            for record in model.records:
                if transfer.person in record.people and record.unit not in seen_units:
                    seen_units.add(record.unit)
                    status, reason, _ = result.unit_status(transfer.person, record.unit)
                    lines.append(f"    出现于 {record.unit}：{STATUS_LABEL[status]}（{reason}）")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------- 当天处置 ----------

def plan_report(model, now, cache=None):
    if cache is None:
        cache = {}
    lines = [f"== 工位与席位（截至 {_fmt(now)}）=="]
    seen_groups = set()
    for unit_id in sorted(model.units, key=lambda u: (model.window(u), u)):
        ids, capacity = model.capacity_group(unit_id)
        key = tuple(sorted(ids))
        if key in seen_groups:
            continue
        seen_groups.add(key)
        unit = model.units[unit_id]
        notices = [n for n in model.notices
                   if n.status == "confirmed" and n.known <= now and n.unit in ids]
        shared = f"（{'、'.join(sorted(ids))} 共用，容量取小）" if len(ids) > 1 else ""
        lines.append(f"  工位 {unit.station}·时段 {unit.slot}{shared}：容量 {capacity}，"
                     f"通知占 {len(notices)}（{_names(sorted(n.person for n in notices))}），"
                     f"空 {capacity - len(notices)}；开场 {_fmt(model.window(unit_id))}")
    lines.append("")

    lines.append("== 通知核对（凭当时已知凭证）==")
    if not model.notices:
        lines.append("  无通知记录。")
    for notice in sorted(model.notices, key=lambda n: n.known):
        ok, items = decide.notice_basis(model, notice, cache)
        verdict = "有据" if ok else "依据不足"
        lines.append(f"  {notice.person} ← {notice.unit}（{_fmt(notice.known)} 确认）：{verdict}")
        for item in items:
            lines.append(f"    - {item}")
    lines.append("")

    lines.append("== 候补处置 ==")
    evaluations = []
    for proposal in sorted(model.proposals, key=lambda p: (p.submitted, p.id)):
        outcome = decide.evaluate_proposal(model, proposal, now, cache)
        evaluations.append(outcome)
        lines.extend(_proposal_lines(model, proposal, outcome, now))
    if not model.proposals:
        lines.append("  无候补。")
    lines.append("")

    sharing = decide.sharing(model, now)
    if sharing:
        lines.append("== 待回单候补的席位共用 ==")
        for group in sharing:
            lines.append(f"  工位 {'、'.join(group['units'])}：待回单候补 {_names(group['proposals'])}，"
                         f"空位 {group['free_seats']}")
            for first, second in group["exclusive_pairs"]:
                lines.append(f"    {first} 与 {second} 依据同一份核对单的不同回答，"
                             f"确实不会一起生效，可共用一席。")
            if group["guaranteed"]:
                lines.append(f"    最多同时生效 {group['max_simultaneous']} 份 ≤ 空位，可以全部接纳。")
            else:
                lines.append(f"    最多可能同时生效 {group['max_simultaneous']} 份 > 空位 "
                             f"{group['free_seats']}：即使总座位够也无法全部保证，发通知前需定夺。")
        lines.append("")

    conflicts = decide.seat_conflicts(model, evaluations, now)
    if conflicts:
        lines.append("== 席位竞争提示 ==")
        for conflict in conflicts:
            lines.append(f"  工位 {'、'.join(conflict['units'])}：候补 {_names(conflict['proposals'])} "
                         f"均可确认，但空位仅 {conflict['free_seats']}，需老师定夺；"
                         f"已通知的机会不受影响。")
        lines.append("")
    return "\n".join(lines).rstrip()


def _proposal_lines(model, proposal, outcome, now):
    cond = ""
    if proposal.review is not None:
        cond = f"，条件 {proposal.review}={proposal.answer}"
    head = f"  {proposal.id}：{proposal.person} ← {proposal.unit}（{_fmt(proposal.submitted)} 提交{cond}）"
    code = outcome["code"]
    lines = [head]
    if code == decide.NOTIFIED:
        lines.append(f"    已通知（{_fmt(outcome['since'])}）。")
    elif code == decide.CONDITION_FAILED:
        reply = outcome["reply"]
        lines.append(f"    条件不成立：{_fmt(outcome['since'])} 回单为 {reply.kind}。")
    elif code == decide.WAITING:
        due = outcome["due"]
        suffix = "；已过承诺回单时间，仍无回单——这不等于否定答复，不能按否定分支把位置给出去" \
            if now > due else ""
        lines.append(f"    待回单（承诺 {_fmt(due)} 前返回）{suffix}。")
    elif code == decide.EXPIRED_PENDING:
        lines.append(f"    {proposal.unit} 已开场（{_fmt(outcome['window'])}），回单仍未到，候补未生效。")
    elif code == decide.CONFIRMABLE:
        lines.append(f"    现在就可以给：自 {_fmt(outcome['since'])} 起条件、前置与空位均具备，"
                     f"开场 {_fmt(outcome['window'])} 前可确认。")
    elif code == decide.CONFIRMABLE_NOW:
        lines.append(f"    现在可以确认（此前因 {'；'.join(outcome['earlier_reasons'])} 不可）。")
    elif code == decide.MISSED_UNNOTIFIED:
        lines.append(f"    本可于 {_fmt(outcome['since'])} 确认（条件、前置、空位当时均具备），"
                     f"但未见通知记录；{proposal.unit} 已开场，不能倒填。")
    elif code == decide.CONDITION_LATE:
        lines.append(f"    条件 {_fmt(outcome['ready_at'])} 才成立，已错过 {proposal.unit} "
                     f"开场（{_fmt(outcome['window'])}）。")
        lines.extend(_reroute_lines(model, outcome["reroute"]))
    elif code == decide.BLOCKED:
        lines.append(f"    暂不可确认：{'；'.join(outcome['reasons'])}。")
    elif code == decide.EXPIRED_BLOCKED:
        lines.append(f"    直至开场仍不可确认：{'；'.join(outcome['reasons'])}。")
    return lines


def _reroute_lines(model, reroute):
    lines = []
    for entry in reroute["later"]:
        if entry["ok"]:
            lines.append(f"    可改派后续工位 {entry['unit']}（{_fmt(entry['window'])} 开场）："
                         f"前置与工位均已满足。")
        else:
            lines.append(f"    后续工位 {entry['unit']}（{_fmt(entry['window'])} 开场）不可用："
                         f"{'；'.join(entry['reasons'])}。")
    for entry in reroute["alternative"]:
        state = "可用" if entry["ok"] else f"不可用（{'；'.join(entry['reasons'])}）"
        lines.append(f"    替换单元 {entry['unit']}（目标不同，{_fmt(entry['window'])} 开场）：{state}。")
    if reroute["closed"]:
        lines.append(f"    替换范围 {_names(reroute['closed'])} 已开场，不可再约。")
    return lines


# ---------- 个人查询 ----------

def child_report(model, result, person, now, cache=None):
    if cache is None:
        cache = {}
    if person not in model.people:
        raise ValueError(f"名册中没有匿名号：{person}")
    row = model.people[person]
    classes = class_map(model, adjusted=True)
    needs_label = {"low_counter": "低台需求", "none": "一般需求"}.get(row.needs, row.needs)
    lines = [f"== {person}（名册 {row.class_id} 班，{needs_label}）=="]
    if classes[person] != row.class_id:
        lines.append(f"  转组后归属：{classes[person]} 班")
    lines.append("")

    lines.append("  【当天通知过什么】")
    notices = [n for n in model.notices if n.person == person]
    if not notices:
        lines.append("    无通知记录。")
    for notice in sorted(notices, key=lambda n: n.known):
        lines.append(f"    {_fmt(notice.known)} 确认 {notice.unit}（{notice.status}）")
    proposals = [p for p in model.proposals if p.person == person]
    for proposal in sorted(proposals, key=lambda p: p.submitted):
        outcome = decide.evaluate_proposal(model, proposal, now, cache)
        cond = f"，条件 {proposal.review}={proposal.answer}" if proposal.review else ""
        lines.append(f"    候补 {proposal.id} ← {proposal.unit}（{_fmt(proposal.submitted)} 提交{cond}）："
                     f"{_code_label(outcome)}")
    lines.append("")

    lines.append("  【凭什么给过机会（依据以当时已知为准）】")
    if not notices and not proposals:
        lines.append("    当天没有给过可核对的承诺。")
    for notice in sorted(notices, key=lambda n: n.known):
        ok, items = decide.notice_basis(model, notice, cache)
        lines.append(f"    {notice.unit} 通知（{_fmt(notice.known)}）：{'有据' if ok else '依据不足'}")
        for item in items:
            lines.append(f"      - {item}")
    for proposal in sorted(proposals, key=lambda p: p.submitted):
        if proposal.review is not None:
            review = model.reviews[proposal.review]
            lines.append(f"    候补 {proposal.id} 以核对单 {proposal.review} 的回单 "
                         f"{proposal.answer} 为启动条件（承诺 {_fmt(review.due)} 前返回）。")
    lines.append("")

    lines.append("  【班后能证明独立完成了什么】")
    any_evidence = False
    unproven = []
    for goal in model.goals:
        status, evidence = result.goal_status(person, goal)
        if status != PROVEN:
            unproven.append(goal)
        lines.append(f"    {goal}：{STATUS_LABEL[status]}")
        for unit_id, unit_status, reason, when in evidence:
            lines.append(f"      - {unit_id}（{_fmt(when)}）：{reason}")
            any_evidence = True
    if not any_evidence:
        lines.append("    没有任何操作凭证。")
    if unproven:
        lines.append(f"    {'、'.join(unproven)} 未能证明——凭证不足或没有凭证不等于缺席。")
    done, steps, missing = result.chain(person)
    if done:
        path = " → ".join(f"{goal}（{unit} {_fmt(moment)}）" for goal, unit, moment in steps)
        lines.append(f"    顺序完成全程 ✓：{path}")
    else:
        lines.append(f"    顺序完成全程 ✗：缺 {'、'.join(missing)}")
    lines.append("")
    lines.append("  说明：预约与通知不是完成证明；班后证明只依据操作记录与回单，"
                 "后来补到的资料可以更正证明，但不会让当时无法保证的承诺变成早就成立。")
    return "\n".join(lines)


def _code_label(outcome):
    code = outcome["code"]
    if code == decide.NOTIFIED:
        return f"已通知（{_fmt(outcome['since'])}）"
    if code == decide.CONFIRMABLE:
        return "现在就可以给（开场前可确认）"
    if code == decide.CONFIRMABLE_NOW:
        return "现在可以确认"
    if code == decide.MISSED_UNNOTIFIED:
        return "本可确认但未通知，现已过开场"
    if code == decide.CONDITION_FAILED:
        return f"条件不成立（{_fmt(outcome['condition_time'])} 回单不符）"
    if code == decide.CONDITION_LATE:
        return "条件成立时已错过开场，需另找后续工位"
    if code == decide.WAITING:
        return "待回单"
    if code == decide.EXPIRED_PENDING:
        return "已开场，回单未到，候补未生效"
    if code == decide.BLOCKED:
        return "暂不可确认"
    if code == decide.EXPIRED_BLOCKED:
        return "直至开场仍不可确认"
    raise ValueError(f"未知处置结论：{code}")


# ---------- 新到资料 ----------

def merge_report(base_model, base_result, merged_model, merged_result, now, cache=None):
    if cache is None:
        cache = {}
    lines = ["== 新到资料引起的证明变化 =="]
    changes = 0
    for person in sorted(merged_model.people):
        for goal in merged_model.goals:
            before, _ = base_result.goal_status(person, goal)
            after, _ = merged_result.goal_status(person, goal)
            if before != after:
                changes += 1
                lines.append(f"  {person} {goal}：{STATUS_LABEL[before]} → {STATUS_LABEL[after]}")
        before_chain = base_result.chain(person)[0]
        after_chain = merged_result.chain(person)[0]
        if before_chain != after_chain:
            changes += 1
            state = "全程证明 ✓" if after_chain else "不再成立"
            lines.append(f"  {person} 顺序完成全程：{state}")
    if not changes:
        lines.append("  证明结论无变化。")
    lines.append("")

    lines.append("== 候补处置变化 ==")
    proposal_changes = 0
    base_props = {p.id: p for p in base_model.proposals}
    for proposal in sorted(merged_model.proposals, key=lambda p: p.id):
        after = decide.evaluate_proposal(merged_model, proposal, now, cache)
        if proposal.id in base_props:
            before = decide.evaluate_proposal(base_model, base_props[proposal.id], now, cache)
            if before["code"] != after["code"]:
                proposal_changes += 1
                lines.append(f"  {proposal.id}：{_code_label(before)} → {_code_label(after)}")
        else:
            proposal_changes += 1
            lines.append(f"  {proposal.id}（新候补）：{_code_label(after)}")
    if not proposal_changes:
        lines.append("  候补处置无变化。")
    lines.append("")
    lines.append("说明：已发出的通知与其依据按当时已知凭证核定，不受新到资料影响；"
                 "开场后补到的资料只更正班后证明，不倒填当时的分配。")
    return "\n".join(lines)
