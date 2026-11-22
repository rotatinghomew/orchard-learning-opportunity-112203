"""核对演练资料的公开输入约定。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from inspect_packet import read_packet


class PacketTest(unittest.TestCase):
    def test_related_records(self):
        doc = read_packet(Path("资料/演练.json"))
        people={row['person'] for row in doc['people']}
        units={row['id'] for row in doc['activities']}
        self.assertTrue(len(people)==len(doc['people']) and len(units)==len(doc['activities']))
        self.assertTrue(all(set(row['people'])<=people and row['did']<=len(set(row['people'])) for row in doc['records']))
        self.assertTrue({row['unit'] for row in doc['records']+doc['notices']+doc['confirmations']}<=units)
        self.assertTrue({row['person'] for row in doc['transfers']+doc['notices']+doc['confirmations']}<=people)
        self.assertTrue(set(doc['curriculum']['replace'])<=units)
        self.assertTrue(all(set(group)<=units for group in doc['curriculum']['replace'].values()))

    def test_reject_wrong_container(self):
        with TemporaryDirectory() as folder:
            packet = Path(folder) / "unexpected.json"
            packet.write_text(json.dumps({"invalid": 3}), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_packet(packet)
