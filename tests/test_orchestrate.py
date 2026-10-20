import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orchestrate as orch


def approved(task=None):
    task = task or orch.demo_task()
    return {"decision": "approve", "summary": "verified", "findings": [],
            "acceptance": [{"id": c["id"], "verdict": "pass", "evidence": "test logs and source"}
                           for c in task["acceptance"]]}


class GateTests(unittest.TestCase):
    def test_fail_closed_on_failed_timed_out_and_empty_tests(self):
        review = approved()
        self.assertTrue(orch.ready(review, [{"exit_code": 0, "timed_out": False}]))
        for tests in ([], [{"exit_code": 1, "timed_out": False}], [{"exit_code": 0, "timed_out": True}]):
            with self.subTest(tests=tests):
                self.assertFalse(orch.ready(review, tests))

    def test_blocking_major_unknown_and_rejection_do_not_pass(self):
        tests = [{"exit_code": 0, "timed_out": False}]
        for severity in ("blocking", "major", "minor"):
            review = approved()
            review["findings"] = [{"severity": severity}]
            self.assertEqual(orch.ready(review, tests), severity == "minor")
        review = approved()
        review["acceptance"][0]["verdict"] = "unknown"
        self.assertFalse(orch.ready(review, tests))
        review = approved()
        review["decision"] = "request_changes"
        self.assertFalse(orch.ready(review, tests))
        review["acceptance"] = []
        self.assertFalse(orch.ready(review, tests))

    def test_missing_duplicate_and_invented_acceptance_rejected(self):
        for ids in (["AC1"], ["AC1", "AC1"], ["AC1", "AC2", "AC3"]):
            review = approved()
            review["acceptance"] = [{"id": key, "verdict": "pass", "evidence": "e"} for key in ids]
            with self.subTest(ids=ids), self.assertRaises(orch.WorkflowError):
                orch.check_review(review, orch.demo_task())

    def test_malformed_schema_rejected(self):
        for change in ({"decision": "looks good"}, {"findings": "none"}, {"summary": " "}):
            review = approved()
            review.update(change)
            with self.subTest(change=change), self.assertRaises(orch.WorkflowError):
                orch.validate(review, orch.REVIEW_SCHEMA)
        review = approved()
        review["extra"] = True
        with self.assertRaises(orch.WorkflowError):
            orch.validate(review, orch.REVIEW_SCHEMA)

    def test_task_empty_tests_and_duplicate_ids_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task.json"
            for bad in (dict(orch.demo_task(), tests=[]), dict(orch.demo_task(), max_rounds=True),
                        dict(orch.demo_task(), acceptance=[{"id": "X", "description": "x"}] * 2)):
                orch.write_json(path, bad)
                with self.assertRaises(orch.WorkflowError):
                    orch.load_task(path)


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="编排测试 space-")
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        orch.create_demo_repo(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def flow(self, agents=None, task=None):
        return orch.Workflow(task or orch.demo_task(), self.source, self.root / "run",
                             agents or orch.DemoAgents(), demo=True)

    def execute(self, flow):
        with contextlib.redirect_stdout(io.StringIO()):
            return flow.run()


class WorkflowTests(RepoCase):
    def test_real_git_tests_and_two_round_repair(self):
        original = (self.source / "calculator.py").read_bytes()
        flow = self.flow()
        self.assertEqual(self.execute(flow), 0)
        state = orch.read_json(flow.run_dir / "state.json")
        self.assertEqual(state["status"], "demo_ready")
        self.assertTrue(state["demo"])
        self.assertEqual(len(state["rounds"]), 2)
        self.assertNotEqual(state["rounds"][0]["tests"][0]["exit_code"], 0)
        self.assertEqual(state["rounds"][1]["tests"][0]["exit_code"], 0)
        self.assertEqual((self.source / "calculator.py").read_bytes(), original)
        self.assertEqual(orch.git(self.source, "status", "--porcelain"), b"")
        self.assertIn("ValueError", (flow.run_dir / "round-02/changes.patch").read_text(encoding="utf-8"))
        prompt = (flow.run_dir / "round-02/implementation/prompt.txt").read_text(encoding="utf-8")
        self.assertIn("requested_fix", prompt)
        self.assertIn("exit_code", prompt)
        self.assertIn("演示", (flow.run_dir / "REPORT.md").read_text(encoding="utf-8"))

    def test_loop_limit_does_not_claim_success(self):
        flow = self.flow(task=dict(orch.demo_task(), max_rounds=1))
        self.assertEqual(self.execute(flow), 2)
        self.assertEqual(orch.read_json(flow.run_dir / "state.json")["status"], "needs_attention")

    def test_false_approval_cannot_override_test_failure(self):
        class Liar(orch.DemoAgents):
            def call(self, role, *args):
                if role == "claude-review":
                    return approved()
                return super().call(role, *args)
        flow = self.flow(Liar(), dict(orch.demo_task(), max_rounds=1))
        self.assertEqual(self.execute(flow), 2)

    def test_review_modifying_code_invalidates_result(self):
        class MutatingReviewer(orch.DemoAgents):
            def call(self, role, prompt, schema, repo, folder, timeout):
                answer = super().call(role, prompt, schema, repo, folder, timeout)
                if role == "claude-review":
                    (repo / "calculator.py").write_text("# changed after tests\n", encoding="utf-8")
                return answer
        flow = self.flow(MutatingReviewer())
        self.assertEqual(self.execute(flow), 1)
        self.assertIn("审查期间", flow.state["message"])

    def test_blocked_plan_stops_before_implementation(self):
        class Blocked(orch.DemoAgents):
            def call(self, role, *args):
                if role != "claude-plan":
                    raise AssertionError("implementation must not run")
                return {"status": "blocked", "summary": "need input", "steps": [], "risks": [], "questions": ["which behavior?"]}
        flow = self.flow(Blocked())
        self.assertEqual(self.execute(flow), 2)
        self.assertEqual(flow.state["status"], "blocked")
        self.assertEqual(flow.state["rounds"], [])

    def test_test_that_modifies_code_is_rejected(self):
        task = orch.demo_task()
        task["tests"] = [{"name": "mutating test", "argv": ["{python}", "-c",
                          "from pathlib import Path; Path('calculator.py').write_text('# changed')"], "timeout_seconds": 10}]
        flow = self.flow(task=task)
        self.assertEqual(self.execute(flow), 1)
        self.assertIn("测试改变", flow.state["message"])

    def test_dirty_source_is_preserved(self):
        (self.source / "calculator.py").write_text("# user work", encoding="utf-8")
        flow = self.flow()
        self.assertEqual(self.execute(flow), 1)
        self.assertEqual((self.source / "calculator.py").read_text(), "# user work")
        self.assertFalse(flow.repo.exists())

    def test_agent_error_keeps_report_and_does_not_pass(self):
        class Broken(orch.DemoAgents):
            def call(self, *args):
                raise orch.WorkflowError("invalid response")
        flow = self.flow(Broken())
        self.assertEqual(self.execute(flow), 1)
        self.assertEqual(flow.state["status"], "error")
        self.assertTrue((flow.run_dir / "REPORT.md").exists())

    def test_production_status_is_distinct_and_requires_authentication(self):
        class TestAgents(orch.DemoAgents):
            def preflight(self, folder):
                return {"codex": {"authenticated": True}, "claude": {"authenticated": True}}
        # These are test doubles, only used to exercise the production control path.
        flow = orch.Workflow(orch.demo_task(), self.source, self.root / "run", TestAgents(), demo=False)
        self.assertEqual(self.execute(flow), 0)
        self.assertEqual(flow.state["status"], "ready_for_acceptance")
        self.assertFalse(flow.state["demo"])

    def test_missing_cli_auth_stops_before_worktree_or_model_calls(self):
        class Unauthenticated(orch.DemoAgents):
            def preflight(self, folder):
                return {"codex": {"authenticated": True}, "claude": {"authenticated": False}}

            def call(self, *args):
                raise AssertionError("must not call model before authentication")
        flow = orch.Workflow(orch.demo_task(), self.source, self.root / "run", Unauthenticated(), demo=False)
        self.assertEqual(self.execute(flow), 1)
        self.assertFalse(flow.repo.exists())
        self.assertIn("未登录", flow.state["message"])

    def test_diff_includes_new_and_staged_files_without_mutating_index(self):
        base = orch.text_git(self.source, "rev-parse", "HEAD")
        (self.source / "新增文件.txt").write_text("untracked payload\n", encoding="utf-8")
        (self.source / "calculator.py").write_text("# staged change\n", encoding="utf-8")
        orch.git(self.source, "add", "calculator.py")
        before = orch.git(self.source, "diff", "--cached")
        folder = self.root / "diff"
        folder.mkdir()
        orch.make_diff(self.source, base, folder)
        diff = (folder / "changes.patch").read_text(encoding="utf-8")
        self.assertIn("untracked payload", diff)
        self.assertIn("# staged change", diff)
        self.assertEqual(orch.git(self.source, "diff", "--cached"), before)
        self.assertFalse((folder / "audit.index").exists())


class ProcessTests(unittest.TestCase):
    def test_argv_keeps_unicode_spaces_and_shell_metacharacters_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = '中文 space & $(do-not-execute) ` " \\ ;'
            result = orch.run_process([sys.executable, "-c", "import sys; print(sys.argv[1])", payload],
                                      Path(tmp), Path(tmp) / "logs", 10)
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(Path(result["stdout"]).read_text(encoding="utf-8").strip(), payload)

    def test_timeout_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = orch.run_process([sys.executable, "-c", "import time; time.sleep(30)"],
                                      Path(tmp), Path(tmp) / "logs", 1)
            self.assertTrue(result["timed_out"])
            self.assertNotEqual(result["exit_code"], 0)

    def test_parent_routing_and_test_credentials_removed(self):
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "parent", "CODEX_API_KEY": "secret",
                                    "ANTHROPIC_API_KEY": "secret", "CLAUDECODE": "1"}):
            agent = orch.child_env()
            self.assertNotIn("CODEX_THREAD_ID", agent)
            self.assertNotIn("CLAUDECODE", agent)
            self.assertEqual(agent["CODEX_API_KEY"], "secret")
            test = orch.child_env(for_test=True)
            self.assertNotIn("CODEX_API_KEY", test)
            self.assertNotIn("ANTHROPIC_API_KEY", test)


