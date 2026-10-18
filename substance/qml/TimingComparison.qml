import QtQuick
import QtQuick.Controls

// A shared, labelled time axis makes the size and direction of a change visible.
Item {
    id: chart
    required property var colors
    required property var preview
    readonly property real first: Math.min(preview.beforeStart || 0, preview.start || 0)
    readonly property real last: Math.max(preview.beforeEnd || 0, preview.end || 0)
    readonly property real span: Math.max(1000, last - first)
    function positionX(t) { return 66 + (t - first) / span * Math.max(1, width - 76) }
    Repeater {
        model: [false, true]
        Item {
            required property bool modelData
            width: chart.width
            y: modelData ? 34 : 0
            height: 28
            Label { text: modelData ? "После" : "Сейчас"; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 11; color: chart.colors.muted }
            Rectangle { x: 66; width: Math.max(1, parent.width - 76); height: 1; y: 14; color: chart.colors.separator }
            Rectangle {
                x: chart.positionX(modelData ? (chart.preview.start || 0) : (chart.preview.beforeStart || 0))
                width: Math.max(3, chart.positionX(modelData ? (chart.preview.end || 0) : (chart.preview.beforeEnd || 0)) - x)
                y: 5; height: 19; radius: 4
                color: chart.preview.error && modelData ? chart.colors.warning : modelData ? chart.colors.accent : Qt.alpha(chart.colors.text, .25)
            }
        }
    }
}
