"""Basic ASS authoring with UTF-16 selection positions from Qt Quick."""
from .ass_tags import BLOCK, tokens, remove_tags

BASIC = ("b", "i", "u", "s")


def style_states(skeleton):
    """Read only the four basic font flags; retain all other ASS style data."""
    result, order, section = {}, [], ""
    for line in skeleton:
        if not line:
            continue
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.lower()
        if section not in ("[v4+ styles]", "[v4 styles]"):
            continue
        if stripped.lower().startswith("format:"):
            order = [part.strip().lower() for part in stripped.split(":", 1)[1].split(",")]
        elif stripped.lower().startswith("style:") and order:
            values = dict(zip(order, (v.strip() for v in stripped.split(":", 1)[1].split(","))))
            state = dict.fromkeys(BASIC, 0)
            for key, field in (("b", "bold"), ("i", "italic"), ("u", "underline"), ("s", "strikeout")):
                try:
                    state[key] = int(bool(int(values.get(field, "0"))))
                except ValueError:
                    pass
            result[values.get("name", "Default")] = state
    return result


def neutral_style_flags(lines):
    """Disable style font flags in serialized output without changing the source."""
    result, order, section = [], [], ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section, order = stripped.lower(), []
        if section in ("[v4+ styles]", "[v4 styles]"):
            if stripped.lower().startswith("format:"):
                order = [part.strip().lower() for part in stripped.split(":", 1)[1].split(",")]
            elif stripped.lower().startswith("style:") and order:
                head, payload = line.split(":", 1)
                values = payload.split(",")
                if len(values) == len(order):
                    for i, name in enumerate(order):
                        if name in ("bold", "italic", "underline", "strikeout"):
                            value = values[i]
                            values[i] = value.replace(value.strip(), "0") if value.strip() else "0"
                    line = head + ":" + ",".join(values)
        result.append(line)
    return result


def _python_position(text, position):
    remaining = max(0, position)
    for i, char in enumerate(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if remaining < width:
            return i
        remaining -= width
    return len(text)


def _qt_position(text, position):
    return len(text[:position].encode("utf-16-le")) // 2


def _bounds(text, start, end):
    start, end = sorted((_python_position(text, start), _python_position(text, end)))
    empty = start == end
    for block in BLOCK.finditer(text):
        if block.start() < start < block.end():
            start = block.end() if empty else block.start()
        if block.start() < end < block.end():
            end = block.end()
    return start, end


def _apply_commands(state, body, base=None, styles=None):
    for _, _, name, raw in tokens(body):
        if name == "r":
            state.update((styles or {}).get(raw[2:].strip(), base or dict.fromkeys(BASIC, 0)))
        elif name in BASIC:
            value = raw[2:].strip()
            if value and value.lstrip("-").isdigit():
                state[name] = int(value)


def _state_at(text, position, base=None, styles=None):
    state = dict(base or dict.fromkeys(BASIC, 0))
    for block in BLOCK.finditer(text):
        if block.end() > position:
            break
        _apply_commands(state, block[0][1:-1], base, styles)
    return state


def selection_state(text, start, end, base=None, styles=None):
    start, end = _bounds(text, start, end)
    state = _state_at(text, start, base, styles)
    result = {key: bool(value) for key, value in state.items()}
    if start == end:
        return result
    # A mixed selection is shown as off, so one click applies to all of it.
    seen, cursor = False, start
    for block in BLOCK.finditer(text, start, end):
        if block.start() > cursor:
            for key in BASIC:
                result[key] = (result[key] if seen else True) and bool(state[key])
            seen = True
        _apply_commands(state, block[0][1:-1], base, styles)
        cursor = block.end()
    if cursor < end:
        for key in BASIC:
            result[key] = (result[key] if seen else True) and bool(state[key])
    return result


def toggle_format(text, start, end, kind, base=None, styles=None):
    if kind not in BASIC:
        raise ValueError("Неизвестное оформление ASS")
    active = selection_state(text, start, end, base, styles)[kind]
    start, end = _bounds(text, start, end)
    restore = _state_at(text, end, base, styles)[kind]
    value = 0 if active else 1
    opening = "{\\" + kind + str(value) + "}"
    # A selected range ending at the end of the cue has no following text whose
    # formatting needs restoring. Keep pairs for insertion at an empty cursor.
    closing = "" if start < end == len(text) else "{\\" + kind + str(restore) + "}"
    body = remove_tags(text[start:end], {kind})

    def keep_after_reset(block):
        commands = list(tokens(block[0][1:-1]))
        if any(name == "r" for _, _, name, _ in commands):
            return block[0][:-1] + "\\" + kind + str(value) + "}"
        return block[0]

    body = BLOCK.sub(keep_after_reset, body)
    result = text[:start] + opening + body + closing + text[end:]
    first, last = start + len(opening), start + len(opening) + len(body)
    return {"text": result, "start": _qt_position(result, first), "end": _qt_position(result, last)}
