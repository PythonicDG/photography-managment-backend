import uuid


def new_local_id():
    """Identifier shared with the frontend, which creates its own ids for every record."""
    return str(uuid.uuid4())
