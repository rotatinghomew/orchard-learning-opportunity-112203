"""核对情形枚举与班后证明的业务结论。"""
from pathlib import Path
import unittest

from model import build_model
from packet import read_packet
from solve import (EXCLUDED, NO_RECORD, POSSIBLE, PROVEN, coverage, solve)

PACKET = Path("资料/演练.json")


class SolveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = build_model(read_packet(PACKET))
        cls.result = solve(cls.model)

    def status(self, person, unit):
        return self.result.unit_status(person, unit)[0]

    def test_scenarios_cover_all_records(self):
        # 全部记录能同时被解释，且没有唯一情形（不自行补齐名单）
        self.assertGreater(self.result.scenarios, 1)

    def test_direct_and_forced_proof(self):
        self.assertEqual(self.status("L01", "A1"), PROVEN)   # 个人独立记录
        self.assertEqual(self.status("L02", "A2"), PROVEN)   # 计数表被互证记录锁定
        self.assertEqual(self.status("L10", "A2"), PROVEN)
        self.assertEqual(self.status("L12", "B1"), PROVEN)   # 低台需求者被排除后恰好锁定

    def test_possible_is_not_proven(self):
        self.assertEqual(self.status("L00", "A1"), POSSIBLE)
        self.assertEqual(self.status("L12", "B2"), POSSIBLE)

    def test_exclusions(self):
        self.assertEqual(self.status("L03", "A2"), EXCLUDED)  # 回单：由同伴代操作
        self.assertEqual(self.status("L02", "B2"), EXCLUDED)
        self.assertEqual(self.status("L10", "B1"), EXCLUDED)  # 低台需求不适用
        self.assertEqual(self.status("L15", "B1"), EXCLUDED)
        # 同时段只能在一个操作位：L10 已在 A2
        self.assertEqual(self.status("L10", "B2"), EXCLUDED)
        self.assertEqual(self.result.unit_status("L10", "B2")[1],
                         "同时段已在其他工位独立操作")

    def test_no_record_is_not_absence(self):
        self.assertEqual(self.status("L06", "A3"), NO_RECORD)
        status, _ = self.result.goal_status("L06", "measure")
        self.assertEqual(status, NO_RECORD)

    def test_goal_status(self):
        self.assertEqual(self.result.goal_status("L01", "measure")[0], PROVEN)
        self.assertEqual(self.result.goal_status("L10", "pick")[0], EXCLUDED)
        self.assertEqual(self.result.goal_status("L10", "sort")[0], PROVEN)
        self.assertEqual(self.result.goal_status("L15", "sort")[0], POSSIBLE)

    def test_chain_requires_same_child_in_order(self):
        done, steps, _ = self.result.chain("L01")
        self.assertTrue(done)
        self.assertEqual([goal for goal, _, _ in steps], ["pick", "sort", "measure"])
        done, _, _ = self.result.chain("L04")
        self.assertTrue(done)
        # 分选与测量各自覆盖得不错，不代表同一批孩子走完两段
        for person in ("L02", "L10", "L11", "L12"):
            self.assertFalse(self.result.chain(person)[0], person)
        _, _, missing = self.result.chain("L10")
        self.assertIn("pick", missing)

    def test_repeats(self):
        self.assertEqual(len(self.result.proven_units("L01")), 3)
        self.assertEqual(len(self.result.proven_units("L04")), 3)
        self.assertEqual(len(self.result.proven_units("L02")), 2)
        self.assertEqual(len(self.result.proven_units("L11")), 2)
        self.assertEqual(len(self.result.proven_units("L15")), 0)

    def test_coverage_denominator_by_class_and_needs(self):
        table = coverage(self.model, self.result)
        self.assertEqual(len(table[("A", "low_counter")]["people"]), 2)
        self.assertEqual(len(table[("A", "none")]["people"]), 8)
        self.assertEqual(table[("A", "none")]["goals"]["pick"]["proven"],
                         ["L01", "L02", "L03", "L04"])
        self.assertEqual(table[("B", "none")]["goals"]["sort"]["possible"],
                         ["L12", "L13", "L14"])

    def test_coverage_adjusted_by_transfer(self):
        table = coverage(self.model, self.result, adjusted=True)
        self.assertIn("L10", table[("A", "low_counter")]["people"])
        self.assertIn("L02", table[("B", "none")]["people"])
        self.assertNotIn("L02", table[("A", "none")]["people"])

    def test_cutoff_limits_knowledge(self):
        early = solve(self.model, cutoff=11 * 60 + 30)  # 11:30，K1/K3 回单未到
        self.assertEqual(early.goal_status("L01", "sort")[0], POSSIBLE)
        self.assertEqual(early.goal_status("L03", "sort")[0], POSSIBLE)
        late = solve(self.model, cutoff=12 * 60 + 5)   # 12:05，K1/K3 已到
        self.assertEqual(late.goal_status("L01", "sort")[0], PROVEN)
        self.assertEqual(late.goal_status("L03", "sort")[0], EXCLUDED)


if __name__ == "__main__":
    unittest.main()
