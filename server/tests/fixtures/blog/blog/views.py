from blog.models import Post


def render_post(post):
    url = post.get_absolute_url()
    return f'<article><a href="{url}">{post.title}</a><p>{post.body}</p></article>'


def post_list(posts):
    return "\n".join(render_post(p) for p in posts)
