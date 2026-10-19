import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SpinBox {
    id: control
    // Fluent places both arrows beside the text. Reserve room for the widest
    // endpoint as well as the current value, including locale separators.
    readonly property real minimumReadableWidth: Math.ceil(Math.max(
        fromMetrics.advanceWidth, toMetrics.advanceWidth, valueMetrics.advanceWidth)) + leftPadding + rightPadding + 4
    Layout.minimumWidth: Qt.platform.os === "windows" ? Math.max(implicitWidth, minimumReadableWidth) : -1
    TextMetrics { id: fromMetrics; font: control.font; text: control.textFromValue(control.from, control.locale) }
    TextMetrics { id: toMetrics; font: control.font; text: control.textFromValue(control.to, control.locale) }
    TextMetrics { id: valueMetrics; font: control.font; text: control.displayText }
}
