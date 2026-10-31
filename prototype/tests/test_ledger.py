import sqlite3
import tempfile
import unittest
from pathlib import Path

from apex import canonical
from apex.ledger import GENESIS_PARENT, ROOT, Ledger, LedgerError, verify


class LedgerTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.ledger = Ledger(self.run_dir)

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def build_small_run(self):
        """Genesis, two seed branches with one agent_run each, a generation event, heads."""
        cfg = self.ledger.blobs.put({"config": {"seed": 1}})
        g = self.ledger.genesis([{"action": "config", "result_hash": cfg}])
        branches = {}
        for agent_id in ("a0", "a1"):
            b = self.ledger.fork(g["block_hash"], agent_id)
            out = self.ledger.blobs.put({"tool": "run_tests", "result": agent_id})
            self.ledger.append("agent_run", b, [{"agent_id": agent_id, "action": "tool:run_tests",
                                                 "result_hash": out}])
            branches[agent_id] = b
        hidden = self.ledger.holdout_blobs.put({"hidden_pass_rate_ppm": 500000})
        self.ledger.append("generation_event", ROOT, [{"action": "hidden_ref", "result_hash": hidden}])
        self.ledger.publish_heads(0)
        return g, branches


class LedgerBuildTest(LedgerTestBase):
    def test_genesis_shape(self):
        g = self.ledger.genesis([])
        self.assertEqual(g["height"], 0)
        self.assertEqual(g["parent_hash"], GENESIS_PARENT)
        self.assertEqual(g["branch_id"], ROOT)
        self.assertEqual(g["kind"], "genesis")
        body = {k: v for k, v in g.items() if k != "block_hash"}
        self.assertEqual(g["block_hash"], canonical.hash_obj(body))

    def test_second_genesis_rejected(self):
        self.ledger.genesis([])
        with self.assertRaises(LedgerError):
            self.ledger.genesis([])

    def test_fork_and_append_rules(self):
        g, branches = self.build_small_run()
        b = branches["a0"]
        self.assertEqual(b, canonical.sha256_hex((g["block_hash"] + "a0").encode()))
        blk = self.ledger.get_block(self.ledger.tip(b))
        self.assertEqual(blk["parent_hash"], g["block_hash"])
        self.assertEqual(blk["height"], 1)
        clocks = [x["lamport_clock"] for x in self.ledger.blocks()]
        self.assertEqual(clocks, sorted(set(clocks)))   # unique and increasing (single writer)

    def test_append_rejects_unknown_branch_and_bad_kind(self):
        self.ledger.genesis([])
        with self.assertRaises(LedgerError):
            self.ledger.append("agent_run", "nope", [])
        with self.assertRaises(LedgerError):
            self.ledger.append("agent_run", ROOT, [])         # agent_run must not be on root
        with self.assertRaises(LedgerError):
            self.ledger.append("bogus", ROOT, [])

    def test_append_rejects_missing_blob(self):
        self.ledger.genesis([])
        with self.assertRaises(LedgerError):
            self.ledger.append("generation_event", ROOT, [{"action": "x", "result_hash": "0" * 64}])

    def test_reopen_continues_clock(self):
        self.build_small_run()
        last = self.ledger.blocks()[-1]["lamport_clock"]
        self.ledger.close()
        self.ledger = Ledger(self.run_dir)
        blk = self.ledger.append("generation_event", ROOT, [])
        self.assertEqual(blk["lamport_clock"], last + 1)


