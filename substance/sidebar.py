"""AppKit navigation hosted inside real Liquid Glass, without moving Qt's view.

The QML item reserves layout space; every control on glass is an AppKit child
of NSGlassEffectView.contentView so the system owns legibility and input.
"""
from ctypes import c_void_p
import logging
import sys

from PySide6.QtCore import QObject, Property, QRectF, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QmlElement
from PySide6.QtQuick import QQuickItem

from .tooltips import tooltip_rect

QML_IMPORT_NAME = 'Substance'
QML_IMPORT_MAJOR_VERSION = 1
log = logging.getLogger(__name__)

FILTERS = (
    ('all', 'Все реплики', 'text.alignleft'),
    ('warnings', 'Замечания', 'exclamationmark.triangle'),
    ('notes', 'С заметками', 'note.text'),
    ('proposals', 'Предложения правок', 'text.badge.plus'),
    ('characters', 'Персонажи', 'person.crop.square'),
)

if sys.platform == 'darwin':
    import objc
    import AppKit as AK
    from Foundation import NSObject, NSString, NSIndexSet, NSClassFromString

    def label(text, small=False):
        field = AK.NSTextField.labelWithString_(text)
        field.setFont_(AK.NSFont.systemFontOfSize_(10 if small else 12))
        field.setTextColor_(AK.NSColor.secondaryLabelColor() if small else AK.NSColor.labelColor())
        field.setTranslatesAutoresizingMaskIntoConstraints_(False)
        return field

    class _SidebarDelegate(NSObject):
        def initWithHost_(self, host):
            self = objc.super(_SidebarDelegate, self).init()
            if self is not None:
                self.host = host
                self.nodes = [NSString.stringWithString_(row[0]) for row in FILTERS]
            return self

        def outlineView_numberOfChildrenOfItem_(self, view, item):
            return len(self.nodes) if item is None else 0

        def outlineView_isItemExpandable_(self, view, item):
            return False

        def outlineView_child_ofItem_(self, view, index, item):
            return self.nodes[index]

        def outlineView_viewForTableColumn_item_(self, view, column, item):
            index = next(i for i, row in enumerate(FILTERS) if row[0] == str(item))
            key, title, symbol = FILTERS[index]
            cell = AK.NSTableCellView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 160, 32))
            text = label(title)
            count = label(str(self.host.backend.counts[key]), True)
            text.setFont_(AK.NSFont.systemFontOfSize_(12 * self.host.scale))
            count.setFont_(AK.NSFont.systemFontOfSize_(10 * self.host.scale))
            image = AK.NSImageView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 16, 16))
            image.setTranslatesAutoresizingMaskIntoConstraints_(False)
            image.setImage_(AK.NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, title))
            cell.setTextField_(text)
            cell.setImageView_(image)
            for child in (image, text, count):
                cell.addSubview_(child)
            AK.NSLayoutConstraint.activateConstraints_([
                image.leadingAnchor().constraintEqualToAnchor_(cell.leadingAnchor()),
                image.centerYAnchor().constraintEqualToAnchor_(cell.centerYAnchor()),
                image.widthAnchor().constraintEqualToConstant_(16),
                image.heightAnchor().constraintEqualToConstant_(16),
                text.leadingAnchor().constraintEqualToAnchor_constant_(image.trailingAnchor(), 7),
                text.centerYAnchor().constraintEqualToAnchor_(cell.centerYAnchor()),
                count.trailingAnchor().constraintEqualToAnchor_constant_(cell.trailingAnchor(), -4),
                count.centerYAnchor().constraintEqualToAnchor_(cell.centerYAnchor()),
                text.trailingAnchor().constraintLessThanOrEqualToAnchor_constant_(count.leadingAnchor(), -6),
            ])
            return cell

        def outlineViewSelectionDidChange_(self, notification):
            host = self.host
            row = host.outline.selectedRow()
            if not host.syncing and 0 <= row < len(FILTERS):
                host.backend.setFilter(FILTERS[row][0])
                # flush() can reject a filter change; restore backend selection.
                host.sync()

        def characterChanged_(self, sender):
            self.host.backend.setCharacterFilter('' if sender.indexOfSelectedItem() == 0 else str(sender.titleOfSelectedItem()))
            self.host.sync()

        def openMedia_(self, sender):
            self.host.backend.openMedia()

    class _SidebarHost:
        def __init__(self, window, backend):
            self.backend, self.syncing, self.snapshot = backend, False, None
            self.scale = backend.appearance.general['uiScale'] / 100
            self.qt_view = objc.objc_object(c_void_p=int(window.winId()))
            self.effect = NSClassFromString('NSGlassEffectView').alloc().initWithFrame_(AK.NSMakeRect(0, 0, 0, 0))
            self.effect.setStyle_(0)  # NSGlassEffectViewStyleRegular (macOS 26).
            self.effect.setCornerRadius_(16)
            self.effect.setAccessibilityElement_(True)
            self.effect.setAccessibilityRole_(AK.NSAccessibilityGroupRole)
            self.effect.setAccessibilityLabel_('Навигация документа')
            self.effect.setHidden_(True)
            self.content = AK.NSView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 180, 600))
            self.delegate = _SidebarDelegate.alloc().initWithHost_(self)
            self.outline = AK.NSOutlineView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 160, 170))
            column = AK.NSTableColumn.alloc().initWithIdentifier_('filter')
            column.setWidth_(160)
            self.outline.addTableColumn_(column)
            self.outline.setOutlineTableColumn_(column)
            self.outline.setHeaderView_(None)
            self.outline.setRowHeight_(32 * self.scale)
            self.outline.setIndentationPerLevel_(0)
            self.outline.setSelectionHighlightStyle_(AK.NSTableViewSelectionHighlightStyleSourceList)
            self.outline.setBackgroundColor_(AK.NSColor.clearColor())
            self.outline.setAllowsEmptySelection_(False)
            self.outline.setAllowsMultipleSelection_(False)
            self.outline.setDataSource_(self.delegate)
            self.outline.setDelegate_(self.delegate)
            self.outline.setAutoresizingMask_(AK.NSViewWidthSizable)
            self.outline.setAccessibilityLabel_('Фильтры документа')
            scroll = AK.NSScrollView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 160, 170))
            scroll.setDrawsBackground_(False)
            scroll.setBorderType_(AK.NSNoBorder)
            scroll.setDocumentView_(self.outline)
            scroll.setHasVerticalScroller_(False)
            scroll.setTranslatesAutoresizingMaskIntoConstraints_(False)
            self.character = AK.NSPopUpButton.alloc().initWithFrame_pullsDown_(AK.NSMakeRect(0, 0, 160, 26), False)
            self.character.setFont_(AK.NSFont.systemFontOfSize_(12))
            self.character.setTarget_(self.delegate)
            self.character.setAction_('characterChanged:')
            self.character.setAccessibilityLabel_('Фильтр по персонажу')
            separator = AK.NSBox.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 160, 1))
            separator.setBoxType_(AK.NSBoxSeparator)
            self.media = label('Медиа не подключено')
            self.media.setLineBreakMode_(AK.NSLineBreakByTruncatingMiddle)
            self.media.setToolTip_('Медиа не подключено')
            self.keyframes = label('Ключевые кадры не загружены', True)
            self.keyframes.setLineBreakMode_(AK.NSLineBreakByTruncatingTail)
            self.open_button = AK.NSButton.buttonWithTitle_target_action_('Подключить…', self.delegate, 'openMedia:')
            self.open_button.setBezelStyle_(AK.NSBezelStyleRounded)
            spacer = AK.NSView.alloc().initWithFrame_(AK.NSMakeRect(0, 0, 0, 0))
            children = [label('ДОКУМЕНТ', True), scroll, label('ПЕРСОНАЖ', True), self.character,
                        separator, label('МЕДИА', True), self.media, self.keyframes, self.open_button,
                        spacer, label('Substance ' + backend.version, True)]
            self.font_nodes = [(child, child.font().pointSize()) for child in children
                               if child.respondsToSelector_('font') and child.font()]
            self.stack = AK.NSStackView.stackViewWithViews_(children)
            self.stack.setOrientation_(AK.NSUserInterfaceLayoutOrientationVertical)
            self.stack.setAlignment_(AK.NSLayoutAttributeLeading)
            self.stack.setSpacing_(10)
            self.stack.setTranslatesAutoresizingMaskIntoConstraints_(False)
            self.content.addSubview_(self.stack)
            self.scroll_height = scroll.heightAnchor().constraintEqualToConstant_(170 * self.scale)
            constraints = [self.stack.leadingAnchor().constraintEqualToAnchor_constant_(self.content.leadingAnchor(), 12),
                           self.stack.trailingAnchor().constraintEqualToAnchor_constant_(self.content.trailingAnchor(), -12),
                           self.stack.topAnchor().constraintEqualToAnchor_constant_(self.content.topAnchor(), 16),
                           self.stack.bottomAnchor().constraintEqualToAnchor_constant_(self.content.bottomAnchor(), -12),
                           self.scroll_height]
            for child in children:
                child.setTranslatesAutoresizingMaskIntoConstraints_(False)
                constraints.append(child.widthAnchor().constraintEqualToAnchor_(self.stack.widthAnchor()))
            AK.NSLayoutConstraint.activateConstraints_(constraints)
            self.effect.setContentView_(self.content)
            # Only the AppKit navigation is embedded on glass. Qt owns its
            # original root view, content geometry, text focus and media scene.
            self.parent_view = self.qt_view.superview()
            # QNSView exports only Qt's accessibility root, ignoring native
            # children. A sibling above it preserves AppKit's accessibility tree.
            self.parent_view.addSubview_positioned_relativeTo_(self.effect, 1, self.qt_view)
            backend.changed.connect(self.sync)
            backend.media_controller.changed.connect(self.sync)
            backend.appearance.changed.connect(self.sync_appearance)
            self.sync_appearance()
            self.sync()

        def sync_appearance(self):
            if self.effect is None:
                return
            self.scale = self.backend.appearance.general['uiScale'] / 100
            for node, size in self.font_nodes:
                node.setFont_(AK.NSFont.systemFontOfSize_(size * self.scale))
            self.outline.setRowHeight_(32 * self.scale)
            self.scroll_height.setConstant_(170 * self.scale)
            self.snapshot = None
            self.sync()

        def sync(self):
            if self.effect is None or self.syncing:
                return
            self.syncing = True
            try:
                backend = self.backend
                row = next(i for i, f in enumerate(FILTERS) if f[0] == backend.activeFilter)
                if self.outline.selectedRow() != row:
                    self.outline.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(row), False)
                selected = backend.characterFilter
                titles = ['Все персонажи'] + list(backend.characters)
                if [str(item.title()) for item in self.character.itemArray()] != titles:
                    self.character.removeAllItems()
                    self.character.addItemsWithTitles_(titles)
                self.character.selectItemAtIndex_(titles.index(selected) if selected in titles else 0)
                state = (tuple(backend.counts.values()), tuple(backend.characters), backend.activeFilter,
                         backend.characterFilter, backend.media_controller.name, backend.media_controller.keyframeCount,
                         backend.busy)
                if state == self.snapshot:
                    return
                self.snapshot = state
                self.outline.reloadData()
                row = next(i for i, f in enumerate(FILTERS) if f[0] == backend.activeFilter)
                self.outline.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(row), False)
                self.character.setEnabled_(not backend.busy)
                self.outline.setEnabled_(not backend.busy)
                name = backend.media_controller.name
                self.media.setStringValue_(name)
                self.media.setToolTip_(name)
                count = backend.media_controller.keyframeCount
                self.keyframes.setStringValue_(f'{count} ключевых кадров' if count else 'Ключевые кадры не загружены')
            finally:
                self.syncing = False

        def place(self, rect, shown):
            if not shown or rect.isEmpty():
                self.effect.setHidden_(True)
                return
            y = rect.y() if self.qt_view.isFlipped() else self.qt_view.bounds().size.height - rect.bottom()
            frame = self.qt_view.convertRect_toView_(AK.NSMakeRect(rect.x(), y, rect.width(), rect.height()), self.parent_view)
            self.effect.setFrame_(frame)
            self.effect.setHidden_(False)

        def close(self, *_args):
            if self.effect is None:
                return
            self.backend.changed.disconnect(self.sync)
            self.backend.media_controller.changed.disconnect(self.sync)
            self.backend.appearance.changed.disconnect(self.sync_appearance)
            self.effect.removeFromSuperview()
            self.outline.setDelegate_(None)
            self.outline.setDataSource_(None)
            self.character.setTarget_(None)
            self.open_button.setTarget_(None)
            self.delegate.host = None
            self.effect = None


