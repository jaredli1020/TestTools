import subprocess
import tempfile
import unittest
from pathlib import Path

from casecraft.analyzers.local_git import LocalGitAnalyzer, RepositorySyncError
from casecraft.core import Requirement


class LocalGitAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = LocalGitAnalyzer()

    def test_auto_router_prefers_explicit_client_keyword(self):
        requirement = Requirement(title="移动端登录", content="H5 手机端新增验证码登录页面")
        auto = {
            "candidates": ["admin", "h5", "backend", "web"],
            "default_candidate": "web",
        }
        projects = {
            "admin": {"routing_keywords": ["管理后台"], "path": "missing-admin"},
            "h5": {"routing_keywords": ["h5", "手机端"], "path": "missing-h5"},
            "backend": {"routing_keywords": ["后端", "java"], "path": "missing-backend"},
            "web": {"routing_keywords": ["pc端", "react"], "path": "missing-web"},
        }

        selected, routing = self.analyzer.resolve_project(requirement, auto, projects)

        self.assertEqual(selected, "h5")
        self.assertEqual(routing["confidence"], "high")
        self.assertGreater(routing["scores"]["h5"], routing["scores"]["web"])

    def test_sync_fast_forwards_to_upstream_latest_commit(self):
        with tempfile.TemporaryDirectory(prefix="casecraft-git-") as temp_dir:
            _, seed, working = self._create_git_fixture(Path(temp_dir))
            target = seed / "src" / "BookingService.java"
            target.write_text("class BookingService { int version = 2; }\n", encoding="utf-8")
            self._git(seed, "add", ".")
            self._git(seed, "commit", "-m", "remote update")
            self._git(seed, "push")

            state = self.analyzer.sync_repository(working, sync=True)

            self.assertTrue(state["verified_latest"])
            self.assertEqual(state["behind"], 0)
            self.assertEqual(state["sync_status"], "fast_forwarded")
            self.assertIn("version = 2", (working / "src" / "BookingService.java").read_text(encoding="utf-8"))

    def test_dirty_behind_repository_is_never_overwritten(self):
        with tempfile.TemporaryDirectory(prefix="casecraft-git-") as temp_dir:
            _, seed, working = self._create_git_fixture(Path(temp_dir))
            local_file = working / "src" / "BookingService.java"
            local_file.write_text("class BookingService { String local = \"keep\"; }\n", encoding="utf-8")

            remote_file = seed / "src" / "BookingService.java"
            remote_file.write_text("class BookingService { String remote = \"new\"; }\n", encoding="utf-8")
            self._git(seed, "add", ".")
            self._git(seed, "commit", "-m", "remote change")
            self._git(seed, "push")

            with self.assertRaisesRegex(RepositorySyncError, "未提交改动"):
                self.analyzer.sync_repository(working, sync=True)

            self.assertIn("local = \"keep\"", local_file.read_text(encoding="utf-8"))

    def test_context_contains_only_relevant_tracked_source(self):
        with tempfile.TemporaryDirectory(prefix="casecraft-git-") as temp_dir:
            _, _, working = self._create_git_fixture(Path(temp_dir))
            repository = self.analyzer.sync_repository(working, sync=False)
            repository["project_key"] = "backend"

            content, matched = self.analyzer.extract_context(
                Requirement(title="酒店预订", content="新增酒店 Booking 订单校验"),
                working,
                repository,
                max_files=10,
                max_chars_per_file=4000,
                max_total_chars=12000,
            )

            self.assertIn("src/BookingService.java", matched)
            self.assertIn("当前分支: main", content)
            self.assertIn("BookingService", content)

    def _create_git_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        remote = root / "remote.git"
        seed = root / "seed"
        working = root / "working"

        self._git(root, "init", "--bare", str(remote))
        seed.mkdir()
        self._git(seed, "init", "-b", "main")
        self._git(seed, "config", "user.name", "CaseCraft Test")
        self._git(seed, "config", "user.email", "casecraft@example.invalid")
        (seed / "src").mkdir()
        (seed / "src" / "BookingService.java").write_text(
            "class BookingService { int version = 1; }\n",
            encoding="utf-8",
        )
        self._git(seed, "add", ".")
        self._git(seed, "commit", "-m", "initial")
        self._git(seed, "remote", "add", "origin", str(remote))
        self._git(seed, "push", "-u", "origin", "main")
        self._git(root, "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
        self._git(root, "clone", str(remote), str(working))
        return remote, seed, working

    @staticmethod
    def _git(cwd: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)
        return completed.stdout


if __name__ == "__main__":
    unittest.main()
