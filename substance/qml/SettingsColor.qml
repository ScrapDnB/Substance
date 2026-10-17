import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

RowLayout {
    id: row
    required property string title
    property string group: "general"
    required property string setting
    required property color fallback
    readonly property string savedColor: backend.appearance[group][setting]
    Label { text: row.title; Layout.fillWidth: true; wrapMode: Text.Wrap }
    Button {
        objectName: "setting_" + row.group + "_" + row.setting
        Layout.preferredWidth: 150
        text: row.savedColor || "Автоматически"
        icon.source: ""
        leftPadding: 30
        Rectangle { x: 10; anchors.verticalCenter: parent.verticalCenter; width: 14; height: 14; radius: 4; color: row.savedColor || row.fallback; border.color: "#808080" }
        onClicked: { picker.selectedColor = row.savedColor || row.fallback; picker.open() }
        Accessible.name: row.title + ": " + text
    }
    ToolButton { text: "Сбросить"; enabled: row.savedColor.length > 0; onClicked: backend.appearance.setValue(row.group, row.setting, ""); Accessible.name: "Сбросить: " + row.title }
    ColorDialog {
        id: picker
        title: row.title
        onAccepted: backend.appearance.setValue(row.group, row.setting, selectedColor.toString())
    }
}
