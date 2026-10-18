import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: header
    required property var colors
    required property string title
    property string detail: ""
    readonly property real uiScale: backend.appearance.general.uiScale / 100
    default property alias actions: actionRow.data
    readonly property alias actionsItem: actionRow
    leftPadding: Math.round(14 * uiScale)
    rightPadding: leftPadding
    topPadding: Math.round(6 * uiScale)
    bottomPadding: topPadding
    background: Rectangle {
        color: header.colors.panelHeader
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: header.colors.separator }
    }
    contentItem: RowLayout {
        spacing: Math.round(10 * header.uiScale)
        Label {
            text: header.title
            font.pixelSize: Math.round(13 * header.uiScale)
            font.weight: Font.DemiBold
            color: header.colors.text
            elide: Text.ElideRight
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Accessible.role: Accessible.Heading
        }
        Label {
            visible: text.length > 0 && header.width > 500 * header.uiScale
            text: header.detail
            color: header.colors.label
            font.pixelSize: Math.round(12 * header.uiScale)
            elide: Text.ElideRight
            Layout.maximumWidth: header.width * 0.3
        }
        RowLayout { id: actionRow; spacing: Math.round(6 * header.uiScale) }
    }
}
