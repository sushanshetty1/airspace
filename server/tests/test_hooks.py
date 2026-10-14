"""Hook handler unit tests. Fakes stand in for the indexer and the admission engine; no FalkorDB needed."""

from pathlib import Path

from airspace.hooks.handlers import Deps, briefing_context, handle_any, handle_post, handle_pre, handle_stop, identity
from airspace.types import Briefing, CallSite, EditAnalysis, SignatureChange, Verdict

SESSION = "5e55f00d-0000-4000-8000-000000000000"

SLUGIFY_BRIEFING = Briefing(
    id="cc_1",
    symbol="utils.text.slugify",
    old_signature="slugify(value, allow_unicode=False)",
    new_signature="slugify(value, *, unicode=False)",
    from_agent="agent-a",
)


class FakeAirspace:
    def __init__(self, verdict=None, briefings=None, messages=None):
        self.verdict = verdict or Verdict("cleared", "")
        self.briefings = list(briefings or [])
        self.messages = list(messages or [])
        self.calls = []

    def pending_messages(self, agent_id, task_id=None):
        self.calls.append(("pending_messages", agent_id, task_id))
        out, self.messages = self.messages, []
        return out

    def ensure_task(self, agent_id, task_id, intent=""):
        self.calls.append(("ensure_task", agent_id, task_id))

    def check_edit(self, task_id, touched, new_calls, call_shapes=None):
        self.calls.append(("check_edit", task_id, list(touched), list(new_calls)))
        self.shapes = call_shapes
        return self.verdict

    def record_changes(self, task_id, changes):
        self.calls.append(("record_changes", task_id, list(changes)))
        return [f"cc_{i}" for i, _ in enumerate(changes)]

    def pending_briefings(self, task_id):
        self.calls.append(("pending_briefings", task_id))
        out, self.briefings = self.briefings, []
        return out

    def claim_pending(self, task_id):
        self.calls.append(("claim_pending", task_id))
        return []

    def owned(self, task_id, qualnames):
        # The fake's edits are all the task's own; stale copies are covered against the real engine.
        return list(qualnames)

    def restore_signatures(self, signatures):
        self.calls.append(("restore_signatures", list(signatures)))

    def record_edited_file(self, task_id, rel):
        self.calls.append(("record_edited_file", task_id, rel))

    def agent_of(self, task_id):
        self.calls.append(("agent_of", task_id))
        return None

    def memory_for_task(self, task_id, qualnames, limit=8):
        return []


def make_deps(fake=None, analysis=None, changes=None, analyze_calls=None, reindex_calls=None):
    fake = fake if fake is not None else FakeAirspace()

    def analyze(root, tool_name, tool_input, known):
        if analyze_calls is not None:
            analyze_calls.append((root, tool_name, tool_input, known))
        return analysis

    def reindex(root, rel):
        if reindex_calls is not None:
            reindex_calls.append((root, rel))
        return list(changes or [])

    return Deps(
        airspace=lambda root: fake,
        analyze=analyze,
        known=lambda root: {"utils.text.slugify", "blog.views.render_post"},
        reindex=reindex,
    )


def payload(root: Path, tool_name="Edit", file="blog/views.py", tool_input=None, event="PreToolUse"):
    if tool_input is None:
        tool_input = {"file_path": str(root / file), "old_string": "a", "new_string": "b"}
    return {
        "session_id": SESSION,
        "cwd": str(root),
        "hook_event_name": event,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "toolu_1",
    }


ENV = {}  # no CLAUDE_PROJECT_DIR, no AIRSPACE_AGENT: identity comes from the payload


def touched_render_post(new_calls=None):
    return EditAnalysis(
        file="blog/views.py",
        touched=["blog.views.render_post"],
        new_calls=new_calls if new_calls is not None else [("blog.views.render_post", "utils.text.slugify")],
        parse_ok=True,
    )


def test_pre_hook_ignores_non_python(tmp_path):
    fake = FakeAirspace(verdict=Verdict("hold", "should not be consulted"))
    calls = []
    deps = make_deps(fake, analysis=touched_render_post(), analyze_calls=calls)
    p = payload(tmp_path, file="README.md")
    assert handle_pre(p, deps, ENV) is None
    assert calls == [] and fake.calls == []


def test_pre_hook_ignores_other_tools(tmp_path):
    fake = FakeAirspace(verdict=Verdict("hold", "should not be consulted"))
    deps = make_deps(fake, analysis=touched_render_post())
    p = payload(tmp_path, tool_name="Bash", tool_input={"command": "python blog/views.py"})
    assert handle_pre(p, deps, ENV) is None
    assert fake.calls == []


