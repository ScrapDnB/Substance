import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "bitmapSubtitleDialog"
    title: "Субтитры из изображений PGS / VobSub"
    preferredWidth: 1140
    preferredHeight: 870
    minimumWidth: Math.min(820, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(680, Screen.desktopAvailableHeight - 80)
    modal: false
    readonly property var controller: backend.bitmapSubtitles
    readonly property var ocr: backend.hardsubTools
    readonly property var preview: controller.preview
    property int loadedIndex: -1
    property string loadedSignature: ""
    function loadPreview() {
        let p = controller.preview
        let signature = JSON.stringify([p.index, p.text, p.startText, p.endText])
        if (signature === loadedSignature) return
        loadedSignature = signature; loadedIndex = p.index === undefined ? -1 : p.index
        textEdit.text = p.text || ""; start.text = p.startText || ""; end.text = p.endText || ""
    }
    function commitPreview() {
        if (loadedIndex < 0) return true
        let p = controller.preview
        if (textEdit.text === p.text && start.text === p.startText && end.text === p.endText) return true
        return controller.updateRow(loadedIndex, textEdit.text, start.text, end.text)
    }
    Connections { target: dialog.controller; function onChanged() { dialog.loadPreview() } }
    onClosed: controller.cancel()
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: "Превратите изображения субтитров в текст"; font.pixelSize: 24; font.weight: Font.DemiBold }
        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "Откройте PGS (.sup), VobSub (.idx вместе с .sub) или графическую дорожку MKV. После распознавания проверьте текст по картинкам. Исходные интервалы сохраняются."; wrapMode: Text.Wrap; color: dialog.colors.muted }
        ToolCard {
            Layout.fillWidth: true
            colors: dialog.colors
            implicitHeight: setup.implicitHeight + 28
            ColumnLayout {
                id: setup
                anchors.fill: parent
                spacing: 10
                enabled: !dialog.controller.busy
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "1. Выберите изображения и язык"; font.weight: Font.DemiBold }
                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.controller.source || "Файл ещё не выбран"; elide: Text.ElideMiddle }
                    Button { objectName: "bitmapChooseSource"; text: "Выбрать файл…"; onClicked: dialog.controller.chooseSource() }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Дорожка" }
                    ComboBox { id: track; Layout.fillWidth: true; model: dialog.controller.tracks }
                    Label { text: "Язык текста" }
                    ComboBox { id: language; Layout.preferredWidth: 150; model: dialog.ocr.languages }
                    Button { objectName: "bitmapAnalyze"; text: "Распознать изображения"; enabled: dialog.ocr.engineReady && dialog.controller.tracks.length > 0 && language.currentIndex >= 0; onClicked: dialog.controller.analyze(track.currentIndex, language.currentText) }
                }
                RowLayout {
                    visible: !dialog.ocr.engineReady
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "Нужен движок распознавания текста. На macOS доступен Apple Vision; можно выбрать установленный Tesseract."; wrapMode: Text.Wrap; color: dialog.colors.warning }
                    Button { text: "Выбрать Tesseract…"; onClicked: dialog.ocr.chooseEngine() }
                    Button { text: "Проверить снова"; onClicked: dialog.ocr.refreshEngine() }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.controller.status; wrapMode: Text.Wrap; color: dialog.controller.stale ? dialog.colors.warning : dialog.colors.muted }
            ProgressBar { Layout.preferredWidth: 160; visible: dialog.controller.busy; value: dialog.controller.progress; indeterminate: value === 0 }
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
                    Label { text: "2. Выберите реплики"; font.weight: Font.DemiBold }
                    RowLayout {
                        Button { text: "Выбрать все"; enabled: !dialog.controller.busy; onClicked: dialog.controller.checkAll(true) }
                        Button { text: "Снять"; enabled: !dialog.controller.busy; onClicked: dialog.controller.checkAll(false) }
                    }
                    ListView {
                        id: list
                        objectName: "bitmapRows"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: width - 16
                        model: dialog.controller.rows
                        ScrollBar.vertical: ScrollBar {}
                        delegate: ItemDelegate {
                            id: row
                            required property var modelData
                            required property int index
                            width: list.contentWidth
                            height: rowContent.implicitHeight + 16
                            enabled: !dialog.controller.busy
                            onClicked: { if (dialog.commitPreview()) dialog.controller.previewRow(index) }
                            RowLayout {
                                id: rowContent
                                anchors.fill: parent
                                anchors.margins: 8
                                CheckBox { checked: row.modelData.checked; Accessible.name: "Импортировать реплику " + row.modelData.number; onClicked: dialog.controller.check(row.index, checked) }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "№ " + row.modelData.number + " · " + row.modelData.time; font.pixelSize: 11; elide: Text.ElideRight }
                                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: row.modelData.text || "Текст не распознан"; textFormat: Text.PlainText; elide: Text.ElideRight }
                                }
                            }
                        }
                    }
                }
            }
            ToolCard {
                colors: dialog.colors
                Layout.fillWidth: true
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    Label { text: "3. Сверьте текст с изображением"; font.weight: Font.DemiBold }
                    Image { Layout.fillWidth: true; Layout.preferredHeight: 160; source: dialog.preview.preview || ""; fillMode: Image.PreserveAspectFit }
                    DialogTextArea { id: textEdit; objectName: "bitmapText"; Layout.fillWidth: true; Layout.fillHeight: true; wrapMode: TextEdit.Wrap; placeholderText: "Здесь можно исправить распознанный текст"; enabled: !dialog.controller.busy }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Начало" }
                        DialogTextField { id: start; Layout.fillWidth: true; enabled: !dialog.controller.busy }
                        Label { text: "Конец" }
                        DialogTextField { id: end; Layout.fillWidth: true; enabled: !dialog.controller.busy }
                        Button { text: "Сохранить исправление"; enabled: dialog.preview.index !== undefined && !dialog.controller.busy; onClicked: dialog.controller.updateRow(dialog.preview.index, textEdit.text, start.text, end.text) }
                    }
                }
            }
        }
        CheckBox { id: translation; text: "Подготовить для перевода: распознанный текст станет оригиналом"; checked: true }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button { text: "Закрыть"; onClicked: dialog.dismiss() }
            Button { objectName: "bitmapImport"; text: "Добавить отмеченные реплики"; enabled: dialog.controller.canApply; highlighted: true; onClicked: { if (dialog.commitPreview()) dialog.controller.apply(translation.checked) } }
        }
    }
}
