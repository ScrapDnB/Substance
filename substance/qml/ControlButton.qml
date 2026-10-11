import QtQuick
import QtQuick.Controls
import Substance 1.0

// Button uses the native macOS style; ToolButton falls back to Basic on macOS.
Button {
    id: control
    property string symbol: ""
    property string hint: ""
    readonly property bool iconOnly: symbol.length > 0 && text.length === 0

    // AppKit's rounded bezel has a minimum width. Below 44 logical pixels the
    // native style paints a wider bezel than the item, offsetting its center.
    implicitWidth: iconOnly ? (Qt.platform.os === "osx" ? 44 : 32) : Math.max(72, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: 32
    leftPadding: iconOnly && Qt.platform.os !== "osx" ? 6 : 12
    rightPadding: leftPadding
    // AppKit's bezel has asymmetric vertical margins (5 / 7 on this size).
    // Preserve those instead of centering against the outer hit rectangle.
    topPadding: background && background.layoutMargins ? background.layoutMargins.top : 6
    bottomPadding: background && background.layoutMargins ? background.layoutMargins.bottom : 6
    icon.source: symbol.length ? "../resources/icons/" + symbol + ".svg" : ""
    icon.width: 20
    icon.height: 20
    icon.color: palette.buttonText
    display: iconOnly ? AbstractButton.IconOnly : AbstractButton.TextBesideIcon
    Accessible.name: hint.length ? hint : text
    NativeToolTip { text: control.hint }
}
