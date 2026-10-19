import QtQuick
import QtQuick.Controls

// Auxiliary dialogs use a real system window. Workflow sections can host
// the same body and action bar directly in the document workspace.
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
    property Item embeddedHost: null
    property bool embeddedActive: false
    readonly property bool presented: visible || embeddedActive
    signal opened()
    signal closed()
    signal accepted()
    signal rejected()

    visible: false
    flags: Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
    modality: modal ? Qt.ApplicationModal : Qt.NonModal
    font.pixelSize: 13
    width: embeddedHost ? embeddedHost.width : Math.min(preferredWidth, Screen.desktopAvailableWidth - 48)
    height: embeddedHost ? embeddedHost.height : Math.min(preferredHeight, Screen.desktopAvailableHeight - 80)
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
    palette.highlightedText: colors.accentText || colors.selectedText

    function open() {
        if (!available) return
        if (embeddedHost && !embeddedHost.visible) detachEmbedding()
        if (embeddedHost) {
            if (!embeddedActive) { embeddedActive = true; opened() }
            return
        }
        if (visible) { raise(); requestActivate(); return }
        let parentWindow = transientParent as ApplicationWindow
        returnFocus = parentWindow ? parentWindow.activeFocusItem : null
        // Let the window manager position dialogs, including on multiple screens.
        show()
        raise()
        requestActivate()
    }
    function detachEmbedding() { embeddedActive = false; embeddedHost = null }
    function dismiss() {
        if (embeddedActive) { embeddedActive = false; closed() }
        else close()
    }
    function accept() { accepted(); dismiss() }
    function reject() { rejected(); dismiss() }
    onAvailableChanged: { if (!available && presented) dismiss() }
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

    // The same controls and controller state serve a native window and a page.
    // Moving the body and footer also keeps custom action bars and previews.
    property Item embeddedSurface: Item {
        parent: dialog.embeddedHost
        width: dialog.embeddedHost ? dialog.embeddedHost.width : 0
        height: dialog.embeddedHost ? dialog.embeddedHost.height : 0
        visible: dialog.embeddedActive
    }
    Binding { target: dialog.footer; property: "parent"; value: dialog.embeddedSurface; when: dialog.embeddedHost !== null }
    Binding { target: dialog.footer; property: "x"; value: 0; when: dialog.embeddedHost !== null }
    Binding { target: dialog.footer; property: "y"; value: dialog.embeddedSurface.height - (dialog.footer ? dialog.footer.height : 0); when: dialog.embeddedHost !== null }
    Binding { target: dialog.footer; property: "width"; value: dialog.embeddedSurface.width; when: dialog.embeddedHost !== null }

    property Item dialogBody: Item {
        id: body
        parent: dialog.embeddedHost ? dialog.embeddedSurface : dialog.contentItem
        anchors.fill: parent
        anchors.margins: 20
        anchors.bottomMargin: 20 + (dialog.embeddedHost && dialog.footer ? dialog.footer.height : 0)
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