def test_pre_hook_ignores_files_outside_repo(tmp_path):
    fake = FakeAirspace(verdict=Verdict("hold", "should not be consulted"))
    deps = make_deps(fake, analysis=touched_render_post())
    repo = tmp_path / "repo"
    repo.mkdir()
    p = payload(repo, tool_input={"file_path": str(tmp_path / "elsewhere.py"), "old_string": "a", "new_string": "b"})
    assert handle_pre(p, deps, ENV) is None
    assert fake.calls == []


def test_pre_hook_new_file_is_cleared(tmp_path):
    fake = FakeAirspace(verdict=Verdict("hold", "should not be consulted"))
    analysis = EditAnalysis(file="blog/new.py", touched=[], new_calls=[], parse_ok=True)
    deps = make_deps(fake, analysis=analysis)
    p = payload(tmp_path, tool_name="Write", tool_input={"file_path": str(tmp_path / "blog/new.py"), "content": "x = 1\n"})
    assert handle_pre(p, deps, ENV) is None
    assert not any(c[0] == "check_edit" for c in fake.calls)


def test_pre_hook_unknown_file_is_cleared(tmp_path):
    fake = FakeAirspace(verdict=Verdict("hold", "should not be consulted"))
    deps = make_deps(fake, analysis=None)
    assert handle_pre(payload(tmp_path), deps, ENV) is None
    assert not any(c[0] == "check_edit" for c in fake.calls)


def test_pre_hook_syntax_error_is_cleared(tmp_path):
    fake = FakeAirspace(verdict=Verdict("hold", "should not be consulted"))
    analysis = EditAnalysis(file="blog/views.py", touched=["blog.views.render_post"], new_calls=[], parse_ok=False)
    deps = make_deps(fake, analysis=analysis)
    assert handle_pre(payload(tmp_path), deps, ENV) is None
    assert not any(c[0] == "check_edit" for c in fake.calls)


def test_pre_hook_passes_repo_known_and_tool_input_to_analyze(tmp_path):
    calls = []
    p = payload(tmp_path)
    deps = make_deps(analysis=None, analyze_calls=calls)
    handle_pre(p, deps, ENV)
    assert calls == [(tmp_path, "Edit", p["tool_input"], {"utils.text.slugify", "blog.views.render_post"})]


def test_pre_hook_hold_prints_deny_json(tmp_path):
    fake = FakeAirspace(verdict=Verdict("hold", "reason text", path=["blog.views.render_post", "utils.text.slugify"]))
    deps = make_deps(fake, analysis=touched_render_post())
    out = handle_pre(payload(tmp_path), deps, ENV)
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "reason text",
        }
    }
    assert ("ensure_task", "agent-5e55", SESSION) in fake.calls
    assert (
        "check_edit",
        SESSION,
        ["blog.views.render_post"],
        [("blog.views.render_post", "utils.text.slugify")],
    ) in fake.calls
    assert fake.calls.index(("ensure_task", "agent-5e55", SESSION)) < [c[0] for c in fake.calls].index("check_edit")


def test_pre_hook_new_call_only_is_checked(tmp_path):
    fake = FakeAirspace(verdict=Verdict("hold", "held"))
    analysis = EditAnalysis(
        file="blog/views.py", touched=[], new_calls=[("blog.views.render_post", "utils.text.slugify")], parse_ok=True
    )
    deps = make_deps(fake, analysis=analysis)
    out = handle_pre(payload(tmp_path), deps, ENV)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_hook_cleared_without_briefing_is_silent(tmp_path):
    fake = FakeAirspace(verdict=Verdict("cleared", ""))
    deps = make_deps(fake, analysis=touched_render_post())
    assert handle_pre(payload(tmp_path), deps, ENV) is None
    assert ("pending_briefings", SESSION) in fake.calls


def test_pre_hook_cleared_with_briefing_returns_context(tmp_path):
    fake = FakeAirspace(verdict=Verdict("cleared", ""), briefings=[SLUGIFY_BRIEFING])
    deps = make_deps(fake, analysis=touched_render_post())
    out = handle_pre(payload(tmp_path), deps, ENV)
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": briefing_context([SLUGIFY_BRIEFING]),
        }
    }
    text = out["hookSpecificOutput"]["additionalContext"]
    for part in ("utils.text.slugify", "agent-a", "slugify(value, *, unicode=False)", "slugify(value, allow_unicode=False)"):
        assert part in text


