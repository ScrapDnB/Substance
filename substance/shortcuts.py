"""Keep command keys at their US QWERTY positions across input layouts.

Only configured shortcuts and standard editing commands are translated. Plain
text and unbound combinations retain their original key and text.
"""
import sys

from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
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
