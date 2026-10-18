import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "hardsubDialog"
    title: "Хардсаб из видео"
    preferredWidth: 940
    preferredHeight: 820
    readonly property var ocr: backend.hardsubTools
    readonly property var selectedRow: ocr.rows[results.currentIndex] || ({})
    property int editIndex: -1
    function loadRow(index) {
        let row = ocr.rows[index] || ({})
        editIndex = row.text !== undefined ? index : -1
        correction.text = row.text || ""
        resultStart.text = row.startLabel || ""
        resultEnd.text = row.endLabel || ""
    }
    function saveRow() {
        return editIndex < 0 || ocr.editRow(editIndex, correction.text, resultStart.text, resultEnd.text)
    }
    function chooseRow(index) {
        if (index === editIndex) return
        if (!saveRow()) return
        results.currentIndex = index
        loadRow(index)
    }
    Connections {
        target: dialog.ocr
        function onChanged() {
            if (!dialog.ocr.rows.length) dialog.loadRow(-1)
            else if (dialog.editIndex < 0 || dialog.editIndex >= dialog.ocr.rows.length) {
                results.currentIndex = 0
                dialog.loadRow(0)
                revealResults.restart()
            }
        }
    }
    Timer {
        id: revealResults
        interval: 60
        onTriggered: scroll.contentItem.contentY = Math.max(0, Math.min(foundGroup.y, scroll.contentItem.contentHeight - scroll.availableHeight))
    }
    function options() {
        return {start: startTime.text, end: endTime.text, language: language.currentText,
                x: regionX.value, y: regionY.value, width: regionWidth.value, height: regionHeight.value,
                step: step.value, confidence: confidence.value, minimum: minimum.value}
    }
    onOpened: {
        forTranslation.checked = backend.mode === "translation"
        language.currentIndex = Math.max(0, ocr.languages.indexOf(ocr.savedLanguage))
        if (!ocr.busy && backend.media.hasVideo && !ocr.previewUrl) ocr.previewFrame()
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        Label {
            Layout.fillWidth: true
            text: "Поиск текста, вшитого в изображение. Вывески и титры тоже могут попасть в результат — проверьте найденные фрагменты перед добавлением."
            wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: backend.media.name; Layout.fillWidth: true; elide: Text.ElideMiddle }
            Button { text: "Открыть видео…"; enabled: !ocr.busy && !backend.busy; onClicked: backend.openMedia() }
        }
        ScrollView {
            id: scroll
            objectName: "hardsubScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                width: scroll.availableWidth
                spacing: 10
                GroupBox {
                    title: "Область текста"
                    Layout.fillWidth: true
                    enabled: !ocr.busy
                    ColumnLayout {
                        anchors.fill: parent
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 190
                            color: "#15171a"
                            Image {
                                id: frame
                                objectName: "hardsubFrame"
                                anchors.fill: parent
                                source: ocr.previewUrl
                                fillMode: Image.PreserveAspectFit
                                cache: false
                                Rectangle {
                                    id: imageArea
                                    x: (frame.width - frame.paintedWidth) / 2
                                    y: (frame.height - frame.paintedHeight) / 2
                                    width: frame.paintedWidth
                                    height: frame.paintedHeight
                                    color: "transparent"
                                    Rectangle {
                                        x: regionX.value / 100 * imageArea.width
                                        y: regionY.value / 100 * imageArea.height
                                        width: regionWidth.value / 100 * imageArea.width
                                        height: regionHeight.value / 100 * imageArea.height
                                        color: "#2038c8ff"
                                        border.color: "#38c8ff"
                                        border.width: 2
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        property real startX: 0
                                        property real startY: 0
                                        function updateRegion(mouse) {
                                            let endX = Math.max(0, Math.min(width, mouse.x))
                                            let endY = Math.max(0, Math.min(height, mouse.y))
                                            regionX.value = Math.min(99, Math.floor(Math.min(startX, endX) / width * 100))
                                            regionY.value = Math.min(99, Math.floor(Math.min(startY, endY) / height * 100))
                                            regionWidth.value = Math.min(100 - regionX.value, Math.max(1, Math.ceil(Math.abs(startX - endX) / width * 100)))
                                            regionHeight.value = Math.min(100 - regionY.value, Math.max(1, Math.ceil(Math.abs(startY - endY) / height * 100)))
                                        }
                                        onPressed: mouse => { startX = mouse.x; startY = mouse.y }
                                        onPositionChanged: mouse => { if (pressed) updateRegion(mouse) }
                                        onReleased: mouse => updateRegion(mouse)
                                    }
                                }
                            }
                            Label { anchors.centerIn: parent; visible: !ocr.previewUrl; text: "Откройте видео и получите кадр для выбора области"; color: "white" }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "Выделите область мышью или задайте проценты кадра."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted }
                            Button { objectName: "hardsubPreviewButton"; text: "Кадр с текущей позиции"; enabled: backend.media.hasVideo; onClicked: ocr.previewFrame() }
                        }
                        RowLayout {
                            Label { text: "X" }
                            DialogSpinBox { id: regionX; objectName: "hardsubRegionX"; from: 0; to: 99; value: 0; editable: true; Accessible.name: "Левая граница области, проценты" }
                            Label { text: "Y" }
                            DialogSpinBox { id: regionY; objectName: "hardsubRegionY"; from: 0; to: 99; value: 65; editable: true; Accessible.name: "Верхняя граница области, проценты" }
                            Label { text: "Ширина" }
                            DialogSpinBox { id: regionWidth; objectName: "hardsubRegionWidth"; from: 1; to: 100; value: 100; editable: true }
                            Label { text: "Высота" }
                            DialogSpinBox { id: regionHeight; objectName: "hardsubRegionHeight"; from: 1; to: 100; value: 35; editable: true }
                        }
                        RowLayout {
                            Button { text: "Нижняя часть"; onClicked: { regionX.value = 0; regionY.value = 65; regionWidth.value = 100; regionHeight.value = 35 } }
                            Button { text: "Верхняя часть"; onClicked: { regionX.value = 0; regionY.value = 0; regionWidth.value = 100; regionHeight.value = 35 } }
                            Button { text: "Весь кадр"; onClicked: { regionX.value = 0; regionY.value = 0; regionWidth.value = 100; regionHeight.value = 100 } }
                        }
                    }
                }
                GridLayout {
                    columns: 2
                    columnSpacing: 12
                    rowSpacing: 8
                    Layout.fillWidth: true
                    enabled: !ocr.busy
                    Label { text: "Движок OCR" }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: ocr.engineTitle; Layout.fillWidth: true }
                        Button { text: "Tesseract…"; onClicked: { ocr.chooseEngine(); language.currentIndex = Math.max(0, ocr.languages.indexOf(ocr.savedLanguage)) } }
                        Button { text: "Авто"; onClicked: { ocr.automaticEngine(); language.currentIndex = Math.max(0, ocr.languages.indexOf(ocr.savedLanguage)) } }
                    }
                    Label { text: "Язык текста" }
                    ComboBox { id: language; objectName: "hardsubLanguage"; model: ocr.languages; Layout.fillWidth: true }
                    Label { text: "Диапазон" }
                    RowLayout {
                        TextField { id: startTime; objectName: "hardsubStart"; text: "00:00:00.000"; Accessible.name: "Начало поиска хардсаба"; Layout.fillWidth: true }
                        Label { text: "—" }
                        TextField { id: endTime; objectName: "hardsubEnd"; placeholderText: "До конца видео"; Accessible.name: "Конец поиска хардсаба"; Layout.fillWidth: true }
                    }
                    Label { text: "Шаг проверки" }
                    RowLayout {
                        DialogSpinBox { id: step; objectName: "hardsubStep"; from: 100; to: 2000; stepSize: 50; value: 250; editable: true }
                        Label { text: "мс · меньше — точнее границы, дольше анализ"; color: dialog.colors.muted }
                    }
                    Label { text: "Минимум уверенности" }
                    RowLayout {
                        DialogSpinBox { id: confidence; objectName: "hardsubConfidence"; from: 0; to: 100; value: 60; editable: true }
                        Label { text: "%" }
                        Label { text: "Минимальное время" }
                        DialogSpinBox { id: minimum; from: 100; to: 10000; stepSize: 100; value: 300; editable: true }
                        Label { text: "мс" }
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: "Границы приблизительные, с шагом проверки. Короткий текст может быть пропущен. Отсутствие результата не доказывает отсутствие хардсаба. Видео обрабатывается на компьютере."
                    wrapMode: Text.Wrap
                    color: dialog.colors.muted
                    font.pixelSize: 11
                }
                GroupBox {
                    id: foundGroup
                    objectName: "hardsubFoundGroup"
                    title: "Найденные фрагменты · " + ocr.rows.length
                    Layout.fillWidth: true
                    visible: ocr.rows.length > 0
                    ColumnLayout {
                        anchors.fill: parent
                        RowLayout {
                            Button { text: "Выбрать все"; onClicked: ocr.checkAll(true) }
                            Button { text: "Снять выбор"; onClicked: ocr.checkAll(false) }
                            Label { text: "Уверенность OCR не гарантирует точность текста"; color: dialog.colors.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                        }
                        ListView {
                            id: results
                            objectName: "hardsubResults"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 185
                            clip: true
                            model: ocr.rows
                            currentIndex: 0
                            ScrollBar.vertical: ScrollBar {}
                            delegate: ItemDelegate {
                                required property var modelData
                                required property int index
                                width: results.width
                                highlighted: results.currentIndex === index
                                onClicked: dialog.chooseRow(index)
                                contentItem: RowLayout {
                                    CheckBox { checked: modelData.checked; onClicked: ocr.check(index, checked) }
                                    Label { text: modelData.startLabel + " — " + modelData.endLabel; font.pixelSize: 11 }
                                    Label { text: modelData.text.replace(/\n/g, " / "); textFormat: Text.PlainText; Layout.fillWidth: true; elide: Text.ElideRight }
                                    Label { text: modelData.score + "%"; font.pixelSize: 11 }
                                }
                            }
                        }
                        Image {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 95
                            source: dialog.selectedRow.preview || ""
                            fillMode: Image.PreserveAspectFit
                        }
                        TextArea {
                            id: correction
                            objectName: "hardsubCorrection"
                            Layout.fillWidth: true
                            textFormat: TextEdit.PlainText
                            wrapMode: TextEdit.Wrap
                            selectByMouse: true
                            Accessible.name: "Исправить распознанный текст"
                        }
                        RowLayout {
                            TextField { id: resultStart; objectName: "hardsubResultStart"; Accessible.name: "Начало найденного фрагмента" }
                            Label { text: "—" }
                            TextField { id: resultEnd; objectName: "hardsubResultEnd"; Accessible.name: "Конец найденного фрагмента" }
                            Button { text: "Сохранить правку"; onClicked: dialog.saveRow() }
                            Button { text: "Показать в видео"; onClicked: { ocr.seek(results.currentIndex); dialog.close() } }
                        }
                    }
                }
            }
        }
        Label { visible: ocr.stale; text: "Документ или видео изменились. Повторите поиск перед добавлением."; color: dialog.colors.warning; Layout.fillWidth: true; wrapMode: Text.Wrap }
        Label { visible: !ocr.canAppend; text: "Оригинал этой онлайн-серии неизменяем. Для импорта используйте локальный документ."; color: dialog.colors.warning; Layout.fillWidth: true; wrapMode: Text.Wrap }
        CheckBox { id: forTranslation; objectName: "hardsubForTranslation"; text: "Для перевода: текст в оригинал, перевод оставить пустым"; enabled: !ocr.busy }
        ProgressBar { Layout.fillWidth: true; visible: ocr.busy; value: ocr.progress; indeterminate: ocr.progress === 0 }
        Label { objectName: "hardsubStatus"; text: ocr.status; color: ocr.error ? dialog.colors.warning : dialog.colors.muted; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 3; elide: Text.ElideRight }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            Button { text: "Закрыть"; onClicked: dialog.close() }
            Button { text: "Остановить"; visible: ocr.busy; onClicked: ocr.stop() }
            Button {
                objectName: "hardsubAnalyzeButton"
                text: "Найти и распознать"
                enabled: !ocr.busy && !backend.busy && backend.media.hasVideo && ocr.engineReady
                onClicked: ocr.analyze(dialog.options())
            }
            Button {
                objectName: "hardsubApplyButton"
                text: "Добавить выбранное"
                highlighted: true
                enabled: ocr.canApply
                onClicked: { if (dialog.saveRow()) ocr.apply(forTranslation.checked) }
            }
        }
    }
}
