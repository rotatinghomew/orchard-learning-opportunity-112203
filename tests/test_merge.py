"""新到资料：更正班后证明，但不倒填当时的分配。"""
from pathlib import Path
import unittest

import decide
from model import build_model
from packet import merge_packets, parse_time, read_packet
from solve import POSSIBLE, PROVEN, solve

PACKET = Path("资料/演练.json")


def at(text):
    return parse_time(text)


class MergeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = read_packet(PACKET)
        cls.model = build_model(cls.doc)

    def merge(self, extra):
        return build_model(merge_packets(self.doc, extra))

    def test_late_confirmation_corrects_proof_only(self):
        extra = {"confirmations": [{"person": "L06", "unit": "A1", "kind": "solo", "known": "12:30"}]}
        merged = self.merge(extra)
        self.assertEqual(solve(self.model).goal_status("L06", "pick")[0], POSSIBLE)
        self.assertEqual(solve(merged).goal_status("L06", "pick")[0], PROVEN)
        # 历史判定不变：W2 的可确认时刻仍按当时已知计算
        before = decide.evaluate_proposal(self.model, self._proposal(self.model, "W2"), at("13:12"))
        after = decide.evaluate_proposal(merged, self._proposal(merged, "W2"), at("13:12"))
        self.assertEqual(before["code"], after["code"])
        self.assertEqual(before["since"], after["since"])

    def test_late_confirmation_cannot_rewrite_notice_basis(self):
        extra = {"confirmations": [{"person": "L04", "unit": "A1", "kind": "watch", "known": "12:31"}]}
        merged = self.merge(extra)
        # 班后证明可以更正（L04 的采摘出现相互矛盾的凭证，交由校验提示）
        # 但通知依据仍按 11:27 当时已知核定
        ok_before, items_before = decide.notice_basis(self.model, self.model.notices[0])
        ok_after, items_after = decide.notice_basis(merged, merged.notices[0])
        self.assertEqual(ok_before, ok_after)
        self.assertEqual(items_before, items_after)

    def test_reply_changes_proposal_outcome_from_now_on(self):
        # 模拟 K2 迟迟未回：先构造无 K2 回单的资料，再补回单
        doc = dict(self.doc)
        doc["confirmations"] = [c for c in self.doc["confirmations"] if c.get("review") != "K2"]
        base = build_model(doc)
        w3 = self._proposal(base, "W3")
        self.assertEqual(decide.evaluate_proposal(base, w3, at("12:30"))["code"],
                         decide.EXPIRED_PENDING)
        merged = build_model(merge_packets(doc, {
            "confirmations": [{"person": "L02", "unit": "B2", "kind": "assisted",
                               "known": "12:20", "review": "K2"}]}))
        self.assertEqual(decide.evaluate_proposal(merged, self._proposal(merged, "W3"), at("12:30"))["code"],
                         decide.CONDITION_FAILED)

    def test_merge_replaces_reviews_by_id_and_dedupes(self):
        extra = {"reviews": [{"id": "K1", "person": "L03", "unit": "A2",
                              "opened": "11:25", "due": "11:55", "answers": ["solo", "assisted"]}],
                 "confirmations": [{"person": "L06", "unit": "A1", "kind": "solo", "known": "12:30"},
                                    {"person": "L06", "unit": "A1", "kind": "solo", "known": "12:30"}]}
        merged = merge_packets(self.doc, extra)
        self.assertEqual(len([r for r in merged["reviews"] if r["id"] == "K1"]), 1)
        self.assertEqual(len(merged["confirmations"]), len(self.doc["confirmations"]) + 1)

    def _proposal(self, model, pid):
        return next(p for p in model.proposals if p.id == pid)


if __name__ == "__main__":
    unittest.main()
