import QtQuick
import QtQuick.Controls.Basic as Basic

// macOS form fields use a rounded bezel and the system accent focus ring.
// The editable control remains Qt's TextField, including IME and accessibility.
Basic.TextField {
    id: control
    selectByMouse: true
    implicitHeight: Math.max(30, contentHeight + topPadding + bottomPadding)
    leftPadding: 10
    rightPadding: 10
    topPadding: 5
    bottomPadding: 5
    color: palette.text
    background: Rectangle {
        radius: 7
        color: control.palette.base
        border.color: Qt.alpha(control.palette.windowText, control.enabled ? 0.18 : 0.08)
        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: parent.radius + 3
            color: "transparent"
            border.width: control.activeFocus ? 3 : 0
            border.color: Qt.alpha(control.palette.highlight, 0.45)
        }
    }
}
