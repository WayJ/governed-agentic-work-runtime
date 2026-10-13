"""Real-filesystem FilePublisher tests: strict gates, atomic commit, lookup.

The adapter's external effect is an actual file on disk; every test uses a
disposable temporary directory, real files and real subprocesses — never a
mocked filesystem. See docs/file-adapter.md for the declared boundaries.
"""

import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from work_runtime.adapter_contract import AdapterContract, receipt_is_valid
from work_runtime.file_adapter import FilePublisher
from work_runtime.policy import digest
from work_runtime.publishing import PublishingPolicy
from work_runtime.publishing_demo import publishing_grants
from work_runtime.runtime import Runtime
from tests.adapter_conformance import AdapterConformanceMixin

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

    def fresh_directory(self):
        tmp = tempfile.TemporaryDirectory(prefix="file-adapter-test-")
        self.addCleanup(tmp.cleanup)
        return tmp.name

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


class FilePublisherConformanceTests(AdapterConformanceMixin, FileAdapterTestCase):
    """The reusable adapter conformance suite over real committed files."""

    def make_adapter(self):
        return FilePublisher(self.directory)

    def sample_document(self):
        return sample_document()

    def changed_document(self):
        return changed_document()

    def effect_count(self, adapter):
        # Actual committed hash-named file enumeration, not an internal counter.
        return len(committed_files(adapter.directory))


class CorruptionTests(FileAdapterTestCase):
    def publish_into(self, directory, key="victim"):
        adapter = FilePublisher(directory)
        document = sample_document()
        adapter.execute(key, document, digest(document))
        return adapter, Path(path_for(directory, key)).read_bytes()

    def damaged_adapter(self, transform):
        """A committed artifact, then the same file rewritten with damage."""
        directory = self.fresh_directory()
        adapter, raw = self.publish_into(directory)
        artifact = transform(json.loads(raw.decode("utf-8")))
        with open(path_for(directory, "victim"), "wb") as handle:
            handle.write(canonical_bytes(artifact))
        return adapter

    def write_raw(self, directory, data):
        with open(path_for(directory, "victim"), "wb") as handle:
            handle.write(data)

    def test_invalid_json_bytes_raise_bounded_valueerror(self):
        adapter, raw = self.publish_into(self.fresh_directory())
        damaged = raw.replace(b'"requires_review":true', b'"requires_review":true,,')
        self.assertNotEqual(damaged, raw)
        self.write_raw(adapter.directory, damaged)
        with self.assertRaises(ValueError) as raised:
            adapter.lookup("victim")
        self.assertNotIsInstance(raised.exception, RecursionError)

    def test_invalid_utf8_bytes_raise_bounded_valueerror(self):
        adapter = self.damaged_adapter(lambda a: a)
        self.write_raw(adapter.directory, b"\xff\xfe not utf8")
        with self.assertRaises(ValueError):
            adapter.lookup("victim")

    def test_non_object_artifact_raises(self):
        adapter = self.damaged_adapter(lambda a: a)
        self.write_raw(adapter.directory, b"[1, 2, 3]")
        with self.assertRaises(ValueError):
            adapter.lookup("victim")

    def test_missing_or_extra_top_level_keys_raise(self):
        adapter = self.damaged_adapter(
            lambda a: {k: v for k, v in a.items() if k != "receipt"})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")
        adapter = self.damaged_adapter(lambda a: {**a, "extra": 1})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")

    def test_unsupported_artifact_version_raises(self):
        adapter = self.damaged_adapter(lambda a: {**a, "artifact_version": 2})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")
        adapter = self.damaged_adapter(lambda a: {**a, "artifact_version": True})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")

    def test_wrong_key_field_raises(self):
        adapter = self.damaged_adapter(
            lambda a: {**a, "key": "other-key"})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")

    def test_tampered_content_digest_raises_on_recomputed_document_digest(self):
        other = sample_document(doc_id="ART-009")
        adapter = self.damaged_adapter(lambda a: {**a, "content_digest": digest(other)})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")

    def test_non_dict_document_raises(self):
        adapter = self.damaged_adapter(
            lambda a: {**a, "document": ["not", "a", "dict"]})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")

    def test_malformed_receipt_raises(self):
        adapter = self.damaged_adapter(
            lambda a: {**a, "receipt": {"status": "accepted", "digest": a["content_digest"]}})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")
        adapter = self.damaged_adapter(
            lambda a: {**a, "receipt": {"status": "accepted", "external_id": "",
                                        "digest": a["content_digest"]}})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")
        adapter = self.damaged_adapter(
            lambda a: {**a, "receipt": {"status": "rejected", "external_id": "FILE-" + "0" * 32,
                                        "digest": a["content_digest"]}})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")
        adapter = self.damaged_adapter(
            lambda a: {**a, "receipt": {"status": "accepted", "external_id": "FILE-x",
                                        "digest": a["content_digest"], "extra": True}})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")
        adapter = self.damaged_adapter(
            lambda a: {**a, "receipt": {**a["receipt"], "digest": "0" * 64}})
        with self.assertRaises(ValueError):
            adapter.lookup("victim")

    def test_replay_against_corrupted_winner_raises_and_leaves_it_untouched(self):
        adapter = self.damaged_adapter(lambda a: {**a, "artifact_version": 3})
        raw = Path(path_for(adapter.directory, "victim")).read_bytes()
        document = sample_document()
        with self.assertRaises(ValueError):
            adapter.execute("victim", document, digest(document))
        self.assertEqual(Path(path_for(adapter.directory, "victim")).read_bytes(), raw)
        self.assertEqual(len(committed_files(adapter.directory)), 1)


