from blog.models import Post


def test_post_save():
    assert Post("Hello World", "").save().slug == "hello-world"
