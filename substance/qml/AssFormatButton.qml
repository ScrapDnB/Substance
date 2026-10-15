import QtQuick
import QtQuick.Controls

ControlButton {
    required property var editor
    required property string tag
    required property string label
    property string command: ""
    objectName: "assFormat_" + tag
    text: tag.toUpperCase()
    implicitWidth: 44
    focusPolicy: Qt.NoFocus
    checkable: true
    checked: editor.formatState[tag] || false
    enabled: backend.current.exists && !backend.busy
    font.bold: tag === "b"
    font.italic: tag === "i"
    font.underline: tag === "u"
    font.strikeout: tag === "s"
    hint: label + (command ? " · " + backend.shortcutLabel(command) : "") + " · для выделенного текста или ввода с курсора"
    onClicked: editor.formatAss(tag)
}
