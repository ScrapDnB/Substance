import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Basic as Basic

Basic.TabBar {
    id: bar
    property var labels: []
    property int selectedIndex: 0
    property bool ready: false
    signal activated(int index)
    implicitWidth: labels.length * 84
    implicitHeight: Qt.platform.os === "osx" ? 28 : 32
    padding: 2
    spacing: 0
    currentIndex: selectedIndex
    Component.onCompleted: ready = true
    onCurrentIndexChanged: {
        if (ready && currentIndex !== selectedIndex) {
            activated(currentIndex)
            // The document can reject a mode change with invalid pending time.
            setCurrentIndex(selectedIndex)
        }
    }
    background: Rectangle {
        radius: 6
        color: Qt.darker(bar.palette.window, 1.08)
        border.color: Qt.alpha(bar.palette.windowText, 0.16)
        Rectangle {
            x: bar.leftPadding + bar.currentIndex * bar.availableWidth / Math.max(1, bar.count)
            y: bar.topPadding
            width: bar.availableWidth / Math.max(1, bar.count)
            height: bar.availableHeight
            radius: 4
            color: bar.palette.button
            border.color: Qt.alpha(bar.palette.windowText, 0.10)
        }
    }
    Repeater {
        model: bar.labels
        Basic.TabButton {
            required property string modelData
            text: modelData
            focusPolicy: Qt.StrongFocus
            width: bar.availableWidth / Math.max(1, bar.labels.length)
            implicitHeight: bar.availableHeight
            height: implicitHeight
            padding: 0
            background: Rectangle {
                radius: 4
                color: "transparent"
                border.width: parent.visualFocus ? 2 : 0
                border.color: bar.palette.highlight
            }
            contentItem: Label {
                text: parent.text
                font: bar.font
                color: bar.palette.windowText
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
    }
}