class ProtocolTests(unittest.TestCase):
    def test_actual_subprocess_adapters_and_structured_claude_envelope(self):
        with tempfile.TemporaryDirectory(prefix="协议 space-") as tmp:
            root = Path(tmp)
            fake = root / "fake_cli.py"
            fake.write_text('''import json, pathlib, sys
role = sys.argv[1]
args = sys.argv[2:]
if "--version" in args:
    print("fake 1.0")
elif "--help" in args:
    print("--output-schema --sandbox --json --ephemeral --json-schema --safe-mode --permission-prompts --strict-mcp-config")
elif "status" in args:
    print(json.dumps({"loggedIn": True}))
else:
    prompt = sys.stdin.read()
    assert "中文 & $()" in prompt
    if role == "codex":
        answer = {"summary": "ok", "changes": [], "tests_run": [], "limitations": []}
        pathlib.Path(args[args.index("--output-last-message") + 1]).write_text(json.dumps(answer), encoding="utf-8")
        print(json.dumps({"type": "turn.completed"}))
    else:
        schema = json.loads(args[args.index("--json-schema") + 1])
        assert schema["additionalProperties"] is False
        assert args[args.index("--tools") + 1] == "Read,Glob,Grep"
        answer = {"status": "ready", "summary": "ok", "steps": [], "risks": [], "questions": []}
        print(json.dumps({"subtype": "success", "is_error": False, "structured_output": answer}))
''', encoding="utf-8")
            agents = orch.Agents({name: [sys.executable, str(fake), name] for name in ("codex", "claude")})
            details = agents.preflight(root / "doctor")
            self.assertTrue(all(x["authenticated"] for x in details.values()))
            codex = agents.call("codex", "中文 & $()", orch.IMPLEMENT_SCHEMA, root, root / "impl", 10)
            claude = agents.call("claude-plan", "中文 & $()", orch.PLAN_SCHEMA, root, root / "plan", 10)
            self.assertEqual(codex["summary"], "ok")
            self.assertEqual(claude["status"], "ready")

    def test_claude_success_without_structured_output_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "bad.py"
            fake.write_text('import json; print(json.dumps({"subtype":"success", "result":"approved"}))', encoding="utf-8")
            agents = orch.Agents({name: [sys.executable, str(fake)] for name in ("codex", "claude")})
            with self.assertRaises(orch.WorkflowError):
                agents.call("claude-review", "review", orch.REVIEW_SCHEMA, root, root / "call", 10)


class BusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="总线 space-")
        self.bus = orch.Bus(Path(self.temp.name) / "bus")

    def tearDown(self):
        self.temp.cleanup()

    def test_send_wait_cursor_and_corrupt_line(self):
        self.bus.send("claude", "codex", "第一条 & $()")
        with self.bus.log.open("a", encoding="utf-8") as stream:
            stream.write("{broken\n")
        self.bus.send("claude", "all", "广播")
        self.assertEqual([m["text"] for m in self.bus.wait("codex", 1)], ["第一条 & $()", "广播"])
        self.assertEqual(self.bus.wait("codex", 0), [])
        self.assertEqual([m["id"] for m in self.bus.history(10)], [1, 2])
        self.assertFalse(self.bus.lock_path.exists())

    def test_ask_matches_reply_and_times_out(self):
        def answer():
            question = self.bus.wait("claude", 5)[0]
            self.bus.send("claude", "codex", "无关消息")
            self.bus.send("claude", "codex", "回答", reply_to=question["id"])
        thread = orch.threading.Thread(target=answer)
        thread.start()
        self.assertEqual(self.bus.ask("codex", "claude", "问题", 10)["text"], "回答")
        thread.join()
        self.assertIsNone(self.bus.ask("codex", "claude", "没人回答", 0.6))

    def test_mcp_server_handshake_and_tools(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "send", "arguments": {"text": "你好"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "unknown/method"},
        ]
        out = io.StringIO()
        orch.serve_bus_mcp(self.bus, "codex", "claude",
                           io.StringIO("".join(json.dumps(r) + "\n" for r in requests)), out)
        responses = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([r["id"] for r in responses], [1, 2, 3, 4, 5])
        self.assertEqual({t["name"] for t in responses[1]["result"]["tools"]}, {"ask", "send", "wait", "history"})
        self.assertEqual(self.bus.history(1)[0]["to"], "claude")
        self.assertTrue(responses[3]["result"]["isError"])
        self.assertEqual(responses[4]["error"]["code"], -32601)

    def test_codex_argv_mounts_bus_only_when_round_enables_it(self):
        recorded = []
        agents = orch.Agents.__new__(orch.Agents)
        agents.config, agents.codex, agents.claude = {}, ["codex"], ["claude"]
        def fake_run(argv, cwd, folder, timeout, prompt=None, for_test=False):
            recorded.append(argv)
            orch.write_json(Path(folder) / "answer.json",
                            {"summary": "ok", "changes": [], "tests_run": [], "limitations": []})
            return {"exit_code": 0, "timed_out": False}
        root = Path(self.temp.name)
        with patch.object(orch, "run_process", fake_run):
            agents.call("codex", "p", orch.IMPLEMENT_SCHEMA, root, root / "r1" / "implementation", 10)
            (root / "r2" / "bus").mkdir(parents=True)
            agents.call("codex", "p", orch.IMPLEMENT_SCHEMA, root, root / "r2" / "implementation", 10)
        self.assertNotIn("bus-mcp", " ".join(recorded[0]))
        joined = " ".join(recorded[1])
        self.assertIn("bus-mcp", joined)
        self.assertIn(str(root / "r2" / "bus").replace("\\", "\\\\"), joined)
        self.assertEqual(recorded[1][-1], "-")


