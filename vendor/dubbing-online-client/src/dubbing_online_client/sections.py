"""Navigation visibility is separate from authorization to mutate project data."""

SECTIONS = ("management", "casting", "text", "glossary")


def visible_sections(roles, override=None, *, server_admin=False):
    if server_admin:
        return list(SECTIONS)
    if override is not None:
        return [section for section in SECTIONS if section in override]
    defaults = {"text", "glossary"}
    if set(roles).intersection({"admin", "chief_editor", "casting_director"}):
        defaults.update(SECTIONS)
    elif set(roles).intersection({"director", "sound_engineer"}):
        defaults.add("casting")
    return [section for section in SECTIONS if section in defaults]
