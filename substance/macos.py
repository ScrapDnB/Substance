"""Native macOS toolbar using the AppKit boundary from Dubbing Manager.

Qt retains ownership of its content view, focus, geometry and event handling.
"""
from ctypes import c_void_p
import logging
import os
import sys

from PySide6.QtCore import QObject, Property, Signal
from PySide6.QtGui import QColor, QGuiApplication

log = logging.getLogger(__name__)

if sys.platform == 'darwin':
    import objc
    from AppKit import (NSApplication, NSAppearance, NSAppearanceNameAqua, NSAppearanceNameDarkAqua,
                        NSColor, NSColorSpace, NSImage, NSImageSymbolConfiguration, NSFont, NSFontWeightRegular,
                        NSControlSizeRegular, NSSegmentStyleAutomatic, NSMakeRect, NSSegmentedControl, NSToolbar, NSToolbarItem,
                        NSToolbarDisplayModeIconOnly, NSToolbarFlexibleSpaceItemIdentifier,
                        NSToolbarSpaceItemIdentifier, NSWindowToolbarStyleUnified, NSTitlebarSeparatorStyleNone)
    from Foundation import NSObject, NSSet, NSClassFromString

    def toolbar_symbol(name, label):
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, label)
        if image is not None:
            configuration = NSImageSymbolConfiguration.configurationWithPointSize_weight_(15, NSFontWeightRegular)
            return image.imageWithSymbolConfiguration_(configuration)
        return None

    class _SubstanceToolbarDelegate(NSObject):
        def initWithOwner_(self, owner):
            self = objc.super(_SubstanceToolbarDelegate, self).init()
            if self is not None:
                self.owner, self.items, self.mode_control = owner, {}, None
            return self

        def toolbarAllowedItemIdentifiers_(self, _toolbar):
            return self.owner.identifiers

        def toolbarDefaultItemIdentifiers_(self, _toolbar):
            return self.owner.default_identifiers

        def toolbarSelectableItemIdentifiers_(self, _toolbar):
            return []

        def toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(self, _toolbar, identifier, _insert):
            key = str(identifier)
            item = NSToolbarItem.alloc().initWithItemIdentifier_(identifier)
            if key == self.owner.MODE:
                item.setLabel_('Режим редактора')
                item.setPaletteLabel_('Режим редактора')
                item.setVisibilityPriority_(1000)
                control = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 0))
                control.setControlSize_(NSControlSizeRegular)
                control.setSegmentStyle_(NSSegmentStyleAutomatic)
                control.setFont_(NSFont.systemFontOfSize_(13))
                control.setSegmentCount_(2)
                for index, label in enumerate(('Тайминг', 'Перевод')):
                    control.setLabel_forSegment_(label, index)
                    control.setWidth_forSegment_(92, index)
                control.sizeToFit()
                control.setSelectedSegment_(int(self.owner.backend.mode == 'translation'))
                control.setTarget_(self)
                control.setAction_('modeChanged:')
                item.setView_(control)
                self.mode_control = control
            else:
                label, symbol, _command = self.owner.ACTIONS[key]
                item.setLabel_(label)
                item.setPaletteLabel_(label)
                item.setToolTip_(label)
                item.setImage_(toolbar_symbol(symbol, label))
                item.setTarget_(self)
                item.setAction_('toolbarAction:')
                # Public AppKit API: system grouping, material and accessibility.
                item.setBordered_(True)
                if key in ('substance.checks', 'substance.reflow', 'substance.align', 'substance.scenes', 'substance.portraits'):
                    item.setVisibilityPriority_(800)
                # AppKit places navigation controls before the document title.
                item.setNavigational_(key == self.owner.SIDEBAR)
            self.items[key] = item
            return item

        def toolbarAction_(self, sender):
            self.owner.perform(str(sender.itemIdentifier()))

        def modeChanged_(self, sender):
            self.owner.backend.setMode('translation' if sender.selectedSegment() else 'timing')
            # Invalid pending time can reject the change; restore the actual mode.
            self.owner.sync()

        def validateToolbarItem_(self, item):
            return self.owner.enabled(str(item.itemIdentifier()))