def canonical_bytes(artifact):
    import work_runtime.file_adapter as module
    return module.canonical(artifact).encode("utf-8")


class SnapshotDetachmentTests(FileAdapterTestCase):
    def test_caller_mutations_after_publish_leave_the_artifact_fixed(self):
        adapter = self.make_adapter()
        document = {"id": "D-1", "items": ["a", "b"], "meta": {"n": 1}}
        receipt = adapter.execute("detach", document, digest(document))
        raw = Path(path_for(self.directory, "detach")).read_bytes()
        document["items"].append("MUTATED")
        document["meta"]["n"] = 999
        document["new"] = "field"
        self.assertEqual(Path(path_for(self.directory, "detach")).read_bytes(), raw)
        self.assertEqual(adapter.lookup("detach"), receipt)
        artifact = read_artifact(self.directory, "detach")
        self.assertEqual(artifact["document"],
                         {"id": "D-1", "items": ["a", "b"], "meta": {"n": 1}})

    def test_mutated_document_is_new_content_under_another_key(self):
        adapter = self.make_adapter()
        document = {"id": "D-1", "n": 1}
        adapter.execute("first", document, digest(document))
        document["n"] = 2
        with self.assertRaises(ValueError):
            adapter.execute("first", document, "0" * 64)  # digest no longer matches
        receipt = adapter.execute("second", document, digest(document))
        self.assertEqual(receipt["digest"], digest({"id": "D-1", "n": 2}))
        artifact = read_artifact(self.directory, "second")
        self.assertEqual(artifact["document"], {"id": "D-1", "n": 2})


class StagingHygieneTests(FileAdapterTestCase):
    def test_foreign_stage_files_are_ignored_by_lookup_and_publish(self):
        adapter = self.make_adapter()
        document = sample_document()
        with open(os.path.join(self.directory, "junk.stage"), "wb") as handle:
            handle.write(b"not json")
        self.assertIsNone(adapter.lookup("nobody"))
        receipt = adapter.execute("fresh", document, digest(document))
        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(stage_files(self.directory), ["junk.stage"])
        self.assertEqual(len(committed_files(self.directory)), 1)

    def test_effect_count_ignores_stage_files(self):
        adapter = self.make_adapter()
        document = sample_document()
        adapter.execute("counted", document, digest(document))
        with open(os.path.join(self.directory, "stale.stage"), "wb") as handle:
            handle.write(b"junk")
        self.assertEqual(len(committed_files(self.directory)), 1)


