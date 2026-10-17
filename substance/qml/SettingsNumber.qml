import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    id: row
    required property string title
    property string description: ""
    property string group: "general"
    required property string setting
    property int from: 10
    property int to: 30
    property int step: 1
    property string unit: "пкс"
    readonly property int currentValue: backend.appearance[group][setting]
    spacing: 16
    ColumnLayout {
        Layout.fillWidth: true
        spacing: 3
        Label { text: row.title; Layout.fillWidth: true; wrapMode: Text.Wrap }
        Label { visible: text.length > 0; text: row.description; opacity: 0.6; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
    }
    Slider {
        Layout.preferredWidth: 110
        visible: row.width > 530
        from: row.from; to: row.to; stepSize: row.step
        value: row.currentValue
        onMoved: backend.appearance.setValue(row.group, row.setting, Math.round(value))
        Accessible.name: row.title
    }
    DialogSpinBox {
        objectName: "setting_" + row.group + "_" + row.setting
        Layout.preferredWidth: 88
        from: row.from; to: row.to; stepSize: row.step
        value: row.currentValue
        editable: true
        onValueModified: backend.appearance.setValue(row.group, row.setting, value)
        Accessible.name: row.title
    }
    Label { text: row.unit; opacity: 0.6; Layout.preferredWidth: 25; font.pixelSize: 11 }
}
