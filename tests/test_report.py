"""报告与命令行：个人查询分列三段，预约不等于完成证明。"""
from pathlib import Path
import io
import unittest
from contextlib import redirect_stdout

from main import main
from model import build_model
from packet import read_packet
from report import child_report, plan_report, proof_report
from solve import solve

PACKET = Path("资料/演练.json")


class ReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = build_model(read_packet(PACKET))
        cls.result = solve(cls.model)

    def test_child_report_separates_notice_basis_and_proof(self):
        text = child_report(self.model, self.result, "L04", self.model.latest_time())
        self.assertIn("当天通知过什么", text)
        self.assertIn("凭什么给过机会", text)
        self.assertIn("班后能证明独立完成了什么", text)
        self.assertIn("A3", text)                       # 通知过 A3
        self.assertIn("顺序完成全程 ✓", text)            # 班后证明走完全程
        self.assertIn("预约与通知不是完成证明", text)

    def test_child_report_shows_transfer_and_no_absence_claim(self):
        text = child_report(self.model, self.result, "L10", self.model.latest_time())
        self.assertIn("转组后归属：A 班", text)
        self.assertIn("低台需求不适用该工位", text)
        self.assertIn("缺 pick、measure", text)
        text = child_report(self.model, self.result, "L08", self.model.latest_time())
        self.assertIn("不等于缺席", text)

    def test_proof_report_does_not_invent_names(self):
        text = proof_report(self.model, self.result)
        self.assertIn("不补齐名单", text)
        self.assertIn("候选", text)
        # 观看演示覆盖两个班，但不构成操作凭证
        self.assertIn("不构成独立操作凭证", text)

    def test_plan_report_marks_waiting_and_late(self):
        text = plan_report(self.model, read_packet and self.model.latest_time())
        self.assertIn("本可于 11:47 确认", text)
        self.assertIn("不能倒填", text)
        self.assertIn("可改派后续工位 A4", text)

    def test_cli_commands(self):
        for argv in ([], ["资料/演练.json", "proof"],
                     ["资料/演练.json", "plan", "--at", "11:45"],
                     ["资料/演练.json", "child", "L01"]):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                main(argv)
            self.assertTrue(buffer.getvalue().strip(), argv)

    def test_cli_rejects_unknown_child(self):
        with self.assertRaises(SystemExit):
            main(["资料/演练.json", "child", "L99"])


if __name__ == "__main__":
    unittest.main()
