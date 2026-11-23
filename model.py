"""把资料包解析为带时刻的对象模型，并做基本校验。

校验分两级：结构错误（无法继续）抛出 ValueError；
业务上可疑但不致命的问题收入 model.warnings，由报告层展示。
"""
from dataclasses import dataclass

from packet import ANSWER_KINDS, RECORD_KINDS, format_time, parse_time

NEEDS_KINDS = ("none", "low_counter")


@dataclass
class Person:
    id: str
    class_id: str
    needs: str


@dataclass
class Unit:
    id: str
    station: str
    target: str
    slot: int
    capacity: int
    accessible: bool
    prereq: str | None


@dataclass
class Record:
    unit: str
    people: tuple
    did: int
    kind: str
    when: int


@dataclass
class Transfer:
    person: str
    from_group: str
    to_group: str
    known: int


@dataclass
class Notice:
    person: str
    unit: str
    status: str
    known: int


@dataclass
class Confirmation:
    person: str
    unit: str
    kind: str
    known: int
    review: str | None


@dataclass
class Review:
    id: str
    person: str
    unit: str
    opened: int
    due: int
    answers: tuple


@dataclass
class Proposal:
    id: str
    person: str
    unit: str
    submitted: int
    review: str | None
    answer: str | None


def _time(row, field, where):
    try:
        return parse_time(row[field])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"{where}：{exc}") from exc


