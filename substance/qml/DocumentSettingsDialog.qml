import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "documentSettingsDialog"
    title: "Настройки документа"
    preferredWidth: 640
    preferredHeight: 720
    minimumWidth: Math.min(560, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(540, Screen.desktopAvailableHeight - 80)
    modal: false
    property var checks: Object.assign({}, backend.reviewSettings)
    property var encodings: ["utf-8", "cp1251", "utf-16"]
    function reload() {
        fps.text = backend.fps.toString()
        encoding.currentIndex = Math.max(0, encodings.indexOf(backend.encoding))
        checks = Object.assign({}, backend.reviewSettings)
    }
    onOpened: reload()
    ScrollView {
        id: scroll
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            width: scroll.availableWidth
            spacing: 18
            Label { text: backend.title; font.pixelSize: 20; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText }
            Label { text: "Параметры относятся только к открытому документу. Изменения применяются вместе; их можно отменить через «Правка → Отменить»."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: dialog.colors.muted }
            DialogSection {
                title: "Формат и время"
                Layout.fillWidth: true
                GridLayout {
                    anchors.fill: parent
                    columns: 2
                    rowSpacing: 12
                    Label { text: "Частота кадров" }
                    DialogTextField {
                        id: fps
                        objectName: "documentFps"
                        Layout.fillWidth: true
                        Accessible.name: "Частота кадров документа"
                        validator: DoubleValidator { bottom: 1; top: 120; locale: "en_US" }
                    }
                    Label { text: "Кодировка ASS" }
                    ComboBox {
                        id: encoding
                        objectName: "documentEncoding"
                        Layout.fillWidth: true
                        model: ["UTF-8", "Windows-1251", "UTF-16"]
                    }
                }
            }
            DialogSection {
                title: "Проверки документа"
                Layout.fillWidth: true
                ReviewSettingsForm {
                    anchors.fill: parent
                    namePrefix: "document"
                    values: dialog.checks
                    onEdited: (key, value) => dialog.checks = Object.assign({}, dialog.checks, {[key]: value})
                }
            }
            Label { text: "Пороги и включённые проверки сохраняются в проекте .substance или в сопутствующем файле .ass.substance рядом с ASS. Точное время хранится в миллисекундах; ASS округляет его до сотых секунды."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: dialog.colors.muted }
        }
    }
    footer: DialogButtonBox {
        leftPadding: 20; rightPadding: 20; bottomPadding: 20; topPadding: 8
        Button { objectName: "documentSettingsCancel"; text: "Отмена"; onClicked: dialog.reject() }
        Button {
            objectName: "documentSettingsApply"
            text: "Применить"
            highlighted: true
            enabled: fps.acceptableInput && !backend.busy
            onClicked: {
                if (backend.documentSettings(Number(fps.text), dialog.encodings[encoding.currentIndex], dialog.checks)) dialog.dismiss()
            }
        }
    }
}
