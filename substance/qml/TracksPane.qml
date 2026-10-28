import QtQuick
import QtQuick.Controls
import Substance 1.0

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
    property var jointEdit: null
    property int jointTime: 0
    clip: true
    onVisibleChanged: if (!visible) jointEdit = null
    Connections {
        target: tracks.tools
        function onLanesChanged() { tracks.jointEdit = null }
    }
    function xAt(ms) { return (ms - viewStart) * timeWidth / span }
    function snapped(value) { return snap ? tools.snapTime(value, Math.round(span * 8 / timeWidth)) : value }
    function snapJoint(joint, value) {
        let time = snap ? tools.snapJointTime(joint.left, joint.right, value, Math.round(span * 8 / timeWidth)) : value
        return Math.max(joint.minimum, Math.min(joint.maximum, time))
    }
    Item {
        id: rows
        anchors.fill: parent
        Repeater {
            model: tracks.tools.lanes
            delegate: Item {
                id: lane
                objectName: "trackLane_" + index
                required property var modelData
                required property int index
                anchors.fill: parent
                Repeater {
                    model: lane.modelData.items.filter(c => c.end >= tracks.viewStart && c.start <= tracks.viewStart + tracks.span)
                    delegate: Rectangle {
                        id: block
                        objectName: "trackCue_" + modelData.index
                        required property var modelData
                        readonly property real laneHeight: tracks.height / Math.max(1, modelData.laneCount)
                        readonly property real inset: Math.min(3, laneHeight * 0.1)
                        readonly property real displayStart: tracks.jointEdit && tracks.jointEdit.right === modelData.index ? tracks.jointTime : modelData.start
                        readonly property real displayEnd: tracks.jointEdit && tracks.jointEdit.left === modelData.index ? tracks.jointTime : modelData.end
                        property bool selected: tracks.tools.selectionIndices.indexOf(modelData.index) >= 0
                        z: selected ? 2 : 1
                        x: tracks.xAt(displayStart) + (dragging.pressed && !dragging.joint && dragging.edge !== "end" ? dragging.deltaX : 0)
                        y: lane.index * laneHeight + inset
                        width: Math.max(8, (displayEnd - displayStart) * tracks.timeWidth / tracks.span + (dragging.pressed && !dragging.joint && dragging.edge === "end" ? dragging.deltaX : dragging.pressed && !dragging.joint && dragging.edge === "start" ? -dragging.deltaX : 0))
                        height: Math.max(0, laneHeight - inset * 2)
                        radius: 4
                        color: Qt.alpha(block.selected ? tracks.colors.selection : tracks.colors.accent, block.selected ? 0.28 : 0.13)
                        border.color: Qt.alpha(tracks.colors.accent, block.selected ? 0.8 : 0.4)
                        Accessible.name: "Реплика " + (modelData.index + 1) + ": " + modelData.text
                        Repeater {
                            model: [block.modelData.startJoint, block.modelData.endJoint]
                            delegate: Rectangle {
                                required property var modelData
                                required property int index
                                visible: modelData !== null
                                x: index === 0 ? 0 : block.width - width
                                y: Math.min(4, block.height / 4)
                                width: 2
                                height: Math.max(0, block.height - y * 2)
                                color: tracks.colors.accent
                                opacity: dragging.containsMouse || dragging.pressed ? 0.9 : 0.45
                            }
                        }
                        Repeater {
                            model: 2
                            delegate: Rectangle {
                                required property int index
                                objectName: "trackHandle_" + block.modelData.index + "_" + index
                                x: index === 0 ? 0 : block.width - width
                                y: 0
                                width: Math.min(8, block.width / 2)
                                height: Math.min(16, block.height)
                                color: tracks.colors.accent
                            }
                        }
                        Label {
                            id: caption
                            objectName: "trackCaption_" + block.modelData.index
                            // Protect only the caption from bright waveform peaks.
                            // Keep it inside the visible part of a scrolled cue.
                            x: Math.max(7, 7 - block.x)
                            y: (block.height - height) / 2
                            width: Math.max(0, Math.min(implicitWidth, block.width - x - 7, tracks.width - block.x - x - 7))
                            // Multiline elision depends on the available height.
                            // Keep that input independent of the measured text.
                            height: Math.max(0, block.height - 4)
                            visible: width >= 16 && height >= captionMetrics.height + topPadding + bottomPadding
                            clip: true
                            leftPadding: 5
                            rightPadding: 5
                            topPadding: 2
                            bottomPadding: 2
                            text: block.modelData.text
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            maximumLineCount: Math.max(1, Math.floor((block.height - 8) / captionMetrics.height))
                            elide: Text.ElideRight
                            color: tracks.colors.text
                            font.bold: block.selected
                            verticalAlignment: Text.AlignVCenter
                            FontMetrics { id: captionMetrics; font: caption.font }
                            background: Rectangle {
                                y: (caption.height - height) / 2
                                height: Math.min(caption.height, caption.implicitHeight)
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
                            property var joint: null
                            cursorShape: mouseX < 8 || mouseX > width - 8 ? Qt.SizeHorCursor : Qt.OpenHandCursor
                            onPressed: mouse => {
                                edge = mouse.x < 8 ? "start" : mouse.x > width - 8 ? "end" : "move"
                                anchorX = mapToItem(tracks, mouse.x, mouse.y).x
                                initialStart = block.modelData.start
                                initialEnd = block.modelData.end
                                deltaX = 0
                                joint = mouse.modifiers & Qt.AltModifier ? (edge === "start" ? block.modelData.startJoint : edge === "end" ? block.modelData.endJoint : null) : null
                                if (!block.selected || (mouse.modifiers & (Qt.ControlModifier | Qt.MetaModifier | Qt.ShiftModifier))) {
                                    let modifiers = mouse.modifiers
                                    if (modifiers & Qt.MetaModifier) modifiers |= Qt.ControlModifier
                                    backend.select(block.modelData.index, modifiers)
                                }
                                movingIndices = tracks.tools.selectionIndices.slice()
                                tracks.tools.beginTrackEdit()
                                if (joint) {
                                    tracks.jointTime = joint.time
                                    tracks.jointEdit = joint
                                }
                            }
                            onPositionChanged: mouse => {
                                if (pressed) {
                                    deltaX = mapToItem(tracks, mouse.x, mouse.y).x - anchorX
                                    if (joint) tracks.jointTime = tracks.snapJoint(joint, joint.time + Math.round(deltaX * tracks.span / tracks.timeWidth))
                                }
                            }
                            onCanceled: {
                                if (joint) tracks.jointEdit = null
                                joint = null
                                deltaX = 0
                            }
                            onReleased: mouse => {
                                let delta = Math.round(deltaX * tracks.span / tracks.timeWidth)
                                let index = block.modelData.index
                                let shared = joint
                                let time = tracks.jointTime
                                tracks.jointEdit = null
                                if (Math.abs(deltaX) > 2) {
                                    if (shared) {
                                        tracks.tools.moveJoint(shared.left, shared.right, time)
                                    } else if (edge === "move") {
                                        delta = tracks.snapped(Math.max(0, initialStart + delta)) - initialStart
                                        tracks.tools.moveCues(movingIndices, delta)
                                    } else {
                                        let start = edge === "start" ? Math.min(initialEnd - 10, tracks.snapped(Math.max(0, initialStart + delta))) : initialStart
                                        let end = edge === "end" ? Math.max(initialStart + 10, tracks.snapped(initialEnd + delta)) : initialEnd
                                        tracks.tools.resizeCue(index, start, end)
                                    }
                                } else backend.media.seek(initialStart)
                                deltaX = 0
                                joint = null
                            }
                            onDoubleClicked: backend.playCurrent(false)
                            NativeToolTip {
                                text: ((dragging.mouseX < 8 && block.modelData.startJoint) || (dragging.mouseX > dragging.width - 8 && block.modelData.endJoint))
                                      ? "Перетащите границу фразы. Alt/⌥ — двигать стык двух фраз."
                                      : dragging.mouseX < 8 || dragging.mouseX > dragging.width - 8 ? "Перетащите границу фразы" : "Перетащите выбранные фразы"
                            }
                        }
                    }
                }
            }
        }
    }
}