class BoundedMessageTests(FileAdapterTestCase):
    MARKER = "SECRET-MARKER-42"

    def test_gate_and_corruption_messages_never_echo_payload(self):
        adapter = self.make_adapter()
        bad_document = {"note": "leak " + self.MARKER, "oops": (1, 2)}
        with self.assertRaises(ValueError) as raised:
            adapter.execute("key-" + self.MARKER, bad_document, "0" * 64)
        self.assertNotIn(self.MARKER, str(raised.exception))
        document = {"note": self.MARKER}
        adapter.execute("victim", document, digest(document))
        raw = Path(path_for(self.directory, "victim")).read_bytes()
        artifact = json.loads(raw.decode("utf-8"))
        artifact["content_digest"] = "f" * 64
        self.write_raw(canonical_bytes(artifact))
        with self.assertRaises(ValueError) as raised:
            adapter.lookup("victim")
        self.assertNotIn(self.MARKER, str(raised.exception))

    def write_raw(self, data):
        with open(path_for(self.directory, "victim"), "wb") as handle:
            handle.write(data)


class ApiShapeTests(FileAdapterTestCase):
    def test_constructor_takes_only_a_directory(self):
        # No crash-exit, timeout or fault flags exist as constructor options;
        # real process death in tests is injected by child processes only.
        parameters = list(inspect.signature(FilePublisher.__init__).parameters)
        self.assertEqual(parameters, ["self", "directory"])


def _race_child(prelude="", tail=""):
    """Child script: optional prelude, publish, optional tail.

    Children run via ``sys.executable -c`` with the inherited working
    directory (the same pattern as tests/test_runtime.py): argv 1 is the
    adapter directory, argv 2 the JSON document, argv 3 the idempotency key.
    The prelude runs before the publish (e.g. wrapping ``os.link``); the
    tail runs after ``execute`` returns (e.g. an outer ``os._exit``).
    A publish failure prints ``ERROR:<ExceptionName>`` and exits 1.
    """
    return (
        "import json,sys\n"
        "from work_runtime.file_adapter import FilePublisher\n"
        "from work_runtime.policy import digest\n"
        + prelude +
        "document=json.loads(sys.argv[2])\n"
        "try:\n"
        "    receipt=FilePublisher(sys.argv[1]).execute(sys.argv[3],document,"
        "digest(document))\n"
        "    print(json.dumps(receipt,sort_keys=True))\n"
        "except Exception as error:\n"
        "    print('ERROR:'+type(error).__name__)\n"
        "    sys.exit(1)\n" + tail
    )


def _spawn(children):
    processes = [subprocess.Popen([sys.executable, "-c", body, directory, document, key],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True)
                 for body, directory, document, key in children]
    results = []
    for process in processes:
        out, err = process.communicate(timeout=120)
        results.append((process.returncode, out.strip(), err.strip()))
    return results


class SubprocessRaceTests(FileAdapterTestCase):
    def test_same_key_same_content_race_commits_exactly_one_artifact(self):
        directory = self.fresh_directory()
        document = sample_document()
        document_json = json.dumps(document)
        key = "race-same"
        children = [(_race_child(""), directory, document_json, key) for _ in range(5)]
        results = _spawn(children)
        for code, out, err in results:
            self.assertEqual(code, 0, err)
        receipts = [json.loads(out) for _, out, _ in results]
        first = receipts[0]
        for receipt in receipts:
            self.assertEqual(receipt, first)
        self.assertEqual(receipt, read_artifact(directory, key)["receipt"])
        self.assertEqual(len(committed_files(directory)), 1)
        self.assertEqual(stage_files(directory), [])

    def test_mixed_content_race_commits_one_artifact_with_the_stable_winner(self):
        directory = self.fresh_directory()
        key = "race-mixed"
        first, second = sample_document("ART-101"), sample_document("ART-202")
        digest_first = digest(first)
        children = []
        for document in (first, first, first, second, second, second):
            children.append((_race_child(""), directory, json.dumps(document), key))
        results = _spawn(children)
        successes = [json.loads(out) for code, out, _ in results if code == 0]
        self.assertTrue(successes, "at least one racer must win the commit")
        losing_outputs = [out for code, out, _ in results if code != 0]
        for output in losing_outputs:
            self.assertEqual(output, "ERROR:ValueError")
        artifact = read_artifact(directory, key)
        self.assertIn(artifact["content_digest"], (digest_first, digest(second)))
        winning_receipt = artifact["receipt"]
        for receipt in successes:
            self.assertEqual(receipt, winning_receipt)
        self.assertEqual(len(committed_files(directory)), 1)
        self.assertEqual(stage_files(directory), [])

    def test_death_before_link_leaves_only_ignorable_staging(self):
        directory = self.fresh_directory()
        document = sample_document()
        document_json = json.dumps(document)
        key = "dies-early"
        die_before_link = (
            "import os\n"
            "os.link=lambda *a,**k: os._exit(77)\n"
        )
        body = _race_child(prelude=die_before_link)
        child = subprocess.run([sys.executable, "-c", body, directory,
                                document_json, key], capture_output=True)
        self.assertEqual(child.returncode, 77)
        self.assertEqual(committed_files(directory), [])
        stages = stage_files(directory)
        self.assertEqual(len(stages), 1)  # the fsynced stage of the dead child
        adapter = FilePublisher(directory)
        self.assertIsNone(adapter.lookup(key))
        receipt = adapter.execute(key, document, digest(document))
        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(len(committed_files(directory)), 1)
        self.assertEqual(stage_files(directory), stages)  # stale stage untouched
        self.assertEqual(adapter.lookup(key), receipt)

    def test_death_after_commit_leaves_one_artifact_and_stable_receipt(self):
        directory = self.fresh_directory()
        document = sample_document()
        document_json = json.dumps(document)
        key = "dies-late"
        die_after_commit = (
            "import os\n"
            "os._exit(78)\n"  # outer exit right after execute() returns
        )
        body = _race_child(tail=die_after_commit)
        child = subprocess.run([sys.executable, "-c", body, directory,
                                document_json, key], capture_output=True)
        self.assertEqual(child.returncode, 78)
        self.assertEqual(len(committed_files(directory)), 1)
        self.assertEqual(stage_files(directory), [])  # own stage cleaned in finally
        artifact = read_artifact(directory, key)
        adapter = FilePublisher(directory)
        self.assertEqual(adapter.lookup(key), artifact["receipt"])
        replayed = adapter.execute(key, document, digest(document))
        self.assertEqual(replayed, artifact["receipt"])
        self.assertEqual(len(committed_files(directory)), 1)


