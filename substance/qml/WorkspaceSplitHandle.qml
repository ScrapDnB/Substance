import QtQuick
import QtQuick.Controls

Rectangle {
    id: handle
    required property var colors
    property bool horizontal: false
    implicitWidth: 5
    implicitHeight: 5
    color: SplitHandle.pressed ? Qt.alpha(colors.accent, 0.25) : SplitHandle.hovered ? Qt.alpha(colors.accent, 0.12) : colors.workspace
    Rectangle {
        anchors.centerIn: parent
        width: handle.horizontal ? 1 : Math.min(40, parent.width)
        height: handle.horizontal ? Math.min(40, parent.height) : 1
        color: handle.SplitHandle.hovered || handle.SplitHandle.pressed ? handle.colors.accent : handle.colors.separator
    }
}