class AskingAgents(orch.DemoAgents):
    """模拟 Codex 在实施中经 MCP 等价路径（Bus.ask）提问。"""

    def __init__(self, questions=1, broken_answer=False):
        super().__init__()
        self.questions, self.broken_answer, self.replies = questions, broken_answer, []

    def call(self, role, prompt, schema, repo, folder, timeout):
        if role == "codex":
            bus = orch.Bus(folder.parent / "bus")
            for index in range(self.questions):
                self.replies.append(bus.ask("codex", "claude", f"除零怎么处理？#{index}", 10))
        if role == "claude-answer" and self.broken_answer:
            raise orch.WorkflowError("answer failed")
        return super().call(role, prompt, schema, repo, folder, timeout)


class RealtimeWorkflowTests(RepoCase):
    def test_question_answered_recorded_and_gate_unchanged(self):
        agents = AskingAgents()
        flow = self.flow(agents)
        self.assertEqual(self.execute(flow), 0)
        self.assertIn("ValueError", agents.replies[0]["text"])
        first = flow.state["rounds"][0]
        self.assertEqual(first["questions"][0]["status"], "answered")
        self.assertTrue((Path(first["folder"]) / "questions/q-01/prompt.txt").exists())
        prompt = (Path(first["folder"]) / "implementation/prompt.txt").read_text(encoding="utf-8")
        self.assertIn("bus 的 ask", prompt)
        report = (flow.run_dir / "REPORT.md").read_text(encoding="utf-8")
        self.assertIn("Codex 提问", report)
        self.assertIn("AC2", report)
        conversation = (flow.run_dir / "CONVERSATION.md").read_text(encoding="utf-8")
        for expected in ("除数为零时抛出 ValueError", "你是实施者", "除零怎么处理？#0",
                         "[模拟] 除零应抛出 ValueError", "Claude 审查意见", "上一轮真实测试及独立审查"):
            self.assertIn(expected, conversation)
        self.assertEqual(len(flow.state["rounds"]), 2)  # 回答不会替代真实测试和审查

    def test_question_limit_and_answer_failure_do_not_stop_run(self):
        agents = AskingAgents(questions=2, broken_answer=True)
        flow = self.flow(agents, dict(orch.demo_task(), max_questions=1))
        self.assertEqual(self.execute(flow), 0)
        statuses = [q["status"] for q in flow.state["rounds"][0]["questions"]]
        self.assertEqual(statuses, ["error", "limit"])
        self.assertTrue(all(reply is not None for reply in agents.replies))

    def test_zero_questions_disables_bus(self):
        flow = self.flow(task=dict(orch.demo_task(), max_questions=0))
        self.assertEqual(self.execute(flow), 0)
        self.assertFalse((flow.run_dir / "round-01/bus").exists())
        self.assertNotIn("questions", flow.state["rounds"][0])

    def test_task_validates_max_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task.json"
            for value in (-1, 21, "3"):
                orch.write_json(path, dict(orch.demo_task(), max_questions=value))
                with self.assertRaises(orch.WorkflowError):
                    orch.load_task(path)
            orch.write_json(path, orch.demo_task())
            self.assertEqual(orch.load_task(path)["max_questions"], 5)


if __name__ == "__main__":
    unittest.main()
