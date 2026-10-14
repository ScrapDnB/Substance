import QtQuick
import QtQuick.Controls

ItemDelegate {
    id: control
    background: Rectangle {
        radius: 6
        color: control.highlighted ? control.palette.highlight
             : control.down ? Qt.alpha(control.palette.windowText, 0.12)
             : control.hovered ? Qt.alpha(control.palette.windowText, 0.06) : "transparent"
    }
}
