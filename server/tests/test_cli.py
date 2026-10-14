import io
import json
import shlex
import sys
import time
from types import SimpleNamespace

from airspace import cli
from airspace.hooks.handlers import Deps
from airspace.types import EditAnalysis, Verdict

PRE = f"{shlex.quote(sys.executable)} -m airspace.cli hook pre"
POST = f"{shlex.quote(sys.executable)} -m airspace.cli hook post"
ANY = f"{shlex.quote(sys.executable)} -m airspace.cli hook any"
ANY_MATCHER = "Bash|Read|Grep|Glob|Task|WebFetch|WebSearch|NotebookEdit"


def read_settings(root):
    return json.loads((root / ".claude" / "settings.json").read_text())


def commands(settings, event):
    return [h["command"] for entry in settings["hooks"].get(event, []) for h in entry.get("hooks", [])]


def test_install_hooks_creates_settings(tmp_path, capsys):
    assert cli.main(["install-hooks", "--root", str(tmp_path)]) == 0
    s = read_settings(tmp_path)
    assert s["hooks"]["PreToolUse"] == [
        {"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": PRE}]},
        {"matcher": ANY_MATCHER, "hooks": [{"type": "command", "command": ANY}]},
    ]
    assert s["hooks"]["PostToolUse"] == [
        {"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": POST}]}
    ]
    assert str(tmp_path / ".claude" / "settings.json") in capsys.readouterr().out


def test_install_hooks_merges_existing_settings(tmp_path):
    existing = {
        "permissions": {"allow": ["Bash(npm test)"]},
        "env": {"FOO": "1"},
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "./guard.sh"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
        },
    }
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(existing))

    assert cli.main(["install-hooks", "--root", str(tmp_path)]) == 0
    s = read_settings(tmp_path)
    assert s["permissions"] == existing["permissions"]
    assert s["env"] == existing["env"]
    assert s["hooks"]["Stop"] == existing["hooks"]["Stop"]
    assert s["hooks"]["PreToolUse"][0] == existing["hooks"]["PreToolUse"][0]
    assert commands(s, "PreToolUse") == ["./guard.sh", PRE, ANY]
    assert commands(s, "PostToolUse") == [POST]


def test_install_hooks_is_idempotent(tmp_path):
    assert cli.main(["install-hooks", "--root", str(tmp_path)]) == 0
    first = read_settings(tmp_path)
    assert cli.main(["install-hooks", "--root", str(tmp_path)]) == 0
    assert read_settings(tmp_path) == first


def test_install_hooks_recognises_an_existing_airspace_command(tmp_path):
    existing = {
        "hooks": {
            "PreToolUse": [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "airspace hook pre"}]}],
        }
    }
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(existing))
    assert cli.main(["install-hooks", "--root", str(tmp_path)]) == 0
    s = read_settings(tmp_path)
    assert commands(s, "PreToolUse") == ["airspace hook pre", ANY]
    assert commands(s, "PostToolUse") == [POST]


def test_install_hooks_adds_any_hook(tmp_path, capsys):
    # A settings file from before the any hook existed: pre and post are kept, the any hook is added once.
    existing = {
        "hooks": {
            "PreToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": PRE}]}],
            "PostToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": POST}]}],
        }
    }
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(existing))

    assert cli.main(["install-hooks", "--root", str(tmp_path)]) == 0
    s = read_settings(tmp_path)
    assert s["hooks"]["PreToolUse"][1] == {"matcher": ANY_MATCHER, "hooks": [{"type": "command", "command": ANY}]}
    assert commands(s, "PreToolUse") == [PRE, ANY]
    assert commands(s, "PostToolUse") == [POST]
    assert "hook any" in capsys.readouterr().out

    assert cli.main(["install-hooks", "--root", str(tmp_path)]) == 0
    assert commands(read_settings(tmp_path), "PreToolUse") == [PRE, ANY]


