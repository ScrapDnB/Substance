import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One real output cue per card, including newly split or merged cues.
ColumnLayout {
    id: preview
    required property var colors
    property var cues: []
    property bool proposed: false
    property bool bilingual: false
    property bool playable: false
    signal playRequested(int index)
    spacing: 8
    Repeater {
        model: preview.cues
        delegate: Rectangle {
            id: cue
            required property var modelData
            required property int index
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
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        text: cue.modelData.startText + " → " + cue.modelData.endText
                        color: preview.colors.muted
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                    }
                    Button { visible: preview.playable; text: "▶"; Accessible.name: "Прослушать субтитр " + (cue.index + 1); onClicked: preview.playRequested(cue.index) }
                }
                Label {
                    visible: preview.bilingual && cue.modelData.translation !== undefined && cue.modelData.translation !== null
                    Layout.fillWidth: true
                    text: (cue.modelData.originalGenerated ? "Оригинал (распознано): " : "Оригинал: ") + (cue.modelData.original || "—")
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: preview.colors.muted
                    font.pixelSize: 14
                }
                Label {
                    Layout.fillWidth: true
                    text: (preview.bilingual && cue.modelData.translation !== undefined && cue.modelData.translation !== null ? "Перевод: " : "") + cue.modelData.text
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    font.pixelSize: 18
                    lineHeight: 1.2
                }
                Label {
                    Layout.fillWidth: true
                    visible: cue.modelData.duration !== undefined
                    text: visible ? cue.modelData.duration + " с на экране · " + cue.modelData.cps + " знаков/с" + (cue.modelData.warning ? " · " + cue.modelData.warning : "") : ""
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: cue.modelData.warning ? preview.colors.warning : preview.colors.muted
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }
}
