import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "batchDialog"
    title: "Обработать несколько файлов"
    preferredWidth: 1180
    preferredHeight: 880
    minimumWidth: Math.min(820, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(680, Screen.desktopAvailableHeight - 80)
    modal: false
    readonly property var controller: backend.batchFiles
    readonly property var preview: controller.preview
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: "Подготовьте сразу несколько серий"; font.pixelSize: 24; font.weight: Font.DemiBold }
        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "Выберите файлы и правила, проверьте результат, затем сохраните новые файлы в отдельную папку вместе с отчётами."; wrapMode: Text.Wrap; color: dialog.colors.muted }
        ToolCard {
            Layout.fillWidth: true
            colors: dialog.colors
            implicitHeight: setup.implicitHeight + 28
            ColumnLayout {
                id: setup
                anchors.fill: parent
                spacing: 8
                enabled: !dialog.controller.busy
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "1. Файлы и правила"; font.weight: Font.DemiBold }
                    Button { objectName: "batchChooseFiles"; text: "Выбрать файлы…"; onClicked: dialog.controller.chooseFiles() }
                    Label { text: "Формат результата" }
                    ComboBox { id: format; model: ["ASS", "SRT", "VTT", "TXT", "Substance"]; onActivated: dialog.controller.invalidate() }
                    Item { Layout.fillWidth: true }
                    Button { objectName: "batchAnalyze"; text: "Подготовить результат"; enabled: dialog.controller.rows.length > 0; onClicked: dialog.controller.analyze({format: format.currentText.toLowerCase(), shift: shift.value, replacements: replacements.text}) }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Профиль проверки" }
                    ComboBox { Layout.fillWidth: true; model: backend.qualityProfiles.names; onActivated: { backend.qualityProfiles.select(currentText); dialog.controller.invalidate() } }
                    Label { text: "Сдвиг, мс (− раньше / + позже)" }
                    DialogSpinBox { id: shift; from: -86400000; to: 86400000; value: 0; editable: true; stepSize: 100; onValueModified: dialog.controller.invalidate() }
                }
                Label { text: "Последовательные замены: одна на строку, например «... → …». Оставьте поле пустым, если замены не нужны."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: dialog.colors.muted }
                DialogTextArea { id: replacements; objectName: "batchReplacements"; Layout.fillWidth: true; Layout.preferredHeight: 64; placeholderText: "найти → заменить"; wrapMode: TextEdit.Wrap; onTextChanged: dialog.controller.invalidate() }
                Label { visible: format.currentText !== "Substance"; Layout.fillWidth: true; text: format.currentText === "ASS" ? "ASS сохранит итоговый текст и оформление. Оригинал, перевод и заметки вместе сохраняет формат Substance." : "SRT/VTT/TXT содержат итоговый текст без оформления ASS. Для проекта с оригиналом, переводом и заметками выберите Substance."; color: dialog.colors.muted; wrapMode: Text.Wrap; font.pixelSize: 11 }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { objectName: "batchStatus"; Layout.fillWidth: true; text: dialog.controller.status; wrapMode: Text.Wrap }
            ProgressBar { visible: dialog.controller.busy; Layout.preferredWidth: 160; value: dialog.controller.progress; indeterminate: value === 0 }
            Button { visible: dialog.controller.busy; text: "Остановить"; onClicked: dialog.controller.cancel() }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12
            ToolCard {
                colors: dialog.colors
                Layout.preferredWidth: dialog.width * .32
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    Label { text: "2. Выберите файлы для записи"; font.weight: Font.DemiBold }
                    ListView {
                        id: files
                        objectName: "batchFileList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: width - 16
                        model: dialog.controller.rows
                        ScrollBar.vertical: ScrollBar {}
                        delegate: ItemDelegate {
                            id: file
                            required property var modelData
                            required property int index
                            width: files.contentWidth
                            height: fileContent.implicitHeight + 16
                            onClicked: dialog.controller.previewRow(index)
                            RowLayout {
                                id: fileContent
                                anchors.fill: parent
                                anchors.margins: 8
                                CheckBox { enabled: !dialog.controller.busy && !file.modelData.error; checked: file.modelData.checked; onClicked: dialog.controller.check(file.index, checked); Accessible.name: "Записать " + file.modelData.name }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: file.modelData.name; textFormat: Text.PlainText; elide: Text.ElideMiddle; font.weight: Font.DemiBold }
                                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: file.modelData.error || "Реплик: " + file.modelData.count + " · Замен: " + file.modelData.changed + " · Замечаний: " + file.modelData.issues; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: file.modelData.error ? dialog.colors.warning : dialog.colors.muted }
                                }
                            }
                        }
                        Label { anchors.centerIn: parent; visible: files.count === 0; width: parent.width - 20; text: "Выберите субтитры нескольких серий."; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; color: dialog.colors.muted }
                    }
                }
            }
            ToolCard {
                colors: dialog.colors
                Layout.fillWidth: true
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    Label { text: "3. Проверьте пример результата"; font.weight: Font.DemiBold }
                    Label { text: "Первые 8 реплик выбранного файла"; color: dialog.colors.muted }
                    ScrollView {
                        id: resultScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        contentWidth: availableWidth
                        clip: true
                        ColumnLayout {
                            width: resultScroll.availableWidth
                            Label { text: "Сейчас"; font.weight: Font.DemiBold }
                            DialogTextArea { Layout.fillWidth: true; text: dialog.preview.before || "Подготовьте результат и выберите файл слева."; readOnly: true; wrapMode: TextEdit.Wrap }
                            Label { text: "После обработки"; font.weight: Font.DemiBold }
                            DialogTextArea { Layout.fillWidth: true; text: dialog.preview.after || ""; readOnly: true; wrapMode: TextEdit.Wrap }
                            Label { text: "Замечания проверки"; font.weight: Font.DemiBold }
                            Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.preview.issues || ""; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: dialog.colors.muted }
                        }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Button { text: "Папка результата…"; enabled: !dialog.controller.busy; onClicked: dialog.controller.chooseFolder() }
            Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.controller.destination || "Выберите, куда сохранить новые файлы"; elide: Text.ElideMiddle }
            Button { visible: !!dialog.controller.output; text: "Показать результат"; onClicked: dialog.controller.reveal() }
            Button { text: "Закрыть"; onClicked: dialog.dismiss() }
            Button { objectName: "batchRun"; text: "Сохранить новые файлы"; enabled: dialog.controller.canRun; highlighted: true; onClicked: dialog.controller.run() }
        }
    }
}
