from tags.models import Tag


def tag_create(name):
    return Tag(name).save()
