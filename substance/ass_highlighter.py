"""Visual formatting only: QTextDocument always retains the exact plain text."""
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from .ass_tags import BLOCK, tokens


class AssHighlighter(QSyntaxHighlighter):
    def __init__(self, document, formatted=False):
        super().__init__(document)
        self.formatted = formatted
        self.base = {}
        self.styles = {}

    def highlightBlock(self, text):
        def mask(style):
            return sum(bit for key, bit in (("b", 1), ("i", 2), ("u", 4), ("s", 8)) if style.get(key))
        previous = self.previousBlockState()
        state = (previous if previous >= 0 else mask(self.base)) if self.formatted else 0
        cursor = 0

        def put(start, end, fmt):
            # Qt positions count UTF-16 code units, Python indexes Unicode scalars.
            offset = len(text[:start].encode("utf-16-le")) // 2
            length = len(text[start:end].encode("utf-16-le")) // 2
            self.setFormat(offset, length, fmt)

        def style():
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Weight.Bold if state & 1 else QFont.Weight.Normal)
            fmt.setFontItalic(bool(state & 2))
            fmt.setFontUnderline(bool(state & 4))
            fmt.setFontStrikeOut(bool(state & 8))
            return fmt

        for block in BLOCK.finditer(text):
            commands = list(tokens(block[0][1:-1]))
            if not commands:
                continue
            put(cursor, block.start(), style())
            tag = QTextCharFormat()
            if self.formatted:
                tag.setForeground(QColor(0, 0, 0, 0))
                tag.setFontPointSize(0.1)
            else:
                tag.setForeground(QColor("#6986bb"))
            put(block.start(), block.end(), tag)
            if self.formatted:
                for _, _, name, raw in commands:
                    if name == "r":
                        state = mask(self.styles.get(raw[2:].strip(), self.base))
                    elif name in ("b", "i", "u", "s"):
                        value = raw[2:].strip()
                        bit = {"b": 1, "i": 2, "u": 4, "s": 8}[name]
                        if value and value.lstrip("-").isdigit():
                            state = state | bit if int(value) else state & ~bit
            cursor = block.end()
        put(cursor, len(text), style())
        self.setCurrentBlockState(state)
