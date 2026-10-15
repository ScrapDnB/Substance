"""Inherit only overrides that enclose the whole source line, never fragments."""
from .ass_tags import BLOCK, command_names, tokens
from .ass_formatting import _python_position, _qt_position
from .document import plain_text


def whole_line_template(original):
    if not plain_text(original).strip():
        return None
    prefix, suffix = [], []
    for block in BLOCK.finditer(original):
        if not list(tokens(block[0][1:-1])):
            continue
        # Vector drawings and timed karaoke cannot be applied to translated speech.
        if set(command_names(block[0][1:-1])) & {"p", "pbo", "k", "K", "kf", "ko", "kt"}:
            return None
        before = bool(plain_text(original[:block.start()]).strip())
        after = bool(plain_text(original[block.end():]).strip())
        if before and after:
            return None
        (suffix if before else prefix).append(block[0])
    return ("".join(prefix), "".join(suffix)) if prefix or suffix else None


def inherit_formatting(original, text, start=0, end=0, cursor=0):
    unchanged = {"text": text, "start": start, "end": end, "cursor": cursor}
    template = whole_line_template(original)
    if template is None or not plain_text(text).strip():
        return unchanged
    opening, closing = template
    # Existing inline formatting is an explicit authoring choice, including
    # manual partial formatting. Never reposition or replace those commands.
    if any(list(tokens(m[0][1:-1])) for m in BLOCK.finditer(text)):
        return unchanged
    result = opening + text + closing

    def mapped(position):
        return _qt_position(result, len(opening) + _python_position(text, position))

    return {"text": result, "start": mapped(start), "end": mapped(end), "cursor": mapped(cursor)}
