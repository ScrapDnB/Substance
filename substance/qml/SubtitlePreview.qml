import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One real output cue per card, including newly split or merged cues.
ColumnLayout {
    id: preview
    required property var colors
    property var cues: []
    property bool proposed: false
    spacing: 8
    Repeater {
        model: preview.cues
        delegate: Rectangle {
            id: cue
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: contents.implicitHeight + 24
            radius: 9
            color: preview.proposed ? Qt.alpha(preview.colors.accent, .07) : preview.colors.panel
            border.color: preview.proposed ? Qt.alpha(preview.colors.accent, .3) : preview.colors.separator
            ColumnLayout {
                id: contents
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10
                Label {
                    Layout.fillWidth: true
                    text: cue.modelData.startText + " → " + cue.modelData.endText
                    color: preview.colors.muted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                Label {
                    Layout.fillWidth: true
                    text: cue.modelData.text
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    font.pixelSize: 18
                    lineHeight: 1.2
                }
                Label {
                    Layout.fillWidth: true
                    visible: cue.modelData.duration !== undefined
                    text: visible ? cue.modelData.duration + " с на экране · " + cue.modelData.cps + " знаков/с" : ""
                    color: preview.colors.muted
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }
}
