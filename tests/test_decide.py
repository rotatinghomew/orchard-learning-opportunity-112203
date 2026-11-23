"""当天处置：席位、候补条件、共用与通知依据。"""
from pathlib import Path
import unittest

import decide
from model import build_model
from packet import parse_time, read_packet

PACKET = Path("资料/演练.json")


def at(text):
    return parse_time(text)


class DecideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = build_model(read_packet(PACKET))

    def proposal(self, pid):
        return next(p for p in self.model.proposals if p.id == pid)

    def test_shared_station_capacity(self):
        # A3 与 ALT 同 station+slot，容量取小
        ids, capacity = self.model.capacity_group("A3")
        self.assertEqual(ids, frozenset({"A3", "ALT"}))
        self.assertEqual(capacity, 2)
        # L04 的通知 11:27 确认后只剩 1 席
        self.assertEqual(decide.free_seats(self.model, "A3", at("11:26")), 2)
        self.assertEqual(decide.free_seats(self.model, "A3", at("11:27")), 1)
        self.assertEqual(decide.free_seats(self.model, "ALT", at("11:27")), 1)

    def test_condition_follows_reply_not_deadline(self):
        w3 = self.proposal("W3")
        # K2 承诺 11:55 前回单：到期无回单不等于否定
        self.assertEqual(decide.condition_state(self.model, w3, at("11:56"))[0], "pending")
        self.assertEqual(decide.condition_state(self.model, w3, at("12:19"))[0], "pending")
        # 12:20 回单 assisted 才使条件不成立
        state, moment, reply = decide.condition_state(self.model, w3, at("12:20"))
        self.assertEqual(state, "false")
        self.assertEqual(reply.kind, "assisted")

    def test_proposal_w2_confirmable_before_open(self):
        outcome = decide.evaluate_proposal(self.model, self.proposal("W2"), at("11:47"))
        self.assertEqual(outcome["code"], decide.CONFIRMABLE)
        self.assertEqual(outcome["since"], at("11:47"))
        # 未发通知，开场后只能记为错失，不能倒填
        outcome = decide.evaluate_proposal(self.model, self.proposal("W2"), at("13:12"))
        self.assertEqual(outcome["code"], decide.MISSED_UNNOTIFIED)

    def test_proposal_w1_condition_failed(self):
        outcome = decide.evaluate_proposal(self.model, self.proposal("W1"), at("11:47"))
        self.assertEqual(outcome["code"], decide.CONDITION_FAILED)
        self.assertEqual(outcome["since"], at("11:47"))

    def test_proposal_w3_not_failed_before_reply(self):
        # 开场后、回单前：不能按否定分支处理
        outcome = decide.evaluate_proposal(self.model, self.proposal("W3"), at("12:10"))
        self.assertEqual(outcome["code"], decide.EXPIRED_PENDING)
        outcome = decide.evaluate_proposal(self.model, self.proposal("W3"), at("12:20"))
        self.assertEqual(outcome["code"], decide.CONDITION_FAILED)

    def test_proposal_w4_late_condition_reroutes(self):
        outcome = decide.evaluate_proposal(self.model, self.proposal("W4"), at("11:59"))
        self.assertEqual(outcome["code"], decide.WAITING)
        outcome = decide.evaluate_proposal(self.model, self.proposal("W4"), at("12:04"))
        self.assertEqual(outcome["code"], decide.EXPIRED_PENDING)
        outcome = decide.evaluate_proposal(self.model, self.proposal("W4"), at("12:05"))
        self.assertEqual(outcome["code"], decide.CONDITION_LATE)
        later = outcome["reroute"]["later"]
        self.assertEqual([entry["unit"] for entry in later], ["A4"])
        self.assertTrue(later[0]["ok"])
        self.assertEqual(outcome["reroute"]["closed"], ["ALT", "B3"])

    def test_sharing_requires_provable_exclusion(self):
        report = decide.sharing(self.model, at("11:45"))
        self.assertEqual(len(report), 1)
        group = report[0]
        self.assertEqual(group["proposals"], ["W1", "W2", "W3", "W4"])
        # 只有同一核对单的不同回答确实不会一起生效
        self.assertEqual(group["exclusive_pairs"], [("W1", "W2")])
        self.assertEqual(group["max_simultaneous"], 3)
        self.assertEqual(group["free_seats"], 1)
        self.assertFalse(group["guaranteed"])

    def test_notice_basis_uses_knowledge_at_notice_time(self):
        notice = self.model.notices[0]
        ok, items = decide.notice_basis(self.model, notice)
        self.assertTrue(ok)
        self.assertTrue(any("前置" in item for item in items))

    def test_eligibility_checks_access_prereq_and_seats(self):
        cache = {}
        ok, _ = decide.eligibility(self.model, "L11", "A3", at("11:47"), cache)
        self.assertTrue(ok)
        # L03 前置 sort 未证明（11:46 时 K1 未回）
        ok, reasons = decide.eligibility(self.model, "L03", "A3", at("11:46"), cache)
        self.assertFalse(ok)
        self.assertTrue(any("前置" in reason for reason in reasons))
        # 低台需求不适用 accessible=false 的工位
        ok, reasons = decide.eligibility(self.model, "L15", "B4", at("12:30"), cache)
        self.assertFalse(ok)
        self.assertTrue(any("低台" in reason for reason in reasons))

    def test_notified_seat_is_protected(self):
        # 再补两份无条件候补：只剩 1 席，不可能都可确认而不提示竞争
        # （11:47 的 K1 回单使 L01、L02 的分选被锁定，L11 有 B2 独立记录，
        #   三份候补在 11:56 都满足前置）
        doc = read_packet(PACKET)
        doc["proposals"] = doc["proposals"] + [
            {"id": "N1", "person": "L11", "unit": "A3", "submitted": "11:50"},
            {"id": "N2", "person": "L02", "unit": "A3", "submitted": "11:51"},
        ]
        model = build_model(doc)
        now = at("11:56")
        evaluations = [decide.evaluate_proposal(model, p, now) for p in model.proposals]
        conflicts = decide.seat_conflicts(model, evaluations, now)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["free_seats"], 1)
        self.assertEqual(set(conflicts[0]["proposals"]), {"W2", "N1", "N2"})
        # L04 的通知始终占位
        self.assertEqual(decide.free_seats(model, "A3", now), 1)


if __name__ == "__main__":
    unittest.main()