def test_cli_hook_any_roundtrip(tmp_path, monkeypatch, capsys):
    from airspace.types import Briefing

    class Briefs:
        def pending_briefings(self, task_id):
            return [Briefing("cc", "utils.text.slugify", "slugify(value, allow_unicode=False)",
                             "slugify(value, *, unicode=False)", "agent-a", "blog.views.render_post")]

        def pending_messages(self, agent_id, task_id=None):
            return []

    deps = fake_deps()
    deps.airspace = lambda root: Briefs()
    monkeypatch.setattr(cli, "_deps", lambda: deps)
    payload = {"session_id": "bbbb1111", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {"command": "pytest"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert cli.main(["hook", "any"]) == 0
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert "slugify(value, *, unicode=False)" in out["additionalContext"]
    assert "blog.views.render_post" in out["additionalContext"]


class HoldingAirspace:
    def ensure_task(self, agent_id, task_id, intent=""):
        pass

    def check_edit(self, task_id, touched, new_calls, call_shapes=None):
        return Verdict("hold", "Airspace hold: utils.text.slugify is being changed by agent-a.")

    def pending_briefings(self, task_id):
        return []


def fake_deps():
    analysis = EditAnalysis(
        file="blog/views.py",
        touched=["blog.views.render_post"],
        new_calls=[("blog.views.render_post", "utils.text.slugify")],
        parse_ok=True,
    )
    return Deps(
        airspace=lambda root: HoldingAirspace(),
        analyze=lambda root, tool, tool_input, known: analysis,
        known=lambda root: {"utils.text.slugify"},
        reindex=lambda root, rel: [],
    )


def test_cli_hook_pre_roundtrip(tmp_path, monkeypatch, capsys):
    payload = {
        "session_id": "bbbb1111",
        "cwd": str(tmp_path),
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(tmp_path / "blog/views.py"), "old_string": "a", "new_string": "b"},
        "tool_use_id": "toolu_1",
    }
    monkeypatch.setattr(cli, "_deps", fake_deps)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert cli.main(["hook", "pre"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Airspace hold: utils.text.slugify is being changed by agent-a.",
        }
    }


def test_cli_hook_cleared_prints_nothing(tmp_path, monkeypatch, capsys):
    payload = {"session_id": "bbbb1111", "cwd": str(tmp_path), "tool_name": "Edit", "tool_input": {"file_path": "x.md"}}
    monkeypatch.setattr(cli, "_deps", fake_deps)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert cli.main(["hook", "post"]) == 0
    assert capsys.readouterr().out == ""


def test_cli_hook_bad_json_exits_zero(monkeypatch, capsys):
    def no_deps():
        raise AssertionError("deps must not be built for bad input")

    monkeypatch.setattr(cli, "_deps", no_deps)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{not json"))
    assert cli.main(["hook", "pre"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1 and captured.err.startswith("airspace: ")


def test_cli_hook_exits_zero_when_handler_crashes(monkeypatch, capsys):
    def broken():
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "_deps", broken)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Edit"})))
    assert cli.main(["hook", "post"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("airspace: ")


def test_index_prints_stats(tmp_path, monkeypatch, capsys):
    seen = []

    def fake_index(graph, root):
        seen.append((graph, root))
        return SimpleNamespace(files=8, symbols=17, calls=7, unresolved=3)

    monkeypatch.setattr(cli, "_graph", lambda root: "G")
    monkeypatch.setattr(cli, "_index_repo", fake_index)
    assert cli.main(["index", "--root", str(tmp_path)]) == 0
    assert seen == [("G", tmp_path.resolve())]
    assert capsys.readouterr().out.strip() == "Indexed 8 files, 17 symbols, 7 calls (3 unresolved)"


def test_index_reports_db_down(tmp_path, monkeypatch, capsys):
    def down(root):
        raise ConnectionError("refused")

    monkeypatch.setattr(cli, "_graph", down)
    assert cli.main(["index", "--root", str(tmp_path)]) == 1
    assert "FalkorDB" in capsys.readouterr().err


def test_status_lists_tasks_claims_and_collisions(graph, tmp_path, monkeypatch, capsys):
    now = time.time()
    graph.query(
        """CREATE (a:Agent {id: 'agent-a'})-[:FLYING]->(ta:Task {id: 'task-a', status: 'active', intent: 'rename'}),
                  (b:Agent {id: 'agent-b'})-[:FLYING]->(tb:Task {id: 'task-b', status: 'active', intent: ''}),
                  (c:Agent {id: 'agent-c'})-[:FLYING]->(:Task {id: 'task-c', status: 'released', intent: ''}),
                  (s:Symbol {qualname: 'utils.text.slugify'}),
                  (old:Symbol {qualname: 'utils.text.truncate_words'}),
                  (ta)-[:CLAIMS {lease_until: $live}]->(s),
                  (tb)-[:CLAIMS {lease_until: $expired}]->(old),
                  (col:Collision {id: 'col_1', at: $now})-[:AT]->(s),
                  (col)-[:BETWEEN]->(ta), (col)-[:BETWEEN]->(tb)""",
        {"live": now + 600, "expired": now - 600, "now": now},
    )
    monkeypatch.setattr(cli, "_graph", lambda root: graph)
    assert cli.main(["status", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    task_a = next(line for line in out.splitlines() if "task-a" in line)
    assert "agent-a" in task_a and "utils.text.slugify" in task_a
    task_b = next(line for line in out.splitlines() if "task-b" in line and "agent-b" in line and "col_1" not in line)
    assert "truncate_words" not in task_b
    assert "task-c" not in out
    col = next(line for line in out.splitlines() if "col_1" in line)
    assert "utils.text.slugify" in col and "agent-a" in col and "agent-b" in col


def test_serve_runs_the_api_with_defaults(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_serve", lambda root, host, port: seen.append((root, host, port)))
    assert cli.main(["serve", "--root", str(tmp_path)]) == 0
    assert seen == [(tmp_path.resolve(), "127.0.0.1", 8787)]


def test_serve_takes_host_and_port(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_serve", lambda root, host, port: seen.append((root, host, port)))
    assert cli.main(["serve", "--root", str(tmp_path), "--host", "0.0.0.0", "--port", "9000"]) == 0
    assert seen == [(tmp_path.resolve(), "0.0.0.0", 9000)]


def test_mcp_runs_the_stdio_server(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_mcp", lambda root: seen.append(root))
    assert cli.main(["mcp", "--root", str(tmp_path)]) == 0
    assert seen == [tmp_path.resolve()]


class InsightsAirspace:
    def insights(self):
        return {
            "hot_zones": [
                {"qualname": "utils.text.slugify", "collisions": 3, "betweenness": 2.0},
                {"qualname": "blog.models.Post.save", "collisions": 1, "betweenness": 0.5},
            ],
            "parallel_groups": [
                {"agents": ["agent-a", "agent-b"], "conflict": True},
                {"agents": ["agent-c"], "conflict": False},
            ],
        }


def test_insights_prints_hot_zones_and_groups(tmp_path, monkeypatch, capsys):
    roots = []

    def fake_airspace(root):
        roots.append(root)
        return InsightsAirspace()

    monkeypatch.setattr(cli, "_airspace", fake_airspace)
    assert cli.main(["insights", "--root", str(tmp_path)]) == 0
    assert roots == [tmp_path.resolve()]
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Hot zones (2)"
    slug = next(line for line in lines if "utils.text.slugify" in line)
    assert "3 collisions" in slug and "betweenness 2.0" in slug
    assert any("1 collision," in line for line in lines if "Post.save" in line)
    assert "Parallel groups (2)" in lines
    ab = next(line for line in lines if "agent-a" in line)
    assert "agent-a, agent-b" in ab and "conflict" in ab
    c = next(line for line in lines if "agent-c" in line)
    assert "no conflicts" in c


def test_insights_on_an_empty_graph(tmp_path, monkeypatch, capsys):
    class Empty:
        def insights(self):
            return {"hot_zones": [], "parallel_groups": []}

    monkeypatch.setattr(cli, "_airspace", lambda root: Empty())
    assert cli.main(["insights", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Hot zones (0)" in out and "Parallel groups (0)" in out


def test_insights_reports_db_down(tmp_path, monkeypatch, capsys):
    def down(root):
        raise ConnectionError("refused")

    monkeypatch.setattr(cli, "_airspace", down)
    assert cli.main(["insights", "--root", str(tmp_path)]) == 1
    assert "FalkorDB" in capsys.readouterr().err
