"""The grader, and proof that each task set really interferes when the caller is written against the old interface."""

import shutil
import subprocess
from pathlib import Path

import pytest

from airspace.bench.grade import classify, git, grade
from airspace.bench.tasks import load_tasks

FIXTURE = Path(__file__).parent / "fixtures" / "blog"
TASKS = {t.id: t for t in load_tasks()}


def test_classify():
    assert classify(True, True, False, True) == "clean"
    assert classify(True, True, False, False) == "interference"
    assert classify(True, True, True, None) == "conflict"
    assert classify(False, True, False, True) == "task_failed"
    assert classify(True, True, False, True, error=True) == "error"


def test_six_task_sets_with_hidden_tests():
    assert len(TASKS) == 6
    for t in TASKS.values():
        assert set(t.hidden) == {"tests/test_hidden_a.py", "tests/test_hidden_b.py"}


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=bench", "-c", "user.email=bench@example.com", "commit", "-qm", "base")
    return repo


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


def _norm(edits):
    out: dict[str, list] = {}
    for key, change in edits.items():
        out.setdefault(key.split("#")[0], []).append(change)
    return out


def _apply_branch(repo, name, edits):
    git(repo, "checkout", "-q", "-b", name, "main")
    for rel, changes in _norm(edits).items():
        p = repo / rel
        for change in changes:
            if isinstance(change, str):
                p.write_text(change)
            else:
                old, new = change
                text = p.read_text()
                assert old in text, (rel, old)
                p.write_text(text.replace(old, new, 1))
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=bench", "-c", "user.email=bench@example.com", "commit", "-qm", name)
    git(repo, "checkout", "-q", "main")


@pytest.mark.parametrize("set_id", sorted(REFS))
def test_reference_solutions_interfere(tmp_path, set_id):
    """Each set is well formed: both reference patches pass alone, and their merge fails."""
    t = TASKS[set_id]
    repo = _repo(tmp_path)
    ref_a, ref_b = REFS[set_id]
    _apply_branch(repo, "a", ref_a)
    _apply_branch(repo, "b", ref_b)
    g = grade(repo, "a", "b", t.hidden_a, t.hidden_b)
    assert g.outcome == "interference", g
