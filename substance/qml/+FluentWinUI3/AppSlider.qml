import QtQuick
import QtQuick.Controls

Slider {
    id: control
    readonly property bool highContrast: Application.styleHints.accessibility.contrastPreference === Qt.HighContrast
    // Keep Fluent's native handle and input, with a groove without automatic
    // tick rows. A declarative override avoids instantiating the style's ticks.
    background: Item {
        objectName: "sliderTrackWithoutTicks"
        implicitWidth: control.horizontal ? 200 : 4
        implicitHeight: control.horizontal ? 4 : 200
        Rectangle {
            id: groove
            readonly property real handleWidth: control.handle ? control.handle.width : 20
            readonly property real handleHeight: control.handle ? control.handle.height : 20
            x: control.leftPadding + (control.horizontal ? handleWidth / 2 : (control.availableWidth - width) / 2)
            y: control.topPadding + (control.horizontal ? (control.availableHeight - height) / 2 : handleHeight / 2)
            width: control.horizontal ? Math.max(0, control.availableWidth - handleWidth) : 4
            height: control.horizontal ? 4 : Math.max(0, control.availableHeight - handleHeight)
            radius: 2
            color: control.highContrast ? control.palette.buttonText : control.palette.mid
            opacity: control.enabled ? 1 : 0.4
            Rectangle {
                width: control.horizontal ? parent.width * control.position : parent.width
                height: control.horizontal ? parent.height : parent.height * control.position
                x: control.horizontal && control.mirrored ? parent.width - width : 0
                y: control.horizontal ? 0 : parent.height - height
                radius: 2
                color: control.highContrast ? control.palette.highlight : control.palette.accent
            }
        }
    }
}