class RuntimeDispatchTests(FileAdapterTestCase):
    """Third adapter through the unchanged Runtime: no lifecycle edits here."""

    def _send(self, runtime, work_id, kind, payload=None, actor="agent"):
        version = None if kind in ("create_work", "record_evidence") \
            else runtime.get_work(work_id)["state_version"]
        return runtime.command(actor, uuid.uuid4().hex, work_id, kind, payload, version)

    def test_third_adapter_dispatches_through_the_unchanged_lifecycle(self):
        artifacts = self.fresh_directory()
        runtime = Runtime(os.path.join(self.directory, "runtime.sqlite"),
                          PublishingPolicy(), publishing_grants())
        policy = PublishingPolicy()
        document = sample_document("ART-SMOKE")
        self._send(runtime, "smoke", "create_work", {"document": document})
        self._send(runtime, "smoke", "bind_contract",
                   {"policy_id": policy.id, "policy_version": policy.version,
                    "goal": policy.goal})
        self._send(runtime, "smoke", "record_evidence",
                   {"event_id": "rev-1", "kind": "approval",
                    "data": {"digest": digest(document)}}, actor="reviewer")
        self._send(runtime, "smoke", "record_evidence",
                   {"event_id": "auth-1", "kind": "confirmation",
                    "data": {"digest": digest(document)}}, actor="author")
        runtime.verify_pending("smoke")
        work = runtime.get_work("smoke")
        proposal = self._send(runtime, "smoke", "propose_action", {
            "capability": "content.publish", "document_digest": digest(document),
            "contract_revision": work["contract"]["revision"],
            "plan_revision": work["plan_revision"]})
        operation = runtime.get_operation(proposal["operation_id"])
        resolved = runtime.dispatch(proposal["operation_id"], FilePublisher(artifacts))
        self.assertEqual(resolved["status"], "confirmed_succeeded")
        self.assertTrue(resolved["external_id"].startswith("FILE-"))
        self.assertEqual(len(committed_files(artifacts)), 1)
        # The Runtime's business key is the adapter's idempotency key.
        artifact = read_artifact(artifacts, operation["business_key"])
        self.assertEqual(artifact["key"], operation["business_key"])
        self.assertEqual(artifact["receipt"]["external_id"], resolved["external_id"])
        work = runtime.get_work("smoke")
        c04 = [r for r in work["requirements"] if r["rule_id"] == "C04"][0]
        self.assertEqual(c04["fulfillment"], "satisfied")


if __name__ == "__main__":
    unittest.main()
