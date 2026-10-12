from evennia_links import runtime


def boolean(value):
    return type(value) is bool


def positive(value):
    return type(value) is int and value > 0


def register():
    runtime.register(
        "BUILDING_REVEALED", False, validator=boolean, description="Reveal player interiors."
    )
    runtime.register(
        "BUILDING_PROJECT_LIMIT", 2, validator=positive, description="Open projects per character."
    )
    runtime.register(
        "BUILDING_ROOM_LIMIT",
        15,
        validator=positive,
        description="Total unpromoted rooms per character.",
    )
    runtime.register(
        "BUILDING_DOOR_LIMIT",
        6,
        validator=positive,
        description="Attachment door warning threshold.",
    )
    runtime.register(
        "BUILDING_DOOR_LIMIT_HARD",
        False,
        validator=boolean,
        description="Enforce the door threshold as a hard limit.",
    )
