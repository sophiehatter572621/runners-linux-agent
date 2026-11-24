import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import unittest

spec = importlib.util.spec_from_file_location("run_agent", Path(__file__).parents[1] / "scripts/run_agent.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def archive(extra=None, symlink=False):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w") as bundle:
        for name in ["Dockerfile", "bin/runner-agent-linux-amd64", "bin/runner-agent-linux-arm64"] + ([extra] if extra else []):
            entry = tarfile.TarInfo(name)
            data = b"sample native agent"
            entry.size = len(data)
            if symlink and name.endswith("amd64"):
                entry.type = tarfile.SYMTYPE
                entry.linkname = "/etc/passwd"
            bundle.addfile(entry, io.BytesIO(data))
    data = result.getvalue()
    return data, hashlib.sha256(data).hexdigest()


class BootstrapTests(unittest.TestCase):
    def test_verified_bundle(self):
        self.assertEqual(agent.extract_binary(*archive()), b"sample native agent")

    def test_checksum_and_unsafe_members(self):
        data, digest = archive()
        with self.assertRaises(ValueError):
            agent.extract_binary(data + b"changed", digest)
        for pair in [archive("../../outside"), archive(symlink=True)]:
            with self.assertRaises(ValueError):
                agent.extract_binary(*pair)

    def test_agent_gets_literal_credentials_without_github_job_tokens(self):
        token = "sample' token; $(printf unexpected)"
        env = agent.agent_environment("https://fleet.example", token, "github-linux", "Linux #1", 330, b"binary", Path("/tmp/agent"),
                                      {"PATH": "/usr/bin", "GITHUB_TOKEN": "private", "ACTIONS_RUNTIME_TOKEN": "private"})
        self.assertEqual(env["JOIN_TOKEN"], token)
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("ACTIONS_RUNTIME_TOKEN", env)

    def test_reject_bad_origin_and_oversized_lease(self):
        for origin in ["http://fleet.example", "https://token@fleet.example", "https://fleet.example/path"]:
            with self.assertRaises(ValueError):
                agent.configuration({"CONTROL_URL": origin, "JOIN_TOKEN": "sample"})
        with self.assertRaises(ValueError):
            agent.configuration({"CONTROL_URL": "https://fleet.example", "JOIN_TOKEN": "sample", "MAX_RUNTIME_MINUTES": "360"})

    def test_only_the_live_matching_agent_counts(self):
        status = {"runs": [{"id": "other", "label": "other", "live": True}, {"id": "old", "label": "mine", "live": False}, {"id": "new", "label": "mine", "live": True}]}
        self.assertEqual(agent.find_run(status, "mine")["id"], "new")

    def test_worker_slots_have_distinct_labels_in_the_same_account_pool(self):
        env = {"CONTROL_URL": "https://fleet.example", "JOIN_TOKEN": "sample",
               "SERVER_TAG": "github-linux", "GITHUB_REPOSITORY": "owner/agent", "GITHUB_RUN_ID": "42"}
        first = agent.configuration(env)
        second = agent.configuration({**env, "WORKER_SLOT": "2"})
        self.assertEqual(first[3], second[3])
        self.assertEqual(first[4], "GitHub Linux owner/agent #42")
        self.assertEqual(second[4], "GitHub Linux owner/agent worker 2 #42")
        for slot in ["0", "3", "2; unexpected"]:
            with self.assertRaises(ValueError):
                agent.configuration({**env, "WORKER_SLOT": slot})


if __name__ == "__main__":
    unittest.main()
