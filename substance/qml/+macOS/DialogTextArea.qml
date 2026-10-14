import QtQuick
import QtQuick.Controls.Basic as Basic

Basic.TextArea {
    id: control
    selectByMouse: true
    padding: 10
    color: palette.text
    background: Rectangle {
        radius: 8
        color: control.palette.base
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.palette.highlight : Qt.alpha(control.palette.windowText, 0.12)
    }
}
