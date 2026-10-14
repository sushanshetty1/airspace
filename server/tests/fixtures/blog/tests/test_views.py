from blog.models import Post
from blog.views import render_post


def test_render_post():
    html = render_post(Post("Hi", "x").save())
    assert "/posts/hi/" in html
