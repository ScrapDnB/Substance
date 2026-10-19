import QtQuick
import QtQuick.Controls
import Substance 1.0

Label {
    id: header
    required property var colors
    required property Item resizeSurface
    required property string columnKey
    required property real minimumColumnWidth
    signal widthRequested(real value)
    signal resetRequested()
    height: parent.height
    verticalAlignment: Text.AlignVCenter
    font.pixelSize: Math.round(12 * resizeSurface.uiScale)
    font.weight: Font.Medium
    color: colors.label
    rightPadding: 8
    elide: Text.ElideRight
    Rectangle {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: 1
        height: parent.height - 10
        color: resizing.containsMouse || resizing.pressed ? header.colors.accent : header.colors.separator
    }
    MouseArea {
        id: resizing
        objectName: "resizeColumn_" + header.columnKey
        anchors.right: parent.right
        width: 8 * header.resizeSurface.uiScale
        height: parent.height
        cursorShape: Qt.SizeHorCursor
        hoverEnabled: true
        preventStealing: true
        property real startX: 0
        property real initialWidth: 0
        onPressed: mouse => {
            startX = mapToItem(header.resizeSurface, mouse.x, mouse.y).x
            initialWidth = header.width
        }
        onPositionChanged: mouse => {
            if (pressed) {
                let x = mapToItem(header.resizeSurface, mouse.x, mouse.y).x
                header.widthRequested(Math.max(header.minimumColumnWidth, initialWidth + x - startX))
            }
        }
        onDoubleClicked: header.resetRequested()
        NativeToolTip { text: "Потяните границу, чтобы изменить ширину. Двойной щелчок — автоматическая ширина." }
    }
}
