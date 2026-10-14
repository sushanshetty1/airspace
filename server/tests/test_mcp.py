import anyio

from airspace.mcp_server import server as mcp
from airspace.types import Briefing

AGENT = "agent-x"
TASK = "agent-x:mcp"

STATE = {
    "now": 100.0,
    "agents": [
        {"id": "agent-x", "paused": False, "status": "active", "tasks": [TASK], "claims": ["blog.views.render_post"],
         "held": False},
        {"id": "agent-a", "paused": False, "status": "active", "tasks": ["task-a"],
         "claims": ["utils.text.slugify", "utils.text.truncate_words"], "held": False},
    ],
    "collisions": [
        {"id": "col_1", "at": 90.0, "kind": "contract", "symbol": "utils.text.slugify", "held_agent": "agent-b",
         "owner_agent": "agent-a", "resolution": "held"},
        {"id": "col_0", "at": 80.0, "kind": "contract", "symbol": "blog.models.Post.save", "held_agent": "agent-b",
         "owner_agent": "agent-c", "resolution": "resolved"},
    ],
}


class FakeAirspace:
    def __init__(self, state=STATE):
        self.calls: list[tuple] = []
        self._state = state

    def ensure_task(self, agent_id, task_id, intent=""):
        self.calls.append(("ensure_task", agent_id, task_id, intent))

    def file_plan(self, agent_id, task_id, intent, qualnames):
        self.calls.append(("file_plan", agent_id, task_id, intent, list(qualnames)))
        return ["blog.models.Post.save", "blog.views.render_post"]

    def state(self):
        self.calls.append(("state",))
        return self._state

    def pending_briefings(self, task_id):
        self.calls.append(("pending_briefings", task_id))
        return [Briefing("cc_1", "utils.text.slugify", "slugify(value, allow_unicode=False)",
                         "slugify(value, *, unicode=False)", "agent-a")]

    def pending_messages(self, agent_id):
        self.calls.append(("pending_messages", agent_id))
        return ["slugify is keyword only now"]

    def explain(self, from_q, to_q):
        self.calls.append(("explain", from_q, to_q))
        return ["blog.views.render_post", "utils.text.slugify"] if to_q == "utils.text.slugify" else []

    def insights(self):
        self.calls.append(("insights",))
        return {"hot_zones": [{"qualname": "utils.text.slugify", "collisions": 3, "betweenness": 2.0}],
                "parallel_groups": []}


def no_dashes(text: str) -> bool:
    return "\u2013" not in text and "\u2014" not in text


def test_file_flight_plan_files_for_this_agent_and_lists_the_cone():
    fake = FakeAirspace()
    out = mcp.file_flight_plan(fake, AGENT, TASK, ["blog.views.render_post"], "rename the slug helper")
    assert ("ensure_task", AGENT, TASK, "rename the slug helper") in fake.calls
    assert ("file_plan", AGENT, TASK, "rename the slug helper", ["blog.views.render_post"]) in fake.calls
    assert fake.calls.index(("ensure_task", AGENT, TASK, "rename the slug helper")) < [c[0] for c in fake.calls].index(
        "file_plan"
    )
    assert "blog.models.Post.save" in out
    assert "blog.views.render_post" in out
    assert no_dashes(out)


def test_file_flight_plan_names_symbols_another_agent_holds():
    fake = FakeAirspace()
    out = mcp.file_flight_plan(fake, AGENT, TASK, ["utils.text.slugify", "blog.views.render_post"])
    line = next(line for line in out.splitlines() if "utils.text.slugify" in line and "agent-a" in line)
    assert "claimed by agent-a" in line


def test_file_flight_plan_with_no_symbols_does_not_call_the_engine():
    fake = FakeAirspace()
    out = mcp.file_flight_plan(fake, AGENT, TASK, [])
    assert fake.calls == []
    assert out


def test_check_symbols_reports_owner_contract_and_free():
    fake = FakeAirspace()
    out = mcp.check_symbols(fake, AGENT, ["utils.text.slugify", "blog.views.render_post", "blog.models.Post.save",
                                          "utils.text.truncate_words"])
    lines = dict(line.split(": ", 1) for line in out.splitlines())
    assert "claimed by agent-a" in lines["utils.text.slugify"]
    assert "agent-a is changing its contract" in lines["utils.text.slugify"]
    assert lines["blog.views.render_post"] == "claimed by this agent (agent-x)"
    assert lines["blog.models.Post.save"] == "free"  # its collision is resolved
    assert lines["utils.text.truncate_words"] == "claimed by agent-a"
    assert ("state",) in fake.calls
    assert no_dashes(out)


