import QtQuick
import QtQuick.Controls

// Transparent event overlay. The Waveform beneath remains the shared audio view.
Item {
    id: tracks
    objectName: "subtitleTracks"
    required property var colors
    required property var wave
    required property bool snap
    readonly property var tools: backend.editorTools
    readonly property real viewStart: wave.viewStart
    readonly property real span: wave.span
    readonly property real timeWidth: Math.max(1, width)
    clip: true
    function xAt(ms) { return (ms - viewStart) * timeWidth / span }
    function snapped(value) { return snap ? tools.snapTime(value, Math.round(span * 8 / timeWidth)) : value }
    Column {
        id: rows
        anchors.fill: parent
        Repeater {
            model: tracks.tools.lanes
            delegate: Item {
                id: lane
                objectName: "trackLane_" + index
                required property var modelData
                required property int index
                width: rows.width
                height: tracks.height / Math.max(1, tracks.tools.lanes.length)
                Rectangle {
                    visible: lane.index > 0
                    width: parent.width; height: 1
                    color: Qt.alpha(tracks.colors.muted, 0.15)
                }
                Repeater {
                    model: lane.modelData.items.filter(c => c.end >= tracks.viewStart && c.start <= tracks.viewStart + tracks.span)
                    delegate: Rectangle {
                        id: block
                        objectName: "trackCue_" + modelData.index
                        required property var modelData
                        property bool selected: tracks.tools.selectionIndices.indexOf(modelData.index) >= 0
                        z: selected ? 2 : 1
                        x: tracks.xAt(modelData.start) + (dragging.pressed && dragging.edge !== "end" ? dragging.deltaX : 0)
                        y: Math.min(3, lane.height * 0.1)
                        width: Math.max(8, (modelData.end - modelData.start) * tracks.timeWidth / tracks.span + (dragging.pressed && dragging.edge === "end" ? dragging.deltaX : dragging.pressed && dragging.edge === "start" ? -dragging.deltaX : 0))
                        height: Math.max(0, lane.height - y * 2)
                        radius: 4
                        color: Qt.alpha(block.selected ? tracks.colors.selection : tracks.colors.accent, block.selected ? 0.28 : 0.13)
                        border.color: Qt.alpha(tracks.colors.accent, block.selected ? 0.8 : 0.4)
                        Accessible.name: "Реплика " + (modelData.index + 1) + ": " + modelData.text
                        Label {
                            // Protect only the caption from bright waveform peaks.
                            // Keep it inside the visible part of a scrolled cue.
                            x: Math.max(7, 7 - block.x)
                            y: (block.height - height) / 2
                            width: Math.max(0, Math.min(implicitWidth, block.width - x - 7, tracks.width - block.x - x - 7))
                            height: Math.max(0, Math.min(implicitHeight, block.height - 4))
                            visible: width >= 16 && height >= 12
                            clip: true
                            leftPadding: 5
                            rightPadding: 5
                            topPadding: 2
                            bottomPadding: 2
                            text: block.modelData.text
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: tracks.colors.text
                            font.bold: block.selected
                            verticalAlignment: Text.AlignVCenter
                            background: Rectangle {
                                radius: 3
                                color: Qt.alpha(tracks.colors.surface, 0.94)
                            }
                        }
                        MouseArea {
                            id: dragging
                            objectName: "trackDrag_" + block.modelData.index
                            anchors.fill: parent
                            hoverEnabled: true
                            preventStealing: true
                            property string edge: ""
                            property real anchorX: 0
                            property real deltaX: 0
                            property var movingIndices: []
                            property int initialStart: 0
                            property int initialEnd: 0
                            cursorShape: mouseX < 7 || mouseX > width - 7 ? Qt.SizeHorCursor : Qt.OpenHandCursor
                            onPressed: mouse => {
                                edge = mouse.x < 7 ? "start" : mouse.x > width - 7 ? "end" : "move"
                                anchorX = mapToItem(tracks, mouse.x, mouse.y).x
                                initialStart = block.modelData.start
                                initialEnd = block.modelData.end
                                deltaX = 0
                                if (!block.selected || (mouse.modifiers & (Qt.ControlModifier | Qt.MetaModifier | Qt.ShiftModifier))) {
                                    let view = wave.viewStart
                                    let modifiers = mouse.modifiers
                                    if (modifiers & Qt.MetaModifier) modifiers |= Qt.ControlModifier
                                    backend.select(block.modelData.index, modifiers)
                                    wave.scrollTime(Math.round(view - wave.viewStart))
                                }
                                movingIndices = tracks.tools.selectionIndices.slice()
                                tracks.tools.beginTrackEdit()
                            }
                            onPositionChanged: mouse => {
                                if (pressed) deltaX = mapToItem(tracks, mouse.x, mouse.y).x - anchorX
                            }
                            onCanceled: deltaX = 0
                            onReleased: mouse => {
                                let delta = Math.round(deltaX * tracks.span / tracks.timeWidth)
                                let index = block.modelData.index
                                if (Math.abs(deltaX) > 2) {
                                    if (edge === "move") {
                                        delta = tracks.snapped(Math.max(0, initialStart + delta)) - initialStart
                                        tracks.tools.moveCues(movingIndices, delta)
                                    } else {
                                        let start = edge === "start" ? Math.min(initialEnd - 10, tracks.snapped(Math.max(0, initialStart + delta))) : initialStart
                                        let end = edge === "end" ? Math.max(initialStart + 10, tracks.snapped(initialEnd + delta)) : initialEnd
                                        tracks.tools.resizeCue(index, start, end)
                                    }
                                } else backend.media.seek(initialStart)
                                deltaX = 0
                            }
                            onDoubleClicked: backend.playCurrent(false)
                        }
                    }
                }
            }
        }
    }
    WheelHandler {
        acceptedModifiers: Qt.ControlModifier
        onWheel: event => { wave.zoom(event.angleDelta.y > 0 ? 0.8 : 1.25); event.accepted = true }
    }
    WheelHandler {
        acceptedModifiers: Qt.ShiftModifier
        onWheel: event => { wave.scrollTime(Math.round(-event.angleDelta.y / 120 * tracks.span / 8)); event.accepted = true }
    }
}
