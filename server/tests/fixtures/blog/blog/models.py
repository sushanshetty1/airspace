from utils.text import slugify


class Post:
    def __init__(self, title, body):
        self.title = title
        self.body = body
        self.slug = ""

    def save(self):
        self.slug = slugify(self.title)
        return self

    def get_absolute_url(self):
        return f"/posts/{self.slug}/"
