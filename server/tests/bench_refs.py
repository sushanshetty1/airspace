"""Reference edits for each benchmark task set, and a driver that sends them through the real hooks.

REFS maps a set id to (A's patch, B's patch). A patch maps "path" (or "path#2" for a second edit to the same file)
to an (old, new) replacement or to the whole content of a new file.
"""

# Reference solutions for each set: A as specified, B written naturally against the code B can see.
SLUG_A = {"utils/text.py": ("def slugify(value, allow_unicode=False):\n    value = str(value)\n    if allow_unicode:", "def slugify(value, *, unicode=False):\n    value = str(value)\n    if unicode:")}
REFS = {
    "slugify-keyword-only": (
        SLUG_A,
        {"blog/views.py": ("from blog.models import Post\n", "from blog.models import Post\nfrom utils.text import slugify\n"),
         "blog/views.py#2": ("<article>", '<article data-slug="{slugify(post.title, allow_unicode=True)}">')},
    ),
    "truncate-words-limit": (
        {"utils/text.py": ("def truncate_words(text, count=30):\n    words = text.split()\n    return \" \".join(words[:count]) + (\"...\" if len(words) > count else \"\")",
                           "def truncate_words(text, *, limit=30):\n    words = text.split()\n    return \" \".join(words[:limit]) + (\"...\" if len(words) > limit else \"\")"),
         "blog/feeds.py": ("truncate_words(render_post(post), 40)", "truncate_words(render_post(post), limit=40)")},
        {"tags/views.py": ("from tags.models import Tag\n", "from tags.models import Tag\nfrom utils.text import truncate_words\n"),
         "tags/views.py#2": ("    return Tag(name).save()\n", "    return Tag(name).save()\n\n\ndef tag_label(name):\n    return truncate_words(name, 3)\n")},
    ),
    "rename-absolute-url": (
        {"blog/models.py": ("def get_absolute_url(self):", "def url(self):"), "blog/views.py": ("post.get_absolute_url()", "post.url()")},
        {"blog/feeds.py": ("        return truncate_words(render_post(post), 40)\n", "        return truncate_words(render_post(post), 40)\n\n    def item_link(self, post):\n        return post.get_absolute_url()\n")},
    ),
    "render-post-show-body": (
        {"blog/views.py": ("def render_post(post):\n    url = post.get_absolute_url()\n    return f'<article><a href=\"{url}\">{post.title}</a><p>{post.body}</p></article>'",
                           "def render_post(post, *, show_body):\n    url = post.get_absolute_url()\n    body = f'<p>{post.body}</p>' if show_body else ''\n    return f'<article><a href=\"{url}\">{post.title}</a>{body}</article>'"),
         "blog/views.py#2": ("render_post(p) for p in posts", "render_post(p, show_body=True) for p in posts"),
         "blog/feeds.py": ("truncate_words(render_post(post), 40)", "truncate_words(render_post(post, show_body=True), 40)"),
         "tests/test_views.py": ("render_post(Post(\"Hi\", \"x\").save())", "render_post(Post(\"Hi\", \"x\").save(), show_body=True)")},
        {"blog/index.py": "from blog.views import render_post\n\n\ndef render_index(posts):\n    return '<ul>' + ''.join(f'<li>{render_post(p)}</li>' for p in posts) + '</ul>'\n"},
    ),
    "post-requires-author": (
        {"blog/models.py": ("def __init__(self, title, body):\n        self.title = title\n        self.body = body", "def __init__(self, title, body, author):\n        self.title = title\n        self.body = body\n        self.author = author"),
         "tests/test_models.py": ('Post("Hello World", "")', 'Post("Hello World", "", "ana")'),
         "tests/test_views.py": ('Post("Hi", "x")', 'Post("Hi", "x", "ana")')},
        {"tests/test_feeds.py": "from blog.feeds import LatestPosts\nfrom blog.models import Post\n\n\ndef test_item_description():\n    assert 'Hi' in LatestPosts().item_description(Post('Hi', 'x').save())\n"},
    ),
    "tag-save-returns-none": (
        {"tags/models.py": ("        self.slug = slugify(self.name)\n        return self", "        self.slug = slugify(self.name)"),
         "tags/views.py": ("    return Tag(name).save()", "    tag = Tag(name)\n    tag.save()\n    return tag")},
        {"tags/utils.py": "from tags.models import Tag\n\n\ndef tag_slug(name):\n    return Tag(name).save().slug\n"},
    ),
}

# Every set: B's natural call breaks against A's new contract. In the last one the parameters stay the same and
# only the return changes (Tag.save stops returning self), which the contract carries as "-> None".
SIGNATURE_SETS = ["slugify-keyword-only", "truncate-words-limit", "rename-absolute-url", "render-post-show-body",
                  "post-requires-author", "tag-save-returns-none"]


