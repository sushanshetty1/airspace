from blog.views import render_post
from utils.text import truncate_words


class LatestPosts:
    def item_description(self, post):
        return truncate_words(render_post(post), 40)