def test_hooks_include_messages(tmp_path):
    # Held: the message rides along in the deny reason, so it reaches the agent while it is held.
    fake = FakeAirspace(verdict=Verdict("hold", "reason text"), messages=["slugify is mid change"])
    out = handle_pre(payload(tmp_path), make_deps(fake, analysis=touched_render_post()), ENV)
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == "reason text\nMessage from Tower: slugify is mid change"
    assert ("pending_messages", "agent-5e55", SESSION) in fake.calls

    # Cleared: briefings first, then messages, in one additionalContext.
    fake = FakeAirspace(briefings=[SLUGIFY_BRIEFING], messages=["one", "two"])
    out = handle_pre(payload(tmp_path), make_deps(fake, analysis=touched_render_post()), ENV)
    assert out["hookSpecificOutput"]["additionalContext"] == (
        briefing_context([SLUGIFY_BRIEFING]) + "\nMessage from Tower: one\nMessage from Tower: two"
    )

    # Cleared with only a message.
    fake = FakeAirspace(messages=["only"])
    out = handle_pre(payload(tmp_path), make_deps(fake, analysis=touched_render_post()), ENV)
    assert out == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "Message from Tower: only"}}

    # Post hook.
    fake = FakeAirspace(messages=["after"])
    out = handle_post(payload(tmp_path, event="PostToolUse"), make_deps(fake, changes=[]), ENV)
    assert out == {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "Message from Tower: after"}}
    assert ("pending_messages", "agent-5e55", SESSION) in fake.calls


def test_hold_reason_unchanged_without_messages(tmp_path):
    fake = FakeAirspace(verdict=Verdict("hold", "reason text"))
    out = handle_pre(payload(tmp_path), make_deps(fake, analysis=touched_render_post()), ENV)
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == "reason text"


def test_hold_survives_a_failed_message_lookup(tmp_path, capsys):
    class Broken(FakeAirspace):
        def pending_messages(self, agent_id, task_id=None):
            raise RuntimeError("graph went away")

    out = handle_pre(payload(tmp_path), make_deps(Broken(verdict=Verdict("hold", "r")), analysis=touched_render_post()), ENV)
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == "r"
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("airspace: ")


def test_briefing_context_lists_every_briefing():
    other = Briefing("cc_2", "utils.text.truncate_words", "truncate_words(text, count=30)", "truncate_words(text, n)", "agent-c")
    text = briefing_context([SLUGIFY_BRIEFING, other])
    assert "utils.text.slugify" in text and "utils.text.truncate_words" in text
    assert "agent-a" in text and "agent-c" in text
    assert chr(0x2014) not in text and chr(0x2013) not in text


def test_pre_hook_fails_open_when_db_down(tmp_path, capsys):
    def down(root):
        raise ConnectionError("Connection refused")

    deps = make_deps(analysis=touched_render_post())
    deps.airspace = down
    assert handle_pre(payload(tmp_path), deps, ENV) is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "airspace: FalkorDB unavailable, edit not checked\n"


def test_pre_hook_fails_open_when_known_loader_fails(tmp_path, capsys):
    deps = make_deps(analysis=touched_render_post())

    def broken(root):
        raise OSError("socket closed")

    deps.known = broken
    assert handle_pre(payload(tmp_path), deps, ENV) is None
    assert capsys.readouterr().err == "airspace: FalkorDB unavailable, edit not checked\n"


def test_pre_hook_fails_open_when_check_edit_raises(tmp_path, capsys):
    class Broken(FakeAirspace):
        def check_edit(self, task_id, touched, new_calls, call_shapes=None):
            raise RuntimeError("graph went away")

    deps = make_deps(Broken(), analysis=touched_render_post())
    assert handle_pre(payload(tmp_path), deps, ENV) is None
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("airspace: ")


def test_post_hook_records_changes(tmp_path):
    change = SignatureChange("utils.text.slugify", "slugify(value, allow_unicode=False)", "slugify(value, *, unicode=False)")
    fake = FakeAirspace()
    reindexed = []
    deps = make_deps(fake, changes=[change], reindex_calls=reindexed)
    p = payload(tmp_path, file="utils/text.py", event="PostToolUse")
    assert handle_post(p, deps, ENV) is None
    assert reindexed == [(tmp_path, "utils/text.py")]
    assert ("ensure_task", "agent-5e55", SESSION) in fake.calls
    assert ("record_changes", SESSION, [change]) in fake.calls