def tool_calls(patch: dict) -> list[tuple[str, str, dict]]:
    """A patch as the Claude Code tool calls an agent would make: (rel path, tool name, tool input)."""
    calls = []
    for key, change in patch.items():
        rel = key.split("#")[0]
        if isinstance(change, str):
            calls.append((rel, "Write", {"file_path": rel, "content": change}))
        else:
            old, new = change
            calls.append((rel, "Edit", {"file_path": rel, "old_string": old, "new_string": new}))
    return calls


def is_deny(out) -> bool:
    return bool(out) and out["hookSpecificOutput"].get("permissionDecision") == "deny"


class Agent:
    """One Claude Code session driven through the real hooks: pre, then the write if cleared, then post."""

    def __init__(self, repo, agent_id: str, session: str, deps):
        self.repo, self.agent_id, self.session, self.deps = repo, agent_id, session, deps
        self.env = {"CLAUDE_PROJECT_DIR": str(repo), "AIRSPACE_AGENT": agent_id}
        self.holds: list[dict] = []
        self.contexts: list[str] = []

    def _payload(self, event: str, tool: str, tool_input: dict) -> dict:
        return {"session_id": self.session, "cwd": str(self.repo), "hook_event_name": event, "tool_name": tool,
                "tool_input": tool_input}

    def _note(self, out) -> None:
        if out and "additionalContext" in out.get("hookSpecificOutput", {}):
            self.contexts.append(out["hookSpecificOutput"]["additionalContext"])

    def pre(self, tool: str, tool_input: dict):
        from airspace.hooks.handlers import handle_pre

        out = handle_pre(self._payload("PreToolUse", tool, tool_input), self.deps, self.env)
        if is_deny(out):
            self.holds.append(out)
        else:
            self._note(out)
        return out

    def write(self, rel: str, tool: str, tool_input: dict) -> None:
        from airspace.hooks.edit_analysis import apply_tool_input

        path = self.repo / rel
        current = path.read_text() if path.exists() else None
        new = apply_tool_input(tool, tool_input, current)
        assert new is not None, (rel, tool_input)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new)

    def post(self, tool: str, tool_input: dict):
        from airspace.hooks.handlers import handle_post

        out = handle_post(self._payload("PostToolUse", tool, tool_input), self.deps, self.env)
        self._note(out)
        return out

    def edit(self, rel: str, tool: str, tool_input: dict) -> bool:
        """The whole tool call. True when it went through, False when it was held."""
        if is_deny(self.pre(tool, tool_input)):
            return False
        self.write(rel, tool, tool_input)
        self.post(tool, tool_input)
        return True

    def apply(self, patch: dict) -> bool:
        """Every edit of a patch, stopping at the first hold. True when all went through."""
        return all(self.edit(rel, tool, tool_input) for rel, tool, tool_input in tool_calls(patch))

    def stop(self, stop_hook_active: bool = False, **timing):
        """The Stop hook at the end of the agent's turn. `timing` passes wait_seconds, poll_seconds, sleep, clock."""
        from airspace.hooks.handlers import handle_stop

        payload = {"session_id": self.session, "cwd": str(self.repo), "hook_event_name": "Stop",
                   "stop_hook_active": stop_hook_active, "last_assistant_message": "Done."}
        out = handle_stop(payload, self.deps, self.env, **timing)
        self._note(out)
        return out

    def shell_write(self, rel: str, content: str):
        """A file written by a shell command (`cat > rel <<EOF`), which no edit hook sees, then PostToolUse Bash."""
        from airspace.hooks.handlers import handle_reconcile

        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        out = handle_reconcile(self._payload("PostToolUse", "Bash", {"command": f"cat > {rel} <<'EOF'"}), self.deps,
                               self.env)
        self._note(out)
        return out

    def other_tool(self, tool: str = "Bash", tool_input: dict | None = None):
        from airspace.hooks.handlers import handle_any

        out = handle_any(self._payload("PreToolUse", tool, tool_input or {"command": "pytest -q"}), self.deps, self.env)
        self._note(out)
        return out


class Escaped(BaseException):
    """A failure inside a hook's sleep. Not an Exception, so the hook's fail-open handler cannot swallow it."""


class FakeTime:
    """A clock that only moves when the hook sleeps. `on_sleep[i]` runs at the i-th sleep."""

    def __init__(self, *on_sleep):
        self.now = 0.0
        self.sleeps = 0
        self.on_sleep = list(on_sleep)

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.sleeps += 1
        if self.sleeps <= len(self.on_sleep):
            try:
                self.on_sleep[self.sleeps - 1]()
            except Exception as e:
                raise Escaped(repr(e)) from e

    def timing(self, **extra) -> dict:
        return {"sleep": self.sleep, "clock": self.clock, **extra}


def never(seconds: float) -> None:
    raise Escaped("the stop hook waited")
