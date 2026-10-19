"""Keep command keys at their US QWERTY positions across input layouts.

Only configured shortcuts and standard editing commands are translated. Plain
text and unbound combinations retain their original key and text.
"""
import sys

from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QWindow
from PySide6.QtWidgets import QApplication, QKeySequenceEdit


# Carbon HIToolbox Events.h: kVK_ANSI_* (keyCode is a physical position).
MAC_KEYS = dict(zip(
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17,
     18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32,
     33, 34, 35, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 50],
    "ASDFHGZXCVBQWERYT123465=97-80]OU[IPLJ'K;\\,/NM.`"))
PC_KEYS = {**dict(zip(range(2, 14), "1234567890-=")),
           **dict(zip(range(16, 28), "QWERTYUIOP[]")),
           **dict(zip(range(30, 42), "ASDFGHJKL;'`")),
           43: "\\", **dict(zip(range(44, 54), "ZXCVBNM,./"))}
SHIFTED = dict(zip("1234567890-=[]\\;',./`", "!@#$%^&*()_+{}|:\"<>?~"))
COMMAND_MODIFIERS = Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier

# Qt calls Command "Ctrl" and physical Control "Meta" on macOS.
TIMING_NUDGES = {
    'nudge' + edge.title() + direction + suffix: (edge, sign, fine)
    for edge in ('start', 'end', 'both')
    for direction, sign in (('Back', -1), ('Forward', 1))
    for suffix, fine in (('', False), ('Fine', True))
}


def timing_shortcut_defaults(platform):
    modifiers = {'start': 'Meta' if platform == 'darwin' else 'Ctrl',
                 'end': 'Ctrl' if platform == 'darwin' else 'Ctrl+Alt', 'both': 'Alt'}
    return {name: modifiers[edge] + ('+Shift' if fine else '') +
            ('+Left' if direction < 0 else '+Right')
            for name, (edge, direction, fine) in TIMING_NUDGES.items()}


def physical_character(event, platform):
    if platform == 'cocoa':
        # A is keyCode 0. Native modifiers distinguish it from synthetic events
        # that carry no hardware information at all.
        if not (event.nativeVirtualKey() or event.nativeModifiers()):
            return None
        return MAC_KEYS.get(event.nativeVirtualKey())
    scan = event.nativeScanCode()
    if platform == 'windows':
        return PC_KEYS.get(scan)  # Extended and keypad scans are deliberately absent.
    return None


class LayoutShortcuts(QObject):
    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self.app = QApplication.instance()
        self.platform = self.app.platformName()
        self._forwarding = False
        self._monitor = self._monitor_handler = None
        self.refresh()
        backend.preferencesChanged.connect(self.refresh)
        self.app.installEventFilter(self)
        if self.platform == 'cocoa' and sys.platform == 'darwin':
            # Runs before AppKit's native menu matching and input method. This
            # replaces only this application's event; it never posts a new key.
            from AppKit import NSEvent, NSEventMaskKeyDown, NSEventMaskKeyUp
            self._monitor_handler = self._native_event
            self._monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                NSEventMaskKeyDown | NSEventMaskKeyUp, self._monitor_handler)

    def refresh(self):
        sequences = list(self.backend.shortcuts.values())
        for standard in (QKeySequence.Copy, QKeySequence.Cut, QKeySequence.Paste,
                         QKeySequence.SelectAll, QKeySequence.Undo, QKeySequence.Redo,
                         QKeySequence.Close, QKeySequence.Quit, QKeySequence.Preferences):
            sequences.extend(QKeySequence.keyBindings(standard))
        self.bindings = set()
        for sequence in sequences:
            parsed = QKeySequence(sequence)
            if parsed.count() == 1:
                combination = parsed[0]
                self.bindings.add((int(combination.key()), combination.keyboardModifiers().value))
        self.timing_bindings = {}
        for name, command in TIMING_NUDGES.items():
            parsed = QKeySequence(self.backend.shortcuts.get(name, ''))
            if parsed.count() == 1:
                combination = parsed[0]
                self.timing_bindings[(int(combination.key()), combination.keyboardModifiers().value)] = command

    def _capture_focused(self):
        item = self.app.focusWidget()
        while item is not None:
            if isinstance(item, QKeySequenceEdit):
                return True
            item = item.parentWidget()
        return False

    def _command_character(self, base, modifiers):
        if base is None or not modifiers & COMMAND_MODIFIERS:
            return None
        character = SHIFTED.get(base, base) if modifiers & Qt.ShiftModifier else base
        if (ord(character), modifiers.value) in self.bindings or self._capture_focused():
            return character
        return None

    def eventFilter(self, receiver, event):
        if self._forwarding or event.type() not in (QEvent.ShortcutOverride, QEvent.KeyPress, QEvent.KeyRelease):
            return False
        character = self._command_character(physical_character(event, self.platform), event.modifiers())
        command = self.timing_bindings.get((ord(character) if character else event.key(), event.modifiers().value))
        # QWindow is the actual key-event target. During native activation
        # transitions QApplication.focusWindow() can still refer to the old one.
        window = receiver if isinstance(receiver, QWindow) else self.app.focusWindow()
        if command and window is not None and window.objectName() == 'substanceWindow' and window.property('timingShortcutsEnabled'):
            # Reserve these commands before TextInput's cursor/selection keys.
            # This also supports auto-repeat and physical keys in other layouts.
            if event.type() == QEvent.KeyPress:
                self.backend.nudgeTiming(*command)
            event.accept()
            return True
        if character is None or ord(character) == event.key():
            return False
        if event.type() == QEvent.ShortcutOverride:
            # Prevent a different logical shortcut from winning before KeyPress.
            event.accept()
            return True
        translated = QKeyEvent(event.type(), ord(character), event.modifiers(),
                               event.text(), event.isAutoRepeat(), event.count())
        translated.setTimestamp(event.timestamp())
        self._forwarding = True
        try:
            self.app.sendEvent(receiver, translated)
        finally:
            self._forwarding = False
        event.setAccepted(translated.isAccepted())
        return True

    def _native_event(self, event):
        from AppKit import (NSEvent, NSEventModifierFlagCommand, NSEventModifierFlagControl,
                            NSEventModifierFlagOption, NSEventModifierFlagShift)
        flags = event.modifierFlags()
        modifiers = Qt.NoModifier
        for flag, modifier in ((NSEventModifierFlagCommand, Qt.ControlModifier),
                               (NSEventModifierFlagControl, Qt.MetaModifier),
                               (NSEventModifierFlagOption, Qt.AltModifier),
                               (NSEventModifierFlagShift, Qt.ShiftModifier)):
            if flags & flag:
                modifiers |= modifier
        character = self._command_character(MAC_KEYS.get(event.keyCode()), modifiers)
        if character is None:
            return event
        if str(event.charactersIgnoringModifiers() or '').upper() == character:
            return event
        native_character = character if modifiers & Qt.ShiftModifier else character.lower()
        return NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
            event.type(), event.locationInWindow(), flags, event.timestamp(),
            event.windowNumber(), None, native_character, native_character, event.isARepeat(), event.keyCode()) or event

    def detach(self):
        self.app.removeEventFilter(self)
        if self._monitor is not None:
            from AppKit import NSEvent
            NSEvent.removeMonitor_(self._monitor)
            self._monitor = self._monitor_handler = None