def test_check_symbols_on_an_empty_airspace():
    fake = FakeAirspace({"now": 1.0, "agents": [], "collisions": []})
    assert mcp.check_symbols(fake, AGENT, ["utils.text.slugify"]) == "utils.text.slugify: free"


def test_briefings_combine_briefings_and_messages():
    fake = FakeAirspace()
    out = mcp.briefings(fake, AGENT, TASK)
    assert ("pending_briefings", TASK) in fake.calls
    assert ("pending_messages", AGENT) in fake.calls
    assert "slugify(value, *, unicode=False)" in out
    assert "agent-a" in out
    assert "slugify is keyword only now" in out
    assert no_dashes(out)


def test_briefings_when_nothing_is_pending():
    class Quiet(FakeAirspace):
        def pending_briefings(self, task_id):
            return []

        def pending_messages(self, agent_id):
            return []

    assert mcp.briefings(Quiet(), AGENT, TASK) == "No pending briefings or messages."


def test_explain_shows_the_path():
    fake = FakeAirspace()
    out = mcp.explain(fake, "blog.views.render_post", "utils.text.slugify")
    assert ("explain", "blog.views.render_post", "utils.text.slugify") in fake.calls
    assert "blog.views.render_post -> utils.text.slugify" in out


def test_explain_without_a_path():
    out = mcp.explain(FakeAirspace(), "blog.views.render_post", "blog.models.Post")
    assert out.startswith("No dependency path")


def test_hot_zones_lists_insights():
    fake = FakeAirspace()
    out = mcp.hot_zones(fake)
    assert ("insights",) in fake.calls
    assert "utils.text.slugify" in out and "3 collisions" in out and "2.0" in out


def test_hot_zones_when_empty():
    class Calm(FakeAirspace):
        def insights(self):
            return {"hot_zones": [], "parallel_groups": []}

    assert mcp.hot_zones(Calm()) == "No hot zones recorded yet."


TOOLS = {"file_flight_plan", "check_symbols", "briefings", "explain", "hot_zones"}


def test_build_server_registers_the_five_tools(tmp_path):
    server = mcp.build_server(tmp_path, env={}, airspace_factory=lambda root: FakeAirspace())
    tools = anyio.run(server.list_tools)
    assert {t.name for t in tools} == TOOLS
    params = {t.name: set(t.input_schema.get("properties", {})) for t in tools}
    assert params["file_flight_plan"] == {"symbols", "intent"}
    assert params["check_symbols"] == {"symbols"}
    assert params["briefings"] == set()
    assert params["explain"] == {"from_symbol", "to_symbol"}
    assert params["hot_zones"] == set()


def test_build_server_does_not_open_the_engine_until_a_tool_runs(tmp_path):
    def refuse(root):
        raise AssertionError("engine opened at build time")

    mcp.build_server(tmp_path, env={}, airspace_factory=refuse)


def test_server_tools_use_the_agent_from_env(tmp_path):
    fake = FakeAirspace()
    opened = []

    def factory(root):
        opened.append(root)
        return fake

    server = mcp.build_server(tmp_path, env={"AIRSPACE_AGENT": "agent-x"}, airspace_factory=factory)

    async def run():
        await server.call_tool("file_flight_plan", {"symbols": ["blog.views.render_post"], "intent": "rename"})
        await server.call_tool("briefings", {})

    anyio.run(run)
    assert ("file_plan", "agent-x", "agent-x:mcp", "rename", ["blog.views.render_post"]) in fake.calls
    assert ("pending_briefings", "agent-x:mcp") in fake.calls
    assert ("pending_messages", "agent-x") in fake.calls
    assert opened == [tmp_path]


def test_server_agent_defaults_to_agent_mcp(tmp_path):
    fake = FakeAirspace()
    server = mcp.build_server(tmp_path, env={}, airspace_factory=lambda root: fake)
    anyio.run(lambda: server.call_tool("briefings", {}))
    assert ("pending_briefings", "agent-mcp:mcp") in fake.calls
