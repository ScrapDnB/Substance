import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Basic as Basic

Basic.GroupBox {
    id: control
    leftPadding: 16
    rightPadding: 16
    topPadding: implicitLabelHeight + 20
    bottomPadding: 16
    label: Label {
        x: 4
        text: control.title
        font.bold: true
        color: control.palette.windowText
    }
    background: Rectangle {
        y: control.implicitLabelHeight + 8
        height: control.height - y
        radius: 10
        color: Qt.tint(control.palette.window, Qt.alpha(control.palette.base, 0.5))
        border.color: Qt.alpha(control.palette.windowText, 0.08)
    }
}
