import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    id: row
    required property string title
    property string group: "general"
    required property string setting
    required property var labels
    required property var values
    property int fieldWidth: 210
    spacing: 16
    Label { text: row.title; Layout.fillWidth: true; wrapMode: Text.Wrap }
    ComboBox {
        objectName: "setting_" + row.group + "_" + row.setting
        Layout.preferredWidth: row.fieldWidth
        model: row.labels
        currentIndex: Math.max(0, row.values.indexOf(backend.appearance[row.group][row.setting]))
        onActivated: backend.appearance.setValue(row.group, row.setting, row.values[currentIndex])
        Accessible.name: row.title
    }
}
