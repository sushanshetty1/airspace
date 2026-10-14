from utils.text import slugify


class Tag:
    def __init__(self, name):
        self.name = name
        self.slug = ""

    def save(self):
        self.slug = slugify(self.name)
        return self
