"""Real-filesystem FilePublisher tests: strict gates, atomic commit, lookup.

The adapter's external effect is an actual file on disk; every test uses a
disposable temporary directory, real files and real subprocesses — never a
mocked filesystem. See docs/file-adapter.md for the declared boundaries.
"""

import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from work_runtime.adapter_contract import AdapterContract, receipt_is_valid
from work_runtime.file_adapter import FilePublisher
from work_runtime.policy import digest

_HEX_JSON = re.compile(r"[0-9a-f]{64}\.json")


def committed_files(directory):
    """Actual committed hash-named artifacts in the directory."""
    return sorted(name for name in os.listdir(directory) if _HEX_JSON.fullmatch(name))


def stage_files(directory):
    return sorted(name for name in os.listdir(directory) if name.endswith(".stage"))


def path_for(directory, key):
    return os.path.join(
        directory, hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")


def read_artifact(directory, key):
    with open(path_for(directory, key), "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def sample_document(doc_id="ART-001"):
    return {"id": doc_id, "title": "Release notes", "body": "Version one.",
            "requires_review": True}


def changed_document():
    return sample_document(doc_id="ART-002")


class FileAdapterTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="file-adapter-test-")
        self.addCleanup(tmp.cleanup)
        self.directory = tmp.name

    def make_adapter(self):
        return FilePublisher(self.directory)


class KeyGateTests(FileAdapterTestCase):
    def test_non_string_keys_are_rejected_without_files(self):
        adapter = self.make_adapter()
        document = sample_document()
        for bad in (7, b"key", None, 3.5, True, ("k",)):
            with self.assertRaises(ValueError):
                adapter.execute(bad, document, digest(document))
            with self.assertRaises(ValueError):
                adapter.lookup(bad)
        self.assertEqual(os.listdir(self.directory), [])

    def test_empty_key_is_rejected_without_files(self):
        adapter = self.make_adapter()
        document = sample_document()
        with self.assertRaises(ValueError):
            adapter.execute("", document, digest(document))
        with self.assertRaises(ValueError):
            adapter.lookup("")
        self.assertEqual(os.listdir(self.directory), [])

    def test_lone_surrogate_key_is_rejected_without_leaking_it(self):
        adapter = self.make_adapter()
        key = "bad\ud800key"
        with self.assertRaises(ValueError) as raised:
            adapter.execute(key, sample_document(), digest(sample_document()))
        self.assertNotIn("\ud800", str(raised.exception))
        self.assertNotIn(repr(key), str(raised.exception))
        self.assertEqual(os.listdir(self.directory), [])


class DocumentGateTests(FileAdapterTestCase):
    def test_non_dict_roots_are_rejected(self):
        adapter = self.make_adapter()
        for bad in ([1, 2], "document", 7, None, True):
            with self.assertRaises(ValueError):
                adapter.execute("gate-key", bad, "0" * 64)
        self.assertEqual(os.listdir(self.directory), [])

    def test_container_subclasses_are_rejected(self):
        adapter = self.make_adapter()
        class MyDict(dict):
            pass
        class MyList(list):
            pass
        for bad in (MyDict(), {"a": MyList()}, {"a": [MyDict()]}):
            with self.assertRaises(ValueError):
                adapter.execute("gate-key", bad, "0" * 64)
        self.assertEqual(os.listdir(self.directory), [])

    def test_non_json_native_values_are_rejected(self):
        adapter = self.make_adapter()
        for bad in ({"a": (1, 2)}, {"a": {1, 2}}, {"a": b"bytes"},
                    {"a": object()}, {"a": {"b": (1,)}}):
            with self.assertRaises(ValueError):
                adapter.execute("gate-key", bad, "0" * 64)
        self.assertEqual(os.listdir(self.directory), [])

    def test_non_string_dict_keys_are_rejected(self):
        adapter = self.make_adapter()
        for bad in ({1: "a"}, {"a": {None: "b"}}, {("k",): 1}, {"a": [{3: "c"}]}):
            with self.assertRaises(ValueError):
                adapter.execute("gate-key", bad, "0" * 64)
        self.assertEqual(os.listdir(self.directory), [])

    def test_nonfinite_floats_are_rejected(self):
        adapter = self.make_adapter()
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                adapter.execute("gate-key", {"a": bad}, "0" * 64)
        self.assertEqual(os.listdir(self.directory), [])

    def test_out_of_range_integers_are_rejected_and_boundaries_accepted(self):
        adapter = self.make_adapter()
        for bad in (2 ** 53, -(2 ** 53) - 1, 2 ** 100):
            with self.assertRaises(ValueError):
                adapter.execute("gate-key", {"a": bad}, "0" * 64)
        self.assertEqual(os.listdir(self.directory), [])
        bounded = {"max": 2 ** 53 - 1, "min": -(2 ** 53 - 1), "flag": True, "zero": 0}
        receipt = adapter.execute("bounds", bounded, digest(bounded))
        self.assertEqual(receipt["status"], "accepted")

    def test_lone_surrogate_strings_are_rejected_without_leaking_them(self):
        adapter = self.make_adapter()
        for bad in ({"a": "bad\ud800"}, {"bad\ud800": 1}, {"a": ["x\udfff"]}):
            with self.assertRaises(ValueError) as raised:
                adapter.execute("gate-key", bad, "0" * 64)
            self.assertNotIn("\ud800", str(raised.exception))
            self.assertNotIn("\udfff", str(raised.exception))
        self.assertEqual(os.listdir(self.directory), [])

    def test_cycles_are_rejected_without_recursion_error(self):
        adapter = self.make_adapter()
        looped_list = []
        looped_list.append(looped_list)
        looped_dict = {}
        looped_dict["self"] = looped_dict
        for bad in ({"a": looped_list}, looped_dict, {"a": {"b": [looped_dict]}}):
            with self.assertRaises(ValueError) as raised:
                adapter.execute("gate-key", bad, "0" * 64)
            self.assertNotIsInstance(raised.exception, RecursionError)
        self.assertEqual(os.listdir(self.directory), [])

    def test_acyclic_aliases_are_valid(self):
        adapter = self.make_adapter()
        shared = {"note": "shared"}
        document = {"first": shared, "second": shared, "list": [shared, shared]}
        receipt = adapter.execute("alias", document, digest(document))
        self.assertEqual(receipt["status"], "accepted")
        artifact = read_artifact(self.directory, "alias")
        self.assertEqual(artifact["document"]["first"], shared)
        self.assertEqual(artifact["document"]["second"], artifact["document"]["first"])
        self.assertEqual(artifact["document"]["list"][0], artifact["document"]["list"][1])

    def test_depth_boundary_is_64_containers(self):
        adapter = self.make_adapter()

        def nested(count):
            value = "leaf"
            for _ in range(count):
                value = [value]
            return {"a": value}

        ok = nested(63)  # root dict (depth 1) + 63 nested lists = depth 64.
        receipt = adapter.execute("deep-ok", ok, digest(ok))
        self.assertEqual(receipt["status"], "accepted")
        too_deep = nested(64)
        with self.assertRaises(ValueError):
            adapter.execute("deep-bad", too_deep, "0" * 64)
        self.assertEqual([name for name in os.listdir(self.directory)],
                         [name for name in committed_files(self.directory)])


class DigestGateTests(FileAdapterTestCase):
    def test_wrong_content_digest_is_rejected_without_files(self):
        adapter = self.make_adapter()
        document = sample_document()
        with self.assertRaises(ValueError):
            adapter.execute("digest-key", document, "0" * 64)
        self.assertEqual(os.listdir(self.directory), [])

    def test_non_string_digest_is_rejected(self):
        adapter = self.make_adapter()
        document = sample_document()
        for bad in (None, "", 123):
            with self.assertRaises(ValueError):
                adapter.execute("digest-key", document, bad)
        self.assertEqual(os.listdir(self.directory), [])


class CommitTests(FileAdapterTestCase):
    def test_publish_commits_exactly_one_hash_named_artifact(self):
        adapter = self.make_adapter()
        document = sample_document()
        key = "unicode-key-中文🔑"
        receipt = adapter.execute(key, document, digest(document))
        self.assertEqual(set(receipt), {"status", "external_id", "digest"})
        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(receipt["digest"], digest(document))
        self.assertTrue(receipt["external_id"].startswith("FILE-"))
        self.assertEqual(len(receipt["external_id"]), len("FILE-") + 32)
        self.assertTrue(receipt_is_valid(receipt, digest(document)))
        self.assertEqual(committed_files(self.directory),
                         [hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"])
        self.assertEqual(stage_files(self.directory), [])
        artifact = read_artifact(self.directory, key)
        self.assertEqual(set(artifact),
                         {"artifact_version", "key", "content_digest",
                          "document", "receipt"})
        self.assertIs(type(artifact["artifact_version"]), int)
        self.assertEqual(artifact["artifact_version"], 1)
        self.assertEqual(artifact["key"], key)
        self.assertEqual(artifact["content_digest"], digest(document))
        self.assertEqual(artifact["document"], document)
        self.assertEqual(artifact["receipt"], receipt)

    def test_replay_same_instance_returns_identical_receipt_and_stable_bytes(self):
        adapter = self.make_adapter()
        document = sample_document()
        first = adapter.execute("replay", document, digest(document))
        raw = Path(path_for(self.directory, "replay")).read_bytes()
        second = adapter.execute("replay", document, digest(document))
        self.assertEqual(first, second)
        self.assertEqual(Path(path_for(self.directory, "replay")).read_bytes(), raw)
        self.assertEqual(len(committed_files(self.directory)), 1)
        self.assertEqual(stage_files(self.directory), [])

    def test_restart_returns_stable_winning_receipt(self):
        adapter = self.make_adapter()
        document = sample_document()
        first = adapter.execute("restart", document, digest(document))
        raw = Path(path_for(self.directory, "restart")).read_bytes()
        reopened = FilePublisher(self.directory)
        second = reopened.execute("restart", document, digest(document))
        self.assertEqual(first, second)
        self.assertEqual(Path(path_for(self.directory, "restart")).read_bytes(), raw)
        self.assertEqual(len(committed_files(self.directory)), 1)
        self.assertEqual(reopened.lookup("restart"), first)

    def test_same_key_different_content_raises_without_overwrite(self):
        adapter = self.make_adapter()
        document = sample_document()
        first = adapter.execute("clash", document, digest(document))
        raw = Path(path_for(self.directory, "clash")).read_bytes()
        changed = changed_document()
        with self.assertRaises(ValueError):
            adapter.execute("clash", changed, digest(changed))
        self.assertEqual(Path(path_for(self.directory, "clash")).read_bytes(), raw)
        self.assertEqual(len(committed_files(self.directory)), 1)
        self.assertEqual(stage_files(self.directory), [])
        self.assertEqual(adapter.lookup("clash"), first)

    def test_lookup_missing_key_returns_none(self):
        adapter = self.make_adapter()
        self.assertIsNone(adapter.lookup("missing-key"))
        document = sample_document()
        adapter.execute("present", document, digest(document))
        self.assertIsNone(adapter.lookup("missing-key"))

    def test_lookup_committed_key_returns_the_committed_receipt(self):
        adapter = self.make_adapter()
        document = sample_document()
        receipt = adapter.execute("lookup-key", document, digest(document))
        self.assertEqual(adapter.lookup("lookup-key"), receipt)
        self.assertEqual(adapter.lookup("lookup-key"), adapter.lookup("lookup-key"))

    def test_unicode_document_round_trips(self):
        adapter = self.make_adapter()
        document = {"id": "U-1", "title": "发布说明", "body": "第一版。🍦",
                    "requires_review": None, "notes": ["中文", "études"]}
        receipt = adapter.execute("unicode-doc", document, digest(document))
        self.assertEqual(receipt["digest"], digest(document))
        artifact = read_artifact(self.directory, "unicode-doc")
        self.assertEqual(artifact["document"], document)

    def test_traversal_shaped_keys_hash_to_safe_basenames(self):
        adapter = self.make_adapter()
        document = sample_document()
        keys = ("../../etc/passwd", "a/b/c", "..", ".")
        for key in keys:
            adapter.execute(key, document, digest(document))
        expected = sorted(hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json"
                          for key in keys)
        self.assertEqual(sorted(os.listdir(self.directory)), expected)
        parent = sorted(os.listdir(os.path.dirname(self.directory)))
        self.assertEqual(len([name for name in parent
                              if name.startswith("file-adapter-test-")]), 1)


class ContractMetadataTests(FileAdapterTestCase):
    def test_declared_contract_is_directory_scoped(self):
        contract = FilePublisher(self.directory).contract
        self.assertEqual(contract, AdapterContract(
            actions=("content.publish",),
            idempotency_scope="directory:key",
            retention="lifetime-of-directory",
            lookup_consistency="authoritative-by-key",
            uniqueness=()))


if __name__ == "__main__":
    unittest.main()
