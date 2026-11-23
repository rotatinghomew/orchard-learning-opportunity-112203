"""核对记录：枚举能同时解释全部记录的情形，给出每个孩子的证明状态。

计数表只说"恰有 did 人独立操作"，个人记录与回单可以缩小候选范围，
不能另外加一次。同一人在同一时段只能在一个操作位；低台需求的孩子
不适用 accessible=false 的工位。满足全部约束的每一种人选组合是一个
"情形"；只有被所有情形共同锁定的结论才作为证明输出，不自行补齐名单。
"""
from collections import Counter
from itertools import combinations

PROVEN = "proven"        # 所有情形都成立（或有直接凭证）
POSSIBLE = "possible"    # 部分情形成立，现有凭证不能确定
EXCLUDED = "excluded"    # 凭证或约束排除了独立操作
NO_RECORD = "no_record"  # 没有任何凭证（不等于缺席）

REASON_SOLO = "个人记录：独立操作"
REASON_CONF_SOLO = "回单确认：独立操作"
REASON_COUNT_FORCED = "计数表与互证记录共同锁定"
REASON_COUNT_POSSIBLE = "计数表候选之一，现有凭证不能确定"
REASON_ASSISTED = "凭证为由同伴代操作"
REASON_WATCH = "凭证为观看演示"
REASON_ACCESS = "低台需求不适用该工位"
REASON_SLOT = "同时段已在其他工位独立操作"
REASON_ARITH = "计数表人数约束下不可能"
REASON_NONE = "无任何凭证"

_STATUS_RANK = {PROVEN: 3, POSSIBLE: 2, EXCLUDED: 1, NO_RECORD: 0}


