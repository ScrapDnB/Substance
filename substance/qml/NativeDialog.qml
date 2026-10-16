import QtQuick
import QtQuick.Controls

// A desktop dialog must be a real window. Popup.Window still uses Qt.Popup
// (without a system title bar); Popup.Item draws inside the editor's overlay.
ApplicationWindow {
    id: dialog
    default property alias dialogContent: body.data
    required property var colors
    property bool available: true
    property bool modal: true
    property int standardButtons: Dialog.NoButton
    property int preferredWidth: 480
    property int preferredHeight: Math.ceil(body.implicitHeight + 40 + (footer ? footer.height : 0))
    property var returnFocus: null
    signal opened()
    signal closed()
    signal accepted()
    signal rejected()

    visible: false
    flags: Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
    modality: modal ? Qt.ApplicationModal : Qt.NonModal
    font.pixelSize: 13
    width: Math.min(preferredWidth, Screen.desktopAvailableWidth - 48)
    height: Math.min(preferredHeight, Screen.desktopAvailableHeight - 80)
    minimumWidth: Math.min(preferredWidth, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(preferredHeight, Screen.desktopAvailableHeight - 80)
    color: colors.sidebar
    palette.window: colors.sidebar
    palette.windowText: colors.text
    palette.base: colors.surface
    palette.text: colors.text
    palette.button: colors.button
    palette.buttonText: colors.text
    palette.highlight: colors.accent
    palette.highlightedText: colors.selectedText

    function open() {
        if (!available) return
        if (visible) { raise(); requestActivate(); return }
        let parentWindow = transientParent as ApplicationWindow
        returnFocus = parentWindow ? parentWindow.activeFocusItem : null
        // Let the window manager position dialogs, including on multiple screens.
        show()
        raise()
        requestActivate()
    }
    function accept() { accepted(); close() }
    function reject() { rejected(); close() }
    onAvailableChanged: { if (!available && visible) close() }
    onVisibleChanged: {
        if (visible) opened()
        else {
            closed()
            if (transientParent && transientParent.visible) {
                transientParent.requestActivate()
                if (returnFocus) returnFocus.forceActiveFocus()
            }
            returnFocus = null
        }
    }

    property Item dialogBody: Item {
        id: body
        parent: dialog.contentItem
        anchors.fill: parent
        anchors.margins: 20
        focus: true
        Keys.onEscapePressed: event => { dialog.reject(); event.accepted = true }
        implicitHeight: {
            let result = 0
            for (let item of children)
                if (item.visible) result = Math.max(result, item.implicitHeight)
            return result
        }
    }
    footer: DialogButtonBox {
        objectName: "nativeDialogButtons"
        visible: count > 0
        standardButtons: dialog.standardButtons
        leftPadding: 20
        rightPadding: 20
        bottomPadding: 20
        implicitHeight: visible ? implicitContentHeight + topPadding + bottomPadding : 0
        function localizeButtons() {
            for (let spec of [[Dialog.Close, "Закрыть"], [Dialog.Cancel, "Отмена"], [Dialog.Ok, "OK"]]) {
                let button = standardButton(spec[0])
                if (button) button.text = spec[1]
            }
        }
        Component.onCompleted: localizeButtons()
        onCountChanged: Qt.callLater(localizeButtons)
        onAccepted: dialog.accept()
        onRejected: dialog.reject()
    }
    Shortcut { sequences: [StandardKey.Close]; context: Qt.ApplicationShortcut; enabled: dialog.visible && dialog.active; onActivated: dialog.reject() }
}
