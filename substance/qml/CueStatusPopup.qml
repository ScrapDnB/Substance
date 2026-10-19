import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: bubble
    required property Item anchorItem
    required property var colors
    property string title: ""
    readonly property real uiScale: backend.appearance.general.uiScale / 100
    readonly property real pointerSize: Math.round(8 * uiScale)
    property bool opensLeft: true
    property real anchorCenterY: 0
    default property alias details: detailsColumn.data

    readonly property Item overlay: Overlay.overlay
    parent: anchorItem
    popupType: Popup.Item
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    width: Math.min(Math.round(360 * uiScale), overlay ? overlay.width - 24 : 360)
    implicitHeight: detailsColumn.implicitHeight + topPadding + bottomPadding
    height: Math.min(implicitHeight, overlay ? overlay.height - 24 : implicitHeight)
    padding: Math.round(14 * uiScale)
    leftPadding: padding + (opensLeft ? 0 : pointerSize)
    rightPadding: padding + (opensLeft ? pointerSize : 0)

    function reposition() {
        if (!overlay || !anchorItem) return
        let point = anchorItem.mapToItem(overlay, 0, 0)
        opensLeft = point.x - width >= 12
        let preferredX = opensLeft ? point.x - width : point.x + anchorItem.width
        x = Math.max(12, Math.min(preferredX, overlay.width - width - 12)) - point.x
        anchorCenterY = anchorItem.height / 2
        y = Math.max(12, Math.min(point.y + anchorCenterY - 30 * uiScale, overlay.height - height - 12)) - point.y
    }
    onAboutToShow: reposition()
    onHeightChanged: if (visible) reposition()
    Connections {
        target: bubble.overlay
        function onWidthChanged() { if (bubble.visible) bubble.reposition() }
        function onHeightChanged() { if (bubble.visible) bubble.reposition() }
    }
    background: Item {
        Rectangle {
            x: bubble.opensLeft ? 0 : bubble.pointerSize
            width: parent.width - bubble.pointerSize
            height: parent.height
            radius: Math.round(10 * bubble.uiScale)
            color: bubble.colors.panel
            border.color: bubble.colors.separator
        }
        Canvas {
            id: pointer
            x: bubble.opensLeft ? parent.width - width : 0
            y: Math.max(12, Math.min(bubble.anchorCenterY - bubble.y - height / 2, parent.height - height - 12))
            width: bubble.pointerSize + 1
            height: bubble.pointerSize * 2
            onPaint: {
                let ctx = getContext("2d")
                ctx.reset()
                let base = bubble.opensLeft ? 0 : width
                let tip = bubble.opensLeft ? width : 0
                ctx.beginPath()
                ctx.moveTo(base, 0)
                ctx.lineTo(tip, height / 2)
                ctx.lineTo(base, height)
                ctx.closePath()
                ctx.fillStyle = bubble.colors.panel
                ctx.fill()
                ctx.beginPath()
                ctx.moveTo(base, 0)
                ctx.lineTo(tip, height / 2)
                ctx.lineTo(base, height)
                ctx.strokeStyle = bubble.colors.separator
                ctx.stroke()
            }
            Connections {
                target: bubble
                function onOpensLeftChanged() { pointer.requestPaint() }
                function onColorsChanged() { pointer.requestPaint() }
            }
        }
    }
    contentItem: ScrollView {
        id: scroll
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            id: detailsColumn
            width: scroll.availableWidth
            spacing: Math.round(10 * bubble.uiScale)
            Label {
                text: bubble.title
                Layout.fillWidth: true
                color: bubble.colors.text
                font.pixelSize: Math.round(13 * bubble.uiScale)
                font.weight: Font.DemiBold
                wrapMode: Text.Wrap
            }
        }
    }
}