def test_post_hook_claims_created_symbols_after_reindex(tmp_path):
    fake = FakeAirspace()
    deps = make_deps(fake, changes=[])
    handle_post(payload(tmp_path, event="PostToolUse"), deps, ENV)
    names = [c[0] for c in fake.calls]
    assert ("claim_pending", SESSION) in fake.calls
    assert names.index("claim_pending") < names.index("pending_briefings")


def test_post_hook_without_changes_records_nothing(tmp_path):
    fake = FakeAirspace()
    deps = make_deps(fake, changes=[])
    assert handle_post(payload(tmp_path, event="PostToolUse"), deps, ENV) is None
    assert not any(c[0] == "record_changes" for c in fake.calls)


def test_post_hook_returns_pending_briefings(tmp_path):
    fake = FakeAirspace(briefings=[SLUGIFY_BRIEFING])
    deps = make_deps(fake, changes=[])
    out = handle_post(payload(tmp_path, event="PostToolUse"), deps, ENV)
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": briefing_context([SLUGIFY_BRIEFING]),
        }
    }


def test_post_hook_ignores_non_python(tmp_path):
    reindexed = []
    deps = make_deps(reindex_calls=reindexed)
    assert handle_post(payload(tmp_path, file="notes.txt", event="PostToolUse"), deps, ENV) is None
    assert reindexed == []


def test_post_hook_fails_open_when_db_down(tmp_path, capsys):
    def down(root):
        raise ConnectionError("Connection refused")

    reindexed = []
    deps = make_deps(reindex_calls=reindexed)
    deps.airspace = down
    assert handle_post(payload(tmp_path, event="PostToolUse"), deps, ENV) is None
    assert capsys.readouterr().err == "airspace: FalkorDB unavailable, edit not checked\n"
    assert reindexed == []


def test_identity_defaults_from_payload(tmp_path):
    p = payload(tmp_path)
    assert identity(p, {}) == (tmp_path, "agent-5e55", SESSION)


def test_identity_env_overrides(tmp_path):
    project = tmp_path / "project"
    p = payload(tmp_path / "project" / "sub")
    env = {"CLAUDE_PROJECT_DIR": str(project), "AIRSPACE_AGENT": "agent-a"}
    assert identity(p, env) == (project, "agent-a", SESSION)


# Call shapes, signature changes recorded at the pre hook, and the hook for every other tool.

SLUGIFY_CHANGE = SignatureChange("utils.text.slugify", "slugify(value, allow_unicode=False)", "slugify(value, *, unicode=False)")
SHAPES = {"utils.text.slugify": [CallSite("blog.views.render_post", 2, (), False, False)]}


def test_pre_hook_passes_call_shapes(tmp_path):
    fake = FakeAirspace(verdict=Verdict("hold", "held"))
    analysis = touched_render_post()
    analysis.call_shapes = SHAPES
    handle_pre(payload(tmp_path), make_deps(fake, analysis=analysis), ENV)
    assert fake.shapes == SHAPES


def test_cleared_pre_records_signature_changes(tmp_path):
    fake = FakeAirspace(verdict=Verdict("cleared", ""))
    analysis = EditAnalysis("utils/text.py", ["utils.text.slugify"], [], True, signature_changes=[SLUGIFY_CHANGE])
    handle_pre(payload(tmp_path, file="utils/text.py"), make_deps(fake, analysis=analysis), ENV)
    names = [c[0] for c in fake.calls]
    assert ("record_changes", SESSION, [SLUGIFY_CHANGE]) in fake.calls
    assert names.index("check_edit") < names.index("record_changes") < names.index("pending_briefings")


def test_held_pre_records_nothing(tmp_path):
    fake = FakeAirspace(verdict=Verdict("hold", "held"))
    analysis = EditAnalysis("utils/text.py", ["utils.text.slugify"], [], True, signature_changes=[SLUGIFY_CHANGE])
    handle_pre(payload(tmp_path, file="utils/text.py"), make_deps(fake, analysis=analysis), ENV)
    assert not any(c[0] == "record_changes" for c in fake.calls)


def test_removal_only_edit_is_checked_and_recorded(tmp_path):
    # Deleting a whole method touches nothing that is left, but the removed symbol is checked against claims.
    removal = SignatureChange("blog.models.Post.get_absolute_url", "get_absolute_url(self)", "")
    fake = FakeAirspace()
    analysis = EditAnalysis("blog/models.py", [], [], True, signature_changes=[removal])
    handle_pre(payload(tmp_path, file="blog/models.py"), make_deps(fake, analysis=analysis), ENV)
    assert ("check_edit", SESSION, ["blog.models.Post.get_absolute_url"], []) in fake.calls
    assert ("record_changes", SESSION, [removal]) in fake.calls


