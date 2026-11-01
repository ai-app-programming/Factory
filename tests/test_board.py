import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOARD = HERE.parent / "scripts" / "board.py"


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        shutil.copy(HERE / "fake_gh.py", self.bin / "gh")
        (self.bin / "gh").chmod(0o755)
        self.env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}
        self.git("init", "-q", "-b", "develop")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "init")
        self.run_board("init")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True)

    def run_board(self, *args, cwd=None, check=True, env=None):
        result = subprocess.run(
            [sys.executable, str(BOARD), *args], cwd=cwd or self.repo,
            capture_output=True, text=True, env=env or self.env,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def github(self):
        return json.loads((self.bin / "gh-state.json").read_text())

    def write_github(self, state):
        (self.bin / "gh-state.json").write_text(json.dumps(state))

    def issue(self, number):
        return next(i for i in self.github()["issues"] if i["number"] == number)

    def labels(self, number):
        return {label["name"] for label in self.issue(number)["labels"]}

    def task(self, number):
        return json.loads(self.run_board("show", str(number)).stdout)

    def dashboard(self):
        return (self.repo / ".factory" / "dashboard.html").read_text()

    def make_outside_issue(self):
        self.run_board("add", "From a stranger")
        state = self.github()
        state["issues"][-1]["author_association"] = "NONE"
        self.write_github(state)
        return state["issues"][-1]["number"]

    def test_init_is_repeatable_and_leaves_git_clean(self):
        self.run_board("add", "Keep me")
        self.run_board("init")
        self.assertEqual(self.task(1)["title"], "Keep me")
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(status.stdout, "")
        exclude = (self.repo / ".git" / "info" / "exclude").read_text().splitlines()
        self.assertEqual(exclude.count(".factory/"), 1)

    def test_add_creates_an_issue_with_priority(self):
        self.run_board("add", "Urgent", "-d", "Details", "-p", "high")
        issue = self.issue(1)
        self.assertEqual((issue["title"], issue["body"]), ("Urgent", "Details"))
        self.assertIn("priority:high", self.labels(1))

    def test_issues_opened_on_github_appear_as_tasks_and_prs_do_not(self):
        self.run_board("add", "Seed")
        state = self.github()
        state["issues"].append({**state["issues"][0], "number": 2, "title": "Opened on the website"})
        state["issues"].append({**state["issues"][0], "number": 3, "title": "A PR", "pull_request": {}})
        self.write_github(state)
        output = self.run_board("list").stdout
        self.assertIn("Opened on the website", output)
        self.assertNotIn("A PR", output)

    def test_next_prefers_priority_then_age_and_does_not_change_state(self):
        self.run_board("add", "Old normal")
        self.run_board("add", "New high", "-p", "high")
        self.run_board("add", "Newer high", "-p", "high")
        self.assertEqual(json.loads(self.run_board("next").stdout)["title"], "New high")
        self.assertFalse(any(l.startswith("factory:") for n in (1, 2, 3) for l in self.labels(n)))

    def test_next_reports_empty_list(self):
        result = self.run_board("next", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("No approved todo tasks", result.stdout)

    def test_outside_author_is_never_picked_or_started_until_approved(self):
        number = self.make_outside_issue()
        self.assertEqual(self.run_board("next", check=False).returncode, 1)
        self.assertEqual(self.run_board("move", str(number), "plan", check=False).returncode, 1)
        self.assertIn("unapproved", self.run_board("list").stdout)
        self.run_board("approve", str(number))
        self.assertEqual(json.loads(self.run_board("next").stdout)["number"], number)
        self.run_board("move", str(number), "plan")

    def test_stage_is_stored_on_the_issue_and_survives_a_lost_cache(self):
        self.run_board("add", "One")
        self.run_board("move", "#1", "implement")
        self.run_board("move", "1", "verify")
        self.assertEqual({l for l in self.labels(1) if l.startswith("factory:")}, {"factory:verify"})
        (self.repo / ".factory" / "tasks.json").write_text('{"tasks": []}')
        self.assertEqual(self.task(1)["status"], "verify")

    def test_three_failures_retry_and_the_fourth_needs_a_human(self):
        self.run_board("add", "One")
        self.run_board("move", "1", "verify")
        for count in (1, 2, 3):
            result = self.run_board("fail", "1", f"Round {count}")
            self.assertTrue(result.stdout.strip().endswith("RETRY"))
            self.assertEqual(self.task(1)["failures"], count)
        self.assertEqual({l for l in self.labels(1) if "failures" in l}, {"factory:failures-3"})
        result = self.run_board("fail", "1", "Round 4")
        self.assertTrue(result.stdout.strip().endswith("HUMAN"))
        task = self.task(1)
        self.assertEqual((task["status"], task["human_stage"]), ("human", "verify"))
        self.assertIn("factory:human", self.labels(1))
        self.assertNotIn("factory:verify", self.labels(1))
        self.assertIn("Round 4", self.github()["comments"][-1]["body"])
        self.assertIn("Human interaction needed", self.dashboard())

    def test_merge_failure_goes_straight_to_human(self):
        self.run_board("add", "One")
        self.run_board("move", "1", "merge")
        self.run_board("human", "1", "Conflict in a.py")
        self.assertEqual(self.task(1)["status"], "human")
        self.assertIn("Conflict in a.py", self.dashboard())
        self.assertIn("Conflict in a.py", self.github()["comments"][-1]["body"])

    def test_retry_from_human_resets_failures(self):
        self.run_board("add", "One")
        self.run_board("move", "1", "verify")
        for count in range(4):
            self.run_board("fail", "1", "Again")
        self.run_board("move", "1", "implement")
        task = self.task(1)
        self.assertEqual((task["status"], task["failures"], task["human_reason"]), ("implement", 0, None))
        self.assertTrue(self.run_board("fail", "1", "New").stdout.strip().endswith("RETRY"))

    def test_person_removing_human_label_on_github_returns_task(self):
        self.run_board("add", "One")
        self.run_board("human", "1", "Help")
        state = self.github()
        state["issues"][0]["labels"] = []
        self.write_github(state)
        self.assertEqual(self.task(1)["status"], "todo")

    def test_ux_stage_has_a_column_and_counts_as_running(self):
        self.run_board("add", "One")
        self.run_board("move", "1", "ux")
        page = self.dashboard()
        for name in ["Todo", "Plan", "Implement", "Cleanup", "Verify", "UI/UX verify", "Merge",
                     "Human interaction needed", "Done"]:
            self.assertIn(f"<h2>{name} ", page)
        self.assertIn("1 running", page)

    def test_done_stays_open_until_closed_then_stays_on_board(self):
        self.run_board("add", "One")
        self.run_board("move", "1", "done")
        self.assertEqual(self.issue(1)["state"], "open")
        self.assertEqual(self.task(1)["status"], "done")
        self.run_board("close", "1", "--comment", "Merged")
        self.assertEqual(self.issue(1)["state"], "closed")
        self.assertEqual(self.task(1)["status"], "done")

    def test_unfinished_task_cannot_close_as_completed(self):
        self.run_board("add", "One")
        self.assertEqual(self.run_board("close", "1", "--comment", "x", check=False).returncode, 1)
        self.assertEqual(self.issue(1)["state"], "open")

    def test_not_planned_close_leaves_the_board(self):
        self.run_board("add", "One")
        self.run_board("close", "1", "--comment", "Dropped", "--not-planned")
        self.assertEqual(self.run_board("list").stdout.strip(), "No tasks")

    def test_edit_updates_issue_and_priority(self):
        self.run_board("add", "One", "-p", "high")
        self.run_board("edit", "1", "--title", "Renamed", "-p", "low", "--branch", "factory/1-x")
        self.assertEqual(self.issue(1)["title"], "Renamed")
        self.assertEqual(self.labels(1), {"priority:low"})
        self.assertEqual(self.task(1)["branch"], "factory/1-x")

    def test_list_status_keeps_active_tasks_visible_and_hides_other_stages(self):
        self.run_board("add", "Waiting")
        self.run_board("add", "Running")
        self.run_board("move", "2", "verify")
        self.run_board("add", "Finished")
        self.run_board("move", "3", "done")
        output = self.run_board("list", "--status", "todo").stdout
        self.assertIn("Waiting", output)
        self.assertNotIn("Finished", output)
        self.assertIn("Running", output)

    def test_dashboard_escapes_issue_text(self):
        self.run_board("add", "<script>alert(1)</script>")
        self.assertNotIn("<script>", self.dashboard())
        self.assertIn("&lt;script&gt;", self.dashboard())

    def test_dashboard_refuses_non_https_links(self):
        self.run_board("add", "One")
        state = self.github()
        state["issues"][0]["html_url"] = "javascript:alert(1)"
        self.write_github(state)
        self.run_board("render")
        self.assertNotIn("javascript:", self.dashboard())

    def test_worktree_shares_the_main_board(self):
        worktree = Path(self.tmp.name) / "wt"
        self.git("worktree", "add", "-q", str(worktree), "-b", "feature")
        self.run_board("add", "From worktree", cwd=worktree)
        self.assertEqual(self.task(1)["title"], "From worktree")
        self.assertFalse((worktree / ".factory").exists())

    def test_parallel_adds_lose_nothing(self):
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda n: self.run_board("add", f"Task {n}"), range(16)))
        self.assertEqual(len(self.github()["issues"]), 16)

    def test_missing_gh_fails_cleanly(self):
        path = "/usr/bin:/bin"
        if shutil.which("gh", path=path):
            self.skipTest("real gh installed")
        result = self.run_board("list", check=False, env={**self.env, "PATH": path})
        self.assertEqual(result.returncode, 1)
        self.assertIn("GitHub CLI", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_outside_git_repo_fails_cleanly(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        result = self.run_board("list", cwd=outside, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not inside a git repository", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
