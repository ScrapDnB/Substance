import QtQuick
import QtQuick.Controls

Pane {
    required property var colors
    padding: 14
    background: Rectangle {
        color: colors.surface
        border.color: colors.separator
        radius: 12
    }
}
