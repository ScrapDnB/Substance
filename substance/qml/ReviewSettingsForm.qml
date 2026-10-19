import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: form
    required property var values
    required property string namePrefix
    signal edited(string key, var value)
    spacing: 12
    RowLayout {
        Layout.fillWidth: true
        CheckBox {
            objectName: form.namePrefix + "ReadingSpeedCheck"
            text: "Скорость чтения, зн/с"
            Layout.fillWidth: true
            checked: form.values.readingSpeed
            onClicked: form.edited("readingSpeed", checked)
        }
        DialogSpinBox {
            objectName: form.namePrefix + "ReadingSpeedLimit"
            enabled: form.values.readingSpeed
            from: 1; to: 100; value: form.values.cpsLimit; editable: true
            Accessible.name: "Максимальная скорость чтения"
            onValueModified: form.edited("cpsLimit", value)
        }
    }
    RowLayout {
        Layout.fillWidth: true
        CheckBox {
            objectName: form.namePrefix + "LineLengthCheck"
            text: "Знаков в строке"
            Layout.fillWidth: true
            checked: form.values.lineLength
            onClicked: form.edited("lineLength", checked)
        }
        DialogSpinBox {
            objectName: form.namePrefix + "LineLengthLimit"
            enabled: form.values.lineLength
            from: 10; to: 200; value: form.values.lineLimit; editable: true
            Accessible.name: "Максимальная длина строки"
            onValueModified: form.edited("lineLimit", value)
        }
    }
    RowLayout {
        Layout.fillWidth: true
        CheckBox {
            objectName: form.namePrefix + "LineCountCheck"
            text: "Строк в реплике"
            Layout.fillWidth: true
            checked: form.values.lineCount
            onClicked: form.edited("lineCount", checked)
        }
        DialogSpinBox {
            objectName: form.namePrefix + "LineCountLimit"
            enabled: form.values.lineCount
            from: 1; to: 10; value: form.values.lineCountLimit; editable: true
            Accessible.name: "Максимальное количество строк"
            onValueModified: form.edited("lineCountLimit", value)
        }
    }
    CheckBox {
        objectName: form.namePrefix + "OverlapsCheck"
        text: "Пересекающиеся строки"
        checked: form.values.overlaps
        onClicked: form.edited("overlaps", checked)
    }
}