class SolveResult:
    def __init__(self, model, cutoff=None):
        self.model = model
        self.cutoff = cutoff
        self._pins_in = {unit_id: {} for unit_id in model.units}   # person -> (reason, when)
        self._pins_out = {unit_id: {} for unit_id in model.units}  # person -> reason
        self._count_records = []
        self._collect_pins()
        self.scenarios = 0
        self._forced = {}     # 记录序号 -> set(person)：所有情形都含
        self._possible = {}   # 记录序号 -> set(person)：部分情形含
        self._excluded = {}   # 记录序号 -> {person: reason}
        self._enumerate()
        self._unit_cache = {}
        self._goal_cache = {}

    # ---------- 收集个人凭证 ----------

    def _collect_pins(self):
        model = self.model
        for record in model.records:
            if self.cutoff is not None and record.when > self.cutoff:
                continue
            if record.kind == "solo":
                for person in record.people:
                    self._pins_in[record.unit][person] = (REASON_SOLO, record.when)
            elif record.kind in ("assisted", "watch"):
                reason = REASON_ASSISTED if record.kind == "assisted" else REASON_WATCH
                for person in record.people:
                    self._pins_out[record.unit][person] = (reason, record.when)
            else:
                self._count_records.append(record)
        for conf in model.confirmations:
            if self.cutoff is not None and conf.known > self.cutoff:
                continue
            if conf.kind == "solo":
                when = self._session_time(conf.unit)
                self._pins_in[conf.unit][conf.person] = (REASON_CONF_SOLO, when)
            elif conf.kind in ("assisted", "watch"):
                reason = REASON_ASSISTED if conf.kind == "assisted" else REASON_WATCH
                self._pins_out[conf.unit][conf.person] = (reason, self._session_time(conf.unit))

    def _session_time(self, unit_id):
        """回单所指操作发生的时刻：有同时段计数表用其时刻，否则用开场时刻。"""
        for record in self._count_records:
            if record.unit == unit_id:
                return record.when
        return self.model.window(unit_id)

    # ---------- 枚举情形 ----------

    def _enumerate(self):
        model = self.model
        records = self._count_records
        options = []
        for index, record in enumerate(records):
            unit = model.units[record.unit]
            must, excluded, free = set(), {}, []
            for person in record.people:
                if person in self._pins_in[record.unit]:
                    must.add(person)
                elif person in self._pins_out[record.unit]:
                    excluded[person] = self._pins_out[record.unit][person][0]
                elif (model.people[person].needs == "low_counter" and not unit.accessible):
                    excluded[person] = REASON_ACCESS
                else:
                    free.append(person)
            need = record.did - len(must)
            if need < 0 or need > len(free):
                combos = []
            else:
                combos = [frozenset(must | set(picked)) for picked in combinations(free, need)]
            options.append((must, excluded, free, combos))

        # 同一人在同一时段只能在一个操作位：先放入个人独立记录，再排计数表
        seed = {}
        for unit_id, pins in self._pins_in.items():
            slot = model.units[unit_id].slot
            for person in pins:
                occupant = seed.setdefault(slot, {}).get(person)
                if occupant is not None and occupant != unit_id:
                    self.scenarios = 0
                    for index in range(len(records)):
                        self._forced[index], self._possible[index], self._excluded[index] = set(), set(), {}
                    return
                seed[slot][person] = unit_id

        order = sorted(range(len(records)), key=lambda i: len(options[i][3]))
        chosen = [None] * len(records)
        count_in = [Counter() for _ in records]
        total = 0

        def backtrack(k, assigned):
            nonlocal total
            if k == len(order):
                total += 1
                for i, combo in enumerate(chosen):
                    if combo:
                        for person in combo:
                            count_in[i][person] += 1
                return
            i = order[k]
            slot = model.units[records[i].unit].slot
            for combo in options[i][3]:
                placed = []
                ok = True
                for person in combo:
                    occupant = assigned.get(slot, {}).get(person)
                    if occupant is not None and occupant != records[i].unit:
                        ok = False
                        break
                if not ok:
                    continue
                chosen[i] = combo
                slot_map = assigned.setdefault(slot, {})
                for person in combo:
                    if person not in slot_map:
                        slot_map[person] = records[i].unit
                        placed.append(person)
                backtrack(k + 1, assigned)
                for person in placed:
                    del slot_map[person]
                chosen[i] = None

        backtrack(0, {slot: dict(members) for slot, members in seed.items()})
        self.scenarios = total

        for index, record in enumerate(records):
            must, excluded, free, combos = options[index]
            forced, possible, excl = set(must), set(), dict(excluded)
            for person in free:
                hits = count_in[index].get(person, 0)
                if total and hits == total:
                    forced.add(person)
                elif hits:
                    possible.add(person)
                else:
                    excl[person] = self._exclusion_reason(record, person)
            self._forced[index] = forced
            self._possible[index] = possible
            self._excluded[index] = excl

    def _exclusion_reason(self, record, person):
        model = self.model
        slot = model.units[record.unit].slot
        if person in self._pins_in.get(record.unit, {}):
            return REASON_ARITH
        for unit_id, pins in self._pins_in.items():
            if unit_id != record.unit and model.units[unit_id].slot == slot and person in pins:
                return REASON_SLOT
        for index, other in enumerate(self._count_records):
            if other.unit != record.unit and model.units[other.unit].slot == slot \
                    and person in self._forced.get(index, ()):
                return REASON_SLOT
        return REASON_ARITH

    # ---------- 查询 ----------

    def unit_status(self, person, unit_id):
        """返回 (状态, 原因, 凭证时刻或 None)。"""
        key = (person, unit_id)
        if key in self._unit_cache:
            return self._unit_cache[key]
        model = self.model
        result = None
        if person in self._pins_in.get(unit_id, {}):
            reason, when = self._pins_in[unit_id][person]
            result = (PROVEN, reason, when)
        if result is None:
            for index, record in enumerate(self._count_records):
                if record.unit != unit_id or person not in record.people:
                    continue
                if person in self._forced[index]:
                    result = (PROVEN, REASON_COUNT_FORCED, record.when)
                    break
                if person in self._possible[index]:
                    result = (POSSIBLE, REASON_COUNT_POSSIBLE, None)
                    break
        if result is None and person in self._pins_out.get(unit_id, {}):
            reason, when = self._pins_out[unit_id][person]
            result = (EXCLUDED, reason, when)
        if result is None:
            for index, record in enumerate(self._count_records):
                if record.unit == unit_id and person in self._excluded[index]:
                    result = (EXCLUDED, self._excluded[index][person], None)
                    break
        if result is None:
            result = (NO_RECORD, REASON_NONE, None)
        self._unit_cache[key] = result
        return result

    def goal_status(self, person, goal):
        """返回 (状态, [(单元, 状态, 原因, 时刻), ...])。"""
        key = (person, goal)
        if key in self._goal_cache:
            return self._goal_cache[key]
        evidence = []
        for unit_id, unit in self.model.units.items():
            if unit.target != goal:
                continue
            status, reason, when = self.unit_status(person, unit_id)
            if status != NO_RECORD:
                evidence.append((unit_id, status, reason, when))
        best = NO_RECORD
        for _, status, _, _ in evidence:
            if _STATUS_RANK[status] > _STATUS_RANK[best]:
                best = status
        self._goal_cache[key] = (best, evidence)
        return self._goal_cache[key]

    def proven_units(self, person):
        """该孩子有独立操作证明的单元：[(单元, 时刻)]，按时段与时刻排序。"""
        found = []
        for unit_id in self.model.units:
            status, _, when = self.unit_status(person, unit_id)
            if status == PROVEN:
                unit = self.model.units[unit_id]
                found.append((unit_id, unit.slot, when if when is not None else self.model.window(unit_id)))
        found.sort(key=lambda item: (item[1], item[2]))
        return [(unit_id, when) for unit_id, _, when in found]

    def chain(self, person):
        """按课程目标顺序核对同人独立完成链。

        返回 (是否全程证明, [(目标, 单元, 时刻)], [缺失目标])。
        每个目标要求 min_independent_each 份证明，且严格按 (时段, 时刻) 递增。
        """
        need = self.model.min_independent_each
        steps, missing = [], []
        previous = (-1, -1)
        for goal in self.model.goals:
            candidates = []
            for unit_id, unit in self.model.units.items():
                if unit.target != goal:
                    continue
                status, _, when = self.unit_status(person, unit_id)
                if status != PROVEN:
                    continue
                moment = when if when is not None else self.model.window(unit_id)
                if (unit.slot, moment) > previous:
                    candidates.append((unit.slot, moment, unit_id))
            candidates.sort()
            if len(candidates) < need:
                missing.append(goal)
                continue
            picked = candidates[:need]
            for _, moment, unit_id in picked:
                steps.append((goal, unit_id, moment))
            previous = (picked[-1][0], picked[-1][1])
        return (not missing, steps, missing)

    def count_detail(self, record_index):
        """某张计数表的核对结果：确定人选、被排除者（含原因）、待定候选。"""
        record = self._count_records[record_index]
        return {
            "record": record,
            "forced": sorted(self._forced[record_index]),
            "possible": sorted(self._possible[record_index]),
            "excluded": dict(self._excluded[record_index]),
        }