class VerifyTest(LedgerTestBase):
    def test_clean_run_verifies(self):
        self.build_small_run()
        self.assertEqual(verify(self.run_dir), [])

    def test_edit_one_block_body_fails(self):
        self.build_small_run()
        self.ledger.close()
        db = sqlite3.connect(self.run_dir / "ledger.sqlite")
        h, body = db.execute("SELECT block_hash, body FROM blocks WHERE kind='agent_run' LIMIT 1").fetchone()
        db.execute("UPDATE blocks SET body=? WHERE block_hash=?", (body.replace("tool:run_tests", "tool:hacked"), h))
        db.commit()
        db.close()
        problems = verify(self.run_dir)
        self.assertTrue(any("hash mismatch" in p for p in problems), problems)

    def test_full_rehash_fails_on_published_heads(self):
        """Rewrite a block and recompute every hash, tip and child link: only the heads file catches it."""
        self.build_small_run()
        self.ledger.close()
        db = sqlite3.connect(self.run_dir / "ledger.sqlite")
        rows = db.execute("SELECT block_hash, body FROM blocks ORDER BY lamport_clock").fetchall()
        remap, branch_remap = {}, {}
        db.execute("DELETE FROM blocks")
        for old_hash, text in rows:
            body = canonical.loads(text)
            body["parent_hash"] = remap.get(body["parent_hash"], body["parent_hash"])
            if body["kind"] == "genesis":
                body["timestamp"] = "1999-01-01T00:00:00.000Z"
            old_branch = body["branch_id"]
            if old_branch != ROOT and old_branch not in branch_remap:     # first block of the branch
                branch_remap[old_branch] = canonical.sha256_hex(
                    (body["parent_hash"] + body["state_transitions"][0]["agent_id"]).encode())
            body["branch_id"] = branch_remap.get(old_branch, old_branch)
            new_hash = canonical.hash_obj(body)
            remap[old_hash] = new_hash
            db.execute("INSERT INTO blocks VALUES (?,?,?,?,?,?,?)",
                       (new_hash, body["branch_id"], body["kind"], body["height"], body["lamport_clock"],
                        body["parent_hash"], canonical.dumps(body).decode()))
        db.execute("DELETE FROM tips")
        for branch_id, tip in {r[1]: r[0] for r in db.execute(
                "SELECT block_hash, branch_id FROM blocks ORDER BY lamport_clock")}.items():
            db.execute("INSERT INTO tips VALUES (?,?)", (branch_id, tip))
        db.commit()
        db.close()
        problems = verify(self.run_dir)
        self.assertTrue(problems)
        self.assertTrue(all("heads" in p for p in problems), problems)

    def test_edit_blob_fails(self):
        self.build_small_run()
        blob = next(p for p in (self.run_dir / "blobs").rglob("*") if p.is_file())
        blob.write_bytes(blob.read_bytes().replace(b"a0", b"zz").replace(b"a1", b"zz").replace(b"seed", b"seex"))
        problems = verify(self.run_dir)
        self.assertTrue(any("blob" in p for p in problems), problems)

    def _set_body(self, kind, new_text):
        self.ledger.close()
        db = sqlite3.connect(self.run_dir / "ledger.sqlite")
        db.execute("UPDATE blocks SET body=? WHERE kind=?", (new_text, kind))
        db.commit()
        db.close()

    def test_malformed_body_is_reported_not_raised(self):
        self.build_small_run()
        self._set_body("generation_event", '[{"kind":1}]')
        problems = verify(self.run_dir)
        self.assertTrue(any("block schema" in p for p in problems), problems)
        self.assertFalse(any("aborted" in p for p in problems), problems)

    def test_garbage_heads_line_is_reported(self):
        self.build_small_run()
        with (self.run_dir / "heads.jsonl").open("ab") as f:
            f.write(b'{"generation": 1, "tips": \n[1,2]\n')
        problems = verify(self.run_dir)
        self.assertTrue(any("line 2" in p for p in problems) and any("line 3" in p for p in problems), problems)

    def test_verify_writes_nothing(self):
        missing = Path(self._tmp.name) / "nope"
        self.assertTrue(verify(missing))
        self.assertFalse(missing.exists())

    def test_later_transition_with_other_agent_id_fails(self):
        g, branches = self.build_small_run()
        out = self.ledger.blobs.put({"x": 1})
        self.ledger.append("agent_run", branches["a0"], [{"agent_id": "a1", "action": "x", "result_hash": out}])
        self.ledger.publish_heads(1)
        self.assertTrue(any("agent_id differs" in p for p in verify(self.run_dir)))

    def test_out_of_band_heads_catch_rewrite_of_whole_dir(self):
        self.build_small_run()
        kept = Path(self._tmp.name) / "heads-elsewhere.jsonl"
        kept.write_bytes((self.run_dir / "heads.jsonl").read_bytes())
        # Attacker appends a block and republishes heads inside the run dir: in-dir heads look fine.
        self.ledger.append("generation_event", ROOT, [])
        self.ledger.publish_heads(1)
        (self.run_dir / "heads.jsonl").write_bytes((self.run_dir / "heads.jsonl").read_bytes().splitlines()[-1] + b"\n")
        self.assertEqual(verify(self.run_dir), [])
        self.assertTrue(verify(self.run_dir, heads_file=kept))

    def test_required_genesis_actions(self):
        self.build_small_run()
        self.assertEqual(verify(self.run_dir, required_genesis_actions={"config"}), [])
        self.assertTrue(any("'rng_seed'" in p for p in verify(self.run_dir, required_genesis_actions={"rng_seed"})))

    def test_edit_holdout_blob_fails(self):
        self.build_small_run()
        blob = next(p for p in (self.run_dir / "blobs-holdout").rglob("*") if p.is_file())
        blob.write_bytes(b'{"hidden_pass_rate_ppm":1000000}')
        self.assertTrue(any("blob" in p for p in verify(self.run_dir)))


if __name__ == "__main__":
    unittest.main()
