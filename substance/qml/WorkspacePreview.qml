import QtQuick
import QtQuick.Controls

Rectangle {
    id: preview
    required property var colors
    property string mode: "timing"
    readonly property var config: backend.appearance[mode]
    readonly property bool timing: mode === "timing"
    readonly property real pad: 10
    readonly property real gap: 5
    readonly property real areaWidth: width - 2 * pad
    readonly property real areaHeight: height - 2 * pad
    readonly property real audioSize: config.audioVisible ? Math.min(48, config.audioHeight / 5) : 0
    readonly property real bodyHeight: areaHeight - (config.audioVisible ? audioSize + gap : 0)
    readonly property real videoWidth: config.videoVisible ? areaWidth * config.videoPercent / 100 : 0
    readonly property real contentWidth: areaWidth - (config.videoVisible ? videoWidth + gap : 0)
    readonly property real contentX: !timing && config.videoVisible && config.videoSide === "left" ? pad + videoWidth + gap : pad
    readonly property real editorRatio: timing ? 0.5 : Math.max(0.4, Math.min(0.72, config.editorHeight / 760))
    implicitHeight: 202
    color: colors.sidebar
    radius: 12
    border.color: colors.border
    clip: true
    Accessible.name: "Предпросмотр раскладки: " + (timing ? "тайминг" : "перевод")
    component Block: Rectangle {
        property string label
        property bool emphasized: false
        color: emphasized ? Qt.alpha(preview.colors.accent, 0.12) : preview.colors.surface
        radius: 6
        border.color: emphasized ? Qt.alpha(preview.colors.accent, 0.4) : Qt.alpha(preview.colors.border, 0.6)
        Label { anchors.centerIn: parent; text: parent.label; color: parent.emphasized ? preview.colors.accent : preview.colors.muted; font.pixelSize: 11 }
    }
    Block {
        label: "Видео"
        visible: preview.config.videoVisible
        x: preview.config.videoSide === "left" ? preview.pad : preview.width - preview.pad - width
        y: preview.pad
        width: preview.videoWidth
        height: preview.timing ? preview.bodyHeight * preview.config.topPercent / 100 : preview.bodyHeight * (preview.config.contextVisible ? 0.6 : 1)
    }
    Block {
        label: "Контекст"
        visible: !preview.timing && preview.config.videoVisible && preview.config.contextVisible
        x: preview.config.videoSide === "left" ? preview.pad : preview.width - preview.pad - width
        y: preview.pad + preview.bodyHeight * 0.6 + preview.gap
        width: preview.videoWidth
        height: preview.bodyHeight * 0.4 - preview.gap
    }
    Block {
        label: preview.timing ? "Редактор" : ""
        emphasized: true
        x: preview.timing ? (preview.config.videoSide === "left" && preview.config.videoVisible ? preview.pad + preview.videoWidth + preview.gap : preview.pad) : preview.contentX
        y: preview.timing || !preview.config.tableFirst ? preview.pad : preview.pad + preview.bodyHeight * (1 - preview.editorRatio) + preview.gap
        width: preview.contentWidth
        height: preview.timing ? preview.bodyHeight * preview.config.topPercent / 100 : preview.bodyHeight * preview.editorRatio - preview.gap
        Block {
            label: "Оригинал"
            visible: !preview.timing
            x: 4; y: 4
            width: preview.config.originalBelow ? parent.width - 8 : (parent.width - 12) / 2
            height: preview.config.originalBelow ? (parent.height - 12) / 2 : parent.height - 8
        }
        Block {
            label: "Перевод"
            emphasized: true
            visible: !preview.timing
            x: preview.config.originalBelow ? 4 : parent.width / 2 + 2
            y: preview.config.originalBelow ? parent.height / 2 + 2 : 4
            width: preview.config.originalBelow ? parent.width - 8 : (parent.width - 12) / 2
            height: preview.config.originalBelow ? (parent.height - 12) / 2 : parent.height - 8
        }
    }
    Block {
        label: preview.timing ? "Реплики" : "Оригинал · Перевод"
        x: preview.timing ? preview.pad : preview.contentX
        y: preview.timing ? preview.pad + preview.bodyHeight * preview.config.topPercent / 100 + preview.gap + (preview.config.audioVisible && preview.config.audioPosition === "middle" ? preview.audioSize + preview.gap : 0) : preview.pad + (preview.config.tableFirst ? 0 : preview.bodyHeight * preview.editorRatio + preview.gap)
        width: preview.timing ? preview.areaWidth : preview.contentWidth
        height: preview.timing ? preview.bodyHeight * (1 - preview.config.topPercent / 100) - preview.gap : preview.bodyHeight * (1 - preview.editorRatio) - preview.gap
    }
    Block {
        label: "∿  Аудио"
        visible: preview.config.audioVisible
        x: preview.pad
        y: preview.timing && preview.config.audioPosition === "middle" ? preview.pad + preview.bodyHeight * preview.config.topPercent / 100 + preview.gap : preview.height - preview.pad - height
        width: preview.areaWidth
        height: preview.audioSize
    }
}
