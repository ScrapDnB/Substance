import QtQuick
import QtQuick.Controls

Slider {
    id: control
    implicitHeight: 28
    readonly property real knobScale: Qt.platform.os === "osx" ? 0.65 : 0.75

    // Keep a 28-point-high interactive Slider while reducing the native knob.
    // Keyboard, accessibility, dragging and platform focus remain in Slider.
    function sizeKnob() {
        if (handle) handle.scale = knobScale
    }
    onHandleChanged: sizeKnob()
    Component.onCompleted: sizeKnob()
}