@QmlElement
class NativeGlassSidebar(QQuickItem):
    activeChanged = Signal()
    integrationChanged = Signal()
    obscuredChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._integration = self._host = self._window = None
        self._obscured = False
        self._state = None
        self.windowChanged.connect(self._attach)
        for signal in (self.visibleChanged, self.obscuredChanged, self.xChanged, self.yChanged,
                       self.widthChanged, self.heightChanged):
            signal.connect(self._request_update)

    @Property(bool, notify=activeChanged)
    def active(self):
        return self._host is not None

    @Property(QObject, notify=integrationChanged)
    def integration(self):
        return self._integration

    @integration.setter
    def integration(self, value):
        if value != self._integration:
            self._integration = value
            self.integrationChanged.emit()
            self._attach(self.window())

    @Property(bool, notify=obscuredChanged)
    def obscured(self):
        return self._obscured

    @obscured.setter
    def obscured(self, value):
        if self._obscured != value:
            self._obscured = value
            self._state = None
            self.obscuredChanged.emit()
            # Native subviews must never cover QML modal overlays.
            if value and self._host:
                self._host.effect.setHidden_(True)

    def _request_update(self):
        if self._window:
            self._window.update()

    def _attach(self, window):
        if self._window and self._host:
            self._window.afterAnimating.disconnect(self._sync)
        if self._host:
            self.destroyed.disconnect(self._host.close)
            self._host.close()
        self._window, self._host, self._state = window, None, None
        if (window and self._integration and sys.platform == 'darwin'
                and QGuiApplication.platformName() == 'cocoa'
                and self._integration.liquidGlassAvailable):
            try:
                self._host = _SidebarHost(window, self._integration.backend)
                self.destroyed.connect(self._host.close)
                window.afterAnimating.connect(self._sync)
                window.update()
            except Exception:
                log.exception('Could not attach glass navigation; using QML sidebar')
        self.activeChanged.emit()

    def _sync(self):
        rect = tooltip_rect(self, self._window)
        shown = self.isVisible() and not self._obscured and self._window.isVisible()
        state = (rect.x(), rect.y(), rect.width(), rect.height(), shown)
        if state != self._state:
            self._state = state
            self._host.place(rect, shown)

    def detach(self):
        self._attach(None)