class Model:
    """资料包的对象模型。所有时刻均为当日分钟数。"""

    def __init__(self, doc):
        self.warnings = []
        for key in ("people", "activities", "records", "curriculum"):
            if key not in doc:
                raise ValueError(f"资料包缺少必需字段：{key}")

        self.people = {}
        for row in doc["people"]:
            person = Person(row["person"], row.get("class_id", ""), row.get("needs", "none"))
            if person.id in self.people:
                raise ValueError(f"名册匿名号重复：{person.id}")
            if person.needs not in NEEDS_KINDS:
                self.warnings.append(f"{person.id} 的需求类别未知：{person.needs}")
            self.people[person.id] = person

        self.units = {}
        for row in doc["activities"]:
            unit = Unit(row["id"], row["station"], row["target"], int(row["slot"]),
                        int(row["capacity"]), bool(row.get("accessible", True)), row.get("prereq"))
            if unit.id in self.units:
                raise ValueError(f"单元编号重复：{unit.id}")
            self.units[unit.id] = unit

        curriculum = doc["curriculum"]
        self.goals = list(curriculum.get("goals", []))
        self.min_independent_each = int(curriculum.get("min_independent_each", 1))
        self.windows = {int(slot): parse_time(text) for slot, text in curriculum.get("windows", {}).items()}
        self.replace = {key: list(value) for key, value in curriculum.get("replace", {}).items()}
        for unit in self.units.values():
            if unit.slot not in self.windows:
                raise ValueError(f"单元 {unit.id} 的时段 {unit.slot} 没有开场时刻")
            if unit.prereq is not None and unit.prereq not in self.goals:
                self.warnings.append(f"单元 {unit.id} 的前置目标 {unit.prereq} 不在课程目标中")
        for key, options in self.replace.items():
            if key not in self.units:
                raise ValueError(f"替换范围引用了不存在的单元：{key}")
            for option in options:
                if option not in self.units:
                    raise ValueError(f"替换范围引用了不存在的单元：{option}")

        self.records = []
        for row in doc["records"]:
            record = Record(row["unit"], tuple(row["people"]), int(row["did"]), row["kind"],
                            _time(row, "when", f"记录 {row}"))
            if record.unit not in self.units:
                raise ValueError(f"记录引用了不存在的单元：{record.unit}")
            if record.kind not in RECORD_KINDS:
                raise ValueError(f"记录类型未知：{record.kind}")
            for person in record.people:
                if person not in self.people:
                    raise ValueError(f"记录引用了名册外匿名号：{person}")
            if record.kind == "count":
                if not 0 <= record.did <= len(set(record.people)):
                    raise ValueError(f"计数表人数超出范围：{record.unit} did={record.did}")
                if record.did > self.units[record.unit].capacity:
                    self.warnings.append(f"计数表 {record.unit} 的独立操作人数超过单元容量")
            elif record.did != len(record.people):
                raise ValueError(f"{record.kind} 记录的人数应与名单一致：{record.unit}")
            self.records.append(record)
        count_units = [record.unit for record in self.records if record.kind == "count"]
        for unit_id in dict.fromkeys(count_units):
            if count_units.count(unit_id) > 1:
                self.warnings.append(f"单元 {unit_id} 有多张计数表，核对时按多张独立会话处理")

        self.transfers = []
        for row in doc.get("transfers", []):
            transfer = Transfer(row["person"], row["from_group"], row["to_group"],
                                _time(row, "known", f"转组 {row}"))
            if transfer.person not in self.people:
                raise ValueError(f"转组凭证引用了名册外匿名号：{transfer.person}")
            if self.people[transfer.person].class_id != transfer.from_group:
                self.warnings.append(f"{transfer.person} 的转组起点 {transfer.from_group} 与名册班别不一致")
            self.transfers.append(transfer)

        self.notices = []
        for row in doc.get("notices", []):
            notice = Notice(row["person"], row["unit"], row.get("status", "confirmed"),
                            _time(row, "known", f"通知 {row}"))
            self._check_person_unit(notice.person, notice.unit, "通知")
            if notice.status != "confirmed":
                self.warnings.append(f"通知状态未知：{notice.status}")
            if notice.known >= self.window(notice.unit):
                self.warnings.append(f"{notice.person} 在 {notice.unit} 的通知不早于开场时刻")
            self.notices.append(notice)

        self.reviews = {}
        for row in doc.get("reviews", []):
            review = Review(row["id"], row["person"], row["unit"],
                            _time(row, "opened", f"核对单 {row.get('id')}"),
                            _time(row, "due", f"核对单 {row.get('id')}"),
                            tuple(row["answers"]))
            if review.id in self.reviews:
                raise ValueError(f"核对单编号重复：{review.id}")
            self._check_person_unit(review.person, review.unit, "核对单")
            if review.opened > review.due:
                raise ValueError(f"核对单 {review.id} 的承诺回单时间早于登记时间")
            for answer in review.answers:
                if answer not in ANSWER_KINDS:
                    self.warnings.append(f"核对单 {review.id} 的回报类别未知：{answer}")
            self.reviews[review.id] = review

        self.confirmations = []
        for row in doc.get("confirmations", []):
            confirmation = Confirmation(row["person"], row["unit"], row["kind"],
                                        _time(row, "known", f"回单 {row}"), row.get("review"))
            self._check_person_unit(confirmation.person, confirmation.unit, "回单")
            if confirmation.kind not in ANSWER_KINDS:
                self.warnings.append(f"回单类别未知：{confirmation.kind}")
            if confirmation.review is not None:
                if confirmation.review not in self.reviews:
                    raise ValueError(f"回单引用了不存在的核对单：{confirmation.review}")
                review = self.reviews[confirmation.review]
                if (confirmation.person, confirmation.unit) != (review.person, review.unit):
                    raise ValueError(f"回单与核对单 {review.id} 的人或单元不一致")
                if confirmation.kind not in review.answers:
                    raise ValueError(f"回单类别不在核对单 {review.id} 的可回报范围内")
                if confirmation.known < review.opened:
                    raise ValueError(f"回单早于核对单 {review.id} 的登记时间")
            self.confirmations.append(confirmation)

        self.proposals = []
        for row in doc.get("proposals", []):
            condition = row.get("if") or {}
            proposal = Proposal(row["id"], row["person"], row["unit"],
                                _time(row, "submitted", f"候补 {row.get('id')}"),
                                condition.get("review"), condition.get("answer"))
            self._check_person_unit(proposal.person, proposal.unit, "候补")
            if proposal.submitted >= self.window(proposal.unit):
                raise ValueError(f"候补 {proposal.id} 提交时已过开场时刻")
            if proposal.review is not None:
                if proposal.review not in self.reviews:
                    raise ValueError(f"候补 {proposal.id} 引用了不存在的核对单：{proposal.review}")
                review = self.reviews[proposal.review]
                if proposal.answer not in review.answers:
                    raise ValueError(f"候补 {proposal.id} 的启动条件不在核对单 {review.id} 的可回报范围内")
                if review.opened > proposal.submitted:
                    raise ValueError(f"候补 {proposal.id} 提交时核对单 {review.id} 尚未登记")
                if review.due >= self.window(proposal.unit):
                    self.warnings.append(
                        f"候补 {proposal.id} 的核对单 {review.id} 承诺回单时间"
                        f"（{format_time(review.due)}）不早于 {proposal.unit} 开场"
                        f"（{format_time(self.window(proposal.unit))}），存在错过风险")
            self.proposals.append(proposal)

        self._check_capacity_groups()
        self._check_solo_conflicts()

    def _check_person_unit(self, person, unit, where):
        if person not in self.people:
            raise ValueError(f"{where}引用了名册外匿名号：{person}")
        if unit not in self.units:
            raise ValueError(f"{where}引用了不存在的单元：{unit}")

    def _check_capacity_groups(self):
        groups = {}
        for unit in self.units.values():
            groups.setdefault((unit.station, unit.slot), []).append(unit)
        self._capacity_groups = {}
        for members in groups.values():
            capacity = min(unit.capacity for unit in members)
            ids = frozenset(unit.id for unit in members)
            for unit in members:
                self._capacity_groups[unit.id] = (ids, capacity)
        taken = {}
        for notice in self.notices:
            if notice.status == "confirmed":
                ids, capacity = self._capacity_groups[notice.unit]
                key = tuple(sorted(ids))
                taken[key] = taken.get(key, 0) + 1
                if taken[key] > capacity:
                    self.warnings.append(f"工位 {sorted(ids)} 的确认通知超过该时段物理容量 {capacity}")

    def _check_solo_conflicts(self):
        seen = {}
        for record in self.records:
            if record.kind != "solo":
                continue
            slot = self.units[record.unit].slot
            for person in record.people:
                key = (person, slot)
                if key in seen and seen[key] != record.unit:
                    self.warnings.append(
                        f"{person} 在时段 {slot} 同时有 {seen[key]} 与 {record.unit} 的独立操作记录")
                seen[key] = record.unit

    def window(self, unit_id):
        return self.windows[self.units[unit_id].slot]

    def capacity_group(self, unit_id):
        """相同 station+slot 的单元共用同一工位，容量取较小值。返回 (单元集合, 容量)。"""
        return self._capacity_groups[unit_id]

    def latest_time(self):
        times = [record.when for record in self.records]
        times += [t.known for t in self.transfers]
        times += [n.known for n in self.notices]
        times += [c.known for c in self.confirmations]
        times += [p.submitted for p in self.proposals]
        for review in self.reviews.values():
            times += [review.opened, review.due]
        times += list(self.windows.values())
        return max(times)


def build_model(doc):
    return Model(doc)