class MacOSIntegration(QObject):
    nativeToolbarActiveChanged = Signal()
    platformPaletteChanged = Signal()
    sidebarRequested = Signal()
    settingsRequested = Signal()
    MODE = 'substance.mode'
    SIDEBAR = 'substance.sidebar'
    ACTIONS = {
        SIDEBAR: ('Боковая панель', 'sidebar.left', None),
        'substance.new': ('Новый документ', 'doc.badge.plus', 'newDocument'),
        'substance.open': ('Открыть…', 'folder', 'openDialog'),
        'substance.save': ('Сохранить', 'square.and.arrow.down', 'save'),
        'substance.save-as': ('Сохранить как…', 'square.and.arrow.down.on.square', 'saveAs'),
        'substance.undo': ('Отменить', 'arrow.uturn.backward', 'undo'),
        'substance.redo': ('Повторить', 'arrow.uturn.forward', 'redo'),
        'substance.media': ('Открыть видео или аудио…', 'film', 'openMedia'),
        'substance.transcribe': ('Распознать речь…', 'captions.bubble', 'openTranscription'),
        'substance.hardsub': ('Найти и распознать хардсаб…', 'text.viewfinder', 'openHardsub'),
        'substance.portraits': ('Автопортреты из видео…', 'person.crop.square', 'openAutoPortraits'),
        'substance.checks': ('Проверить и исправить…', 'checklist', 'openChecks'),
        'substance.reflow': ('Переносы и разбиение…', 'text.alignleft', 'openReflow'),
        'substance.align': ('Уточнить тайминг по речи…', 'waveform.badge.magnifyingglass', 'openAlignment'),
        'substance.point-sync': ('Точечная синхронизация…', 'point.topleft.down.to.point.bottomright.curvepath', 'openPointSync'),
        'substance.time-shift': ('Сдвиг времени…', 'arrow.left.and.right', 'openShift'),
        'substance.scenes': ('Найти смены планов…', 'film.stack', 'openScenes'),
        'substance.settings': ('Настройки…', 'gearshape', None),
        'substance.export': ('Экспорт…', 'square.and.arrow.up', 'exportDialog'),
    }

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._toolbar = self._delegate = self._window = None
        self._active = False
        self._content_pointer = self._parent_pointer = 0
        self._palette = {}
        backend.changed.connect(self.sync)
        backend.currentChanged.connect(self.sync)
        backend.preferencesChanged.connect(self.sync_appearance)
        backend.media_controller.changed.connect(self.sync)
        self.refresh_palette()
        app = QGuiApplication.instance()
        app.styleHints().colorSchemeChanged.connect(self.refresh_palette)
        app.paletteChanged.connect(self.refresh_palette)

    @Property('QVariantMap', notify=platformPaletteChanged)
    def platformPalette(self):
        return self._palette

    def refresh_palette(self, *_args):
        if sys.platform != 'darwin':
            return
        app = NSApplication.sharedApplication()
        appearance = app.effectiveAppearance() if self.backend.theme == 'system' else NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua if self.backend.theme == 'dark' else NSAppearanceNameAqua)
        colors = {}
        def resolve():
            alternating = NSColor.alternatingContentBackgroundColors()
            native = {
                'text': NSColor.labelColor(), 'muted': NSColor.secondaryLabelColor(),
                'surface': NSColor.textBackgroundColor(), 'alternate': alternating[-1],
                'sidebar': NSColor.windowBackgroundColor(), 'header': NSColor.windowBackgroundColor(),
                'button': NSColor.controlColor(), 'border': NSColor.separatorColor(),
                'selection': NSColor.selectedContentBackgroundColor(),
                'selectedText': NSColor.alternateSelectedControlTextColor(),
                'accent': NSColor.controlAccentColor(), 'warning': NSColor.systemOrangeColor(),
                'success': NSColor.systemGreenColor(),
            }
            for key, color in native.items():
                rgb = color.colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
                colors[key] = QColor.fromRgbF(rgb.redComponent(), rgb.greenComponent(), rgb.blueComponent(), rgb.alphaComponent())
        appearance.performAsCurrentDrawingAppearance_(resolve)
        if self._palette != colors:
            self._palette = colors
            self.platformPaletteChanged.emit()

    @Property(bool, notify=nativeToolbarActiveChanged)
    def nativeToolbarActive(self):
        return self._active

    @Property(bool, constant=True)
    def liquidGlassAvailable(self):
        return (sys.platform == 'darwin' and QGuiApplication.platformName() == 'cocoa'
                and NSClassFromString('NSGlassEffectView') is not None
                and os.environ.get('SUBSTANCE_DISABLE_GLASS') != '1')

    @property
    def identifiers(self):
        if sys.platform != 'darwin':
            return list(self.ACTIONS) + [self.MODE]
        return list(self.ACTIONS) + [self.MODE, NSToolbarFlexibleSpaceItemIdentifier, NSToolbarSpaceItemIdentifier]

    @property
    def default_identifiers(self):
        if sys.platform != 'darwin':
            return list(self.ACTIONS) + [self.MODE]
        space, flexible = NSToolbarSpaceItemIdentifier, NSToolbarFlexibleSpaceItemIdentifier
        return [self.SIDEBAR, flexible, self.MODE, flexible,
                'substance.new', 'substance.open', 'substance.save', space,
                'substance.undo', 'substance.redo', space,
                'substance.media', 'substance.transcribe', 'substance.portraits', space,
                'substance.checks', 'substance.reflow', 'substance.align', 'substance.point-sync', 'substance.time-shift', 'substance.scenes',
                space, 'substance.export', 'substance.settings']

    def configure(self, window):
        if sys.platform != 'darwin' or QGuiApplication.platformName() != 'cocoa' or self._active:
            return
        ns_window = toolbar = None
        try:
            view = objc.objc_object(c_void_p=int(window.winId()))
            ns_window = view.window()
            if ns_window is None:
                return
            self._content_pointer = int(objc.pyobjc_id(ns_window.contentView()))
            self._parent_pointer = int(objc.pyobjc_id(view.superview()))
            # A new layout identifier avoids restoring the previous default order.
            toolbar = NSToolbar.alloc().initWithIdentifier_('dev.scrapdnb.substance.toolbar.v8')
            delegate = _SubstanceToolbarDelegate.alloc().initWithOwner_(self)
            toolbar.setDelegate_(delegate)
            toolbar.setDisplayMode_(NSToolbarDisplayModeIconOnly)
            toolbar.setAllowsUserCustomization_(True)
            toolbar.setAutosavesConfiguration_(not bool(os.environ.get('SUBSTANCE_DATA_DIR')))
            toolbar.setCenteredItemIdentifiers_(NSSet.setWithObject_(self.MODE))
            ns_window.setToolbar_(toolbar)
            ns_window.setToolbarStyle_(NSWindowToolbarStyleUnified)
            ns_window.setTitlebarAppearsTransparent_(True)
            ns_window.setTitlebarSeparatorStyle_(NSTitlebarSeparatorStyleNone)
            ns_window.setBackgroundColor_(NSColor.windowBackgroundColor())
            self._toolbar, self._delegate, self._window = toolbar, delegate, ns_window
            self._active = True
            self.sync_appearance()
            self.sync()
            self.nativeToolbarActiveChanged.emit()
        except Exception:
            if ns_window is not None:
                ns_window.setToolbar_(None)
            if toolbar is not None:
                toolbar.setDelegate_(None)
            self._toolbar = self._delegate = self._window = None
            self._active = False
            log.exception('Could not attach the native toolbar; using the Qt toolbar')

    def enabled(self, key):
        if key in ('substance.checks', 'substance.reflow', 'substance.align', 'substance.point-sync', 'substance.time-shift'):
            return self.backend.count > 0 and not self.backend.busy
        if key in ('substance.transcribe', 'substance.portraits'):
            return not self.backend.busy
        if key in ('substance.new', 'substance.open') or key == self.MODE:
            return not self.backend.busy
        if key == 'substance.undo':
            return self.backend.canUndo or self.backend.dirty
        if key == 'substance.redo':
            return self.backend.canRedo
        return True

    def perform(self, key):
        if key not in self.ACTIONS or not self.enabled(key):
            return
        if key == self.SIDEBAR:
            self.sidebarRequested.emit()
        elif key == 'substance.settings':
            self.settingsRequested.emit()
        elif key == 'substance.export':
            self.backend.exportDialog(False)
        else:
            getattr(self.backend, self.ACTIONS[key][2])()
        self.sync()

    def sync(self):
        if self._toolbar is None:
            return
        control = self._delegate.mode_control
        if control is not None:
            control.setSelectedSegment_(int(self.backend.mode == 'translation'))
            control.setEnabled_(not self.backend.busy)
        # Include overflow items, which AppKit does not validate automatically.
        for key, item in self._delegate.items.items():
            item.setEnabled_(self.enabled(key))

    def sync_appearance(self):
        if self._window is None:
            self.refresh_palette()
            return
        appearance = None if self.backend.theme == 'system' else NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua if self.backend.theme == 'dark' else NSAppearanceNameAqua)
        NSApplication.sharedApplication().setAppearance_(appearance)
        self._window.setAppearance_(appearance)
        self.refresh_palette()

    def diagnostics(self, window):
        if self._window is None:
            return {'nativeToolbar': False}
        view = objc.objc_object(c_void_p=int(window.winId()))
        sidebar = window.findChild(QObject, 'nativeGlassSidebar')
        # app.exec() may already have detached the native content view on quit.
        content_view, parent_view = self._window.contentView(), view.superview()
        return {'nativeToolbar': self._active, 'nativeToolbarItems': [str(item.itemIdentifier()) for item in self._toolbar.items()],
                'liquidGlassAvailable': self.liquidGlassAvailable,
                'nativeGlassSidebar': bool(sidebar and sidebar.active),
                'qtContentViewPreserved': content_view is not None and int(objc.pyobjc_id(content_view)) == self._content_pointer,
                'qtViewParentPreserved': parent_view is not None and int(objc.pyobjc_id(parent_view)) == self._parent_pointer}

    def detach(self):
        if self._window is not None:
            self._window.setToolbar_(None)
        if self._toolbar is not None:
            self._toolbar.setDelegate_(None)
        self._toolbar = self._delegate = self._window = None
        self._active = False