def solve(model, cutoff=None):
    return SolveResult(model, cutoff)


def solve_cached(model, cutoff, cache):
    key = cutoff
    if key not in cache:
        cache[key] = SolveResult(model, cutoff)
    return cache[key]


# ---------- 汇总（分母、覆盖、重复体验） ----------

def class_map(model, adjusted=False):
    """每个匿名号归属的班别。adjusted=True 时按转组凭证（以收到时间为准）调整。"""
    result = {person_id: person.class_id for person_id, person in model.people.items()}
    if adjusted:
        for transfer in sorted(model.transfers, key=lambda item: item.known):
            result[transfer.person] = transfer.to_group
    return result


def coverage(model, result, adjusted=False):
    """按班别 × 可及性需求汇总分母、覆盖、顺序完成与重复体验。"""
    classes = class_map(model, adjusted=adjusted)
    table = {}
    for person_id, class_id in classes.items():
        needs = model.people[person_id].needs
        cell = table.setdefault((class_id, needs), {
            "people": [],
            "goals": {goal: {"proven": [], "possible": []} for goal in model.goals},
            "chain": [],
            "repeats": {},
        })
        cell["people"].append(person_id)
        for goal in model.goals:
            status, _ = result.goal_status(person_id, goal)
            if status == PROVEN:
                cell["goals"][goal]["proven"].append(person_id)
            elif status == POSSIBLE:
                cell["goals"][goal]["possible"].append(person_id)
        done, _, _ = result.chain(person_id)
        if done:
            cell["chain"].append(person_id)
        cell["repeats"][person_id] = len(result.proven_units(person_id))
    for cell in table.values():
        cell["people"].sort()
        for goal in model.goals:
            cell["goals"][goal]["proven"].sort()
            cell["goals"][goal]["possible"].sort()
        cell["chain"].sort()
    return table