def test_any_hook_delivers_briefings_and_messages(tmp_path):
    fake = FakeAirspace(briefings=[SLUGIFY_BRIEFING], messages=["hello"])
    analyze_calls, reindex_calls = [], []
    deps = make_deps(fake, analyze_calls=analyze_calls, reindex_calls=reindex_calls)
    p = payload(tmp_path, tool_name="Bash", tool_input={"command": "pytest -q"})
    out = handle_any(p, deps, ENV)
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": briefing_context([SLUGIFY_BRIEFING]) + "\nMessage from Tower: hello",
        }
    }
    assert analyze_calls == [] and reindex_calls == []
    assert not any(c[0] in ("check_edit", "record_changes", "ensure_task") for c in fake.calls)


def test_any_hook_is_silent_without_news(tmp_path):
    fake = FakeAirspace()
    p = payload(tmp_path, tool_name="Read", tool_input={"file_path": str(tmp_path / "x.py")})
    assert handle_any(p, make_deps(fake), ENV) is None
    assert ("pending_briefings", SESSION) in fake.calls


def test_any_hook_leaves_edits_to_the_edit_hooks(tmp_path):
    fake = FakeAirspace(briefings=[SLUGIFY_BRIEFING])
    assert handle_any(payload(tmp_path), make_deps(fake), ENV) is None
    assert fake.calls == []


def test_any_hook_fails_open(tmp_path, capsys):
    def down(root):
        raise ConnectionError("Connection refused")

    deps = make_deps()
    deps.airspace = down
    assert handle_any(payload(tmp_path, tool_name="Bash", tool_input={"command": "ls"}), deps, ENV) is None
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.count("\n") == 1 and captured.err.startswith("airspace: ")

    class Broken(FakeAirspace):
        def pending_briefings(self, task_id):
            raise RuntimeError("graph went away")

    assert handle_any(payload(tmp_path, tool_name="Bash", tool_input={"command": "ls"}), make_deps(Broken()), ENV) is None


def test_briefing_context_names_the_broken_call_and_removals():
    caller_first = Briefing("cc_3", "utils.text.slugify", "slugify(value, allow_unicode=False)",
                            "slugify(value, *, unicode=False)", "agent-a", "blog.views.render_post")
    text = briefing_context([caller_first])
    assert "The call blog.views.render_post makes no longer fits slugify(value, *, unicode=False)." in text
    removed = Briefing("cc_4", "blog.models.Post.get_absolute_url", "get_absolute_url(self)", "", "agent-a")
    text = briefing_context([removed])
    assert "blog.models.Post.get_absolute_url was renamed or removed by agent-a" in text
    assert "New signature" not in text
    for t in (briefing_context([caller_first, removed]),):
        assert chr(0x2014) not in t and chr(0x2013) not in t


def test_post_records_edited_files(tmp_path):
    change = SignatureChange("utils.text.slugify", "slugify(value, allow_unicode=False)", "slugify(value, *, unicode=False)")
    fake = FakeAirspace()
    handle_post(payload(tmp_path, file="utils/text.py", event="PostToolUse"), make_deps(fake, changes=[change]), ENV)
    names = [c[0] for c in fake.calls]
    assert ("record_edited_file", SESSION, "utils/text.py") in fake.calls
    # After the task exists, so the first edit of a task is recorded too.
    assert names.index("ensure_task") < names.index("record_edited_file")

    fake = FakeAirspace()
    handle_post(payload(tmp_path, file="notes.txt", event="PostToolUse"), make_deps(fake), ENV)
    assert fake.calls == []


def test_stop_without_a_task_is_silent(tmp_path):
    fake = FakeAirspace()
    p = {"session_id": SESSION, "cwd": str(tmp_path), "hook_event_name": "Stop", "stop_hook_active": False}
    assert handle_stop(p, make_deps(fake), ENV) is None
    assert fake.calls == [("agent_of", SESSION)]


def test_stop_fails_open(tmp_path, capsys):
    def down(root):
        raise ConnectionError("Connection refused")

    deps = make_deps()
    deps.airspace = down
    p = {"session_id": SESSION, "cwd": str(tmp_path), "hook_event_name": "Stop", "stop_hook_active": False}
    assert handle_stop(p, deps, ENV) is None
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "airspace: FalkorDB unavailable, landing not checked\n"

    class Broken(FakeAirspace):
        def agent_of(self, task_id):
            raise RuntimeError("graph went away")

    assert handle_stop(p, make_deps(Broken()), ENV) is None
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("airspace: ") and "landing not checked" in err
