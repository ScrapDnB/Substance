import QtQuick
import QtQuick.Controls
import Substance 1.0

ToolButton {
    id: control
    readonly property real uiScale: backend.appearance.general.uiScale / 100
    property string symbol: ""
    property string hint: ""
    readonly property bool iconOnly: true
    property int count: 0
    required property color badgeColor
    required property color badgeTextColor
    implicitWidth: Math.round(32 * uiScale)
    implicitHeight: Math.round(28 * uiScale)
    padding: Math.round(4 * uiScale)
    icon.source: "../resources/icons/" + symbol + ".svg"
    icon.width: Math.round(18 * uiScale)
    icon.height: Math.round(18 * uiScale)
    icon.color: palette.buttonText
    display: AbstractButton.IconOnly
    checkable: true
    Accessible.name: hint
    NativeToolTip { text: control.hint }
    background: Rectangle {
        radius: Math.round(5 * control.uiScale)
        color: control.checked || control.down ? control.palette.highlight : control.palette.buttonText
        opacity: control.checked || control.down ? 0.2 : control.hovered ? 0.1 : 0
    }
    // Keep the caret and selection in the editor when showing details.
    focusPolicy: Qt.NoFocus

    Rectangle {
        objectName: "statusCountBadge"
        visible: control.count > 0
        anchors.top: parent.top
        anchors.right: parent.right
        implicitWidth: Math.max(height, counter.implicitWidth + Math.round(6 * control.uiScale))
        implicitHeight: Math.round(14 * control.uiScale)
        radius: height / 2
        color: control.badgeColor
        Label {
            id: counter
            objectName: "statusCountText"
            anchors.centerIn: parent
            text: control.count > 0 ? control.count : ""
            color: control.badgeTextColor
            font.pixelSize: Math.round(10 * control.uiScale)
            font.weight: Font.DemiBold
        }
    }
}
