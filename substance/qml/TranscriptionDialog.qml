import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "transcriptionDialog"
    title: "Автоматические субтитры"
    preferredWidth: 680
    preferredHeight: 760
    readonly property var speech: backend.transcription
    readonly property var selectedModel: speech.models[modelChoice.currentIndex] || ({})
    function timecode(ms) {
        let seconds = Math.floor(ms / 1000)
        return String(Math.floor(seconds / 3600)).padStart(2, "0") + ":"
            + String(Math.floor(seconds / 60) % 60).padStart(2, "0") + ":"
            + String(seconds % 60).padStart(2, "0") + "." + String(ms % 1000).padStart(3, "0")
    }
    onOpened: {
        let index = speech.models.findIndex(item => item.id === speech.savedModel)
        modelChoice.currentIndex = index < 0 ? 2 : index
        index = speech.languages.findIndex(item => item.id === speech.savedLanguage)
        languageChoice.currentIndex = index < 0 ? 0 : index
        audioChoice.currentIndex = Math.max(0, backend.media.activeAudio)
        destination.currentIndex = speech.canAppend ? 0 : 1
        let timing = speech.timing
        pauseTime.value = timing.pause_ms
        minimumTime.value = timing.min_duration_ms
        maximumTime.value = timing.max_duration_ms
        readingSpeed.value = timing.reading_cps
        leadTime.value = timing.lead_ms
        tailTime.value = timing.tail_ms
        holdTime.value = timing.max_hold_ms
        gapTime.value = timing.gap_ms
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        ScrollView {
            id: optionsScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            rightPadding: 12
            contentWidth: availableWidth
            ColumnLayout {
                width: optionsScroll.availableWidth
                spacing: 12
        Label {
            text: "При первом запуске реплики появляются в таблице по мере распознавания. Повторный запуск обновляет прежний результат после завершения, сохраняя ручные правки."
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: backend.media.name; elide: Text.ElideMiddle; Layout.fillWidth: true }
            Button { objectName: "speechChooseMedia"; text: "Выбрать файл…"; enabled: !speech.busy && !backend.busy; onClicked: backend.openMedia() }
        }
        GridLayout {
            columns: 2
            columnSpacing: 12
            rowSpacing: 10
            Layout.fillWidth: true
            enabled: !speech.busy
            Label { text: "Аудиодорожка" }
            ComboBox {
                id: audioChoice
                objectName: "speechAudioTrack"
                Layout.fillWidth: true
                model: backend.media.audioTracks.length ? backend.media.audioTracks : ["1 · Аудиодорожка"]
            }
            Label { text: "Язык речи" }
            ComboBox { id: languageChoice; objectName: "speechLanguage"; Layout.fillWidth: true; model: speech.languages; textRole: "title" }
            Label { text: "Модель" }
            ComboBox { id: modelChoice; objectName: "speechModel"; Layout.fillWidth: true; model: speech.modelTitles }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: dialog.selectedModel.installed ? "Скачана · проверяется перед запуском" : "Нужно скачать модель"; color: dialog.colors.muted; Layout.fillWidth: true }
            Button { objectName: "speechDownloadModel"; text: "Скачать"; visible: !dialog.selectedModel.installed; enabled: !speech.busy; onClicked: speech.download(dialog.selectedModel.id) }
            Button { objectName: "speechRemoveModel"; text: "Удалить модель"; visible: !!dialog.selectedModel.exists; enabled: !speech.busy; onClicked: speech.removeModel(dialog.selectedModel.id) }
        }
        GridLayout {
            columns: 2
            columnSpacing: 12
            rowSpacing: 10
            Layout.fillWidth: true
            enabled: !speech.busy
            Label { text: "Диапазон" }
            RowLayout {
                Layout.fillWidth: true
                TextField { id: startTime; objectName: "speechStart"; text: "00:00:00.000"; Layout.fillWidth: true; Accessible.name: "Начало распознавания"; selectByMouse: true }
                Label { text: "—" }
                TextField { id: endTime; objectName: "speechEnd"; placeholderText: "До конца файла"; Layout.fillWidth: true; Accessible.name: "Конец распознавания"; selectByMouse: true }
            }
            Label { text: "Длина строки" }
            RowLayout {
                DialogSpinBox { id: lineWidth; objectName: "speechLineWidth"; from: 20; to: 100; value: 42; editable: true }
                Label { text: "символа · до двух строк в реплике"; color: dialog.colors.muted }
            }
            Label { text: "Результат" }
            ComboBox { id: destination; objectName: "speechDestination"; Layout.fillWidth: true; model: ["Создать / обновить в текущем документе", "Создать новый локальный документ"] }
        }
        Label {
            visible: !speech.canAppend && destination.currentIndex === 0
            text: speech.canAppend ? "" : "Оригинал этой онлайн-серии неизменяем. Выберите новый локальный документ."
            wrapMode: Text.Wrap
            color: dialog.colors.warning
            Layout.fillWidth: true
        }
        GroupBox {
            title: "Тайминг и время чтения"
            Layout.fillWidth: true
            enabled: !speech.busy
            ColumnLayout {
                anchors.fill: parent
                spacing: 10
                Label { text: "Границы фраз определяются по словам и паузам в речи. Продление для чтения ограничено следующей фразой и допустимой задержкой."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted }
                GridLayout {
                    columns: 3
                    Layout.fillWidth: true
                    rowSpacing: 8
                    columnSpacing: 12
                    Label { text: "Скорость чтения"; Layout.fillWidth: true }
                    DialogSpinBox { id: readingSpeed; objectName: "speechReadingSpeed"; from: 8; to: 40; value: 17; editable: true }
                    Label { text: "зн/с" }
                    Label { text: "Минимальное время на экране" }
                    DialogSpinBox { id: minimumTime; objectName: "speechMinDuration"; from: 300; to: 3000; stepSize: 100; value: 1000; editable: true }
                    Label { text: "мс" }
                    Label { text: "Максимальная длина фразы" }
                    DialogSpinBox { id: maximumTime; objectName: "speechMaxDuration"; from: 2000; to: 12000; stepSize: 500; value: 6000; editable: true }
                    Label { text: "мс" }
                    Label { text: "Разделять по паузе от" }
                    DialogSpinBox { id: pauseTime; objectName: "speechPause"; from: 150; to: 2000; stepSize: 50; value: 450; editable: true }
                    Label { text: "мс" }
                    Label { text: "Появление до начала речи" }
                    DialogSpinBox { id: leadTime; objectName: "speechLead"; from: 0; to: 500; stepSize: 20; value: 0; editable: true }
                    Label { text: "мс" }
                    Label { text: "Задержка после конца речи" }
                    DialogSpinBox { id: tailTime; objectName: "speechTail"; from: 0; to: 1000; stepSize: 20; value: 120; editable: true }
                    Label { text: "мс" }
                    Label { text: "Максимальное продление для чтения" }
                    DialogSpinBox { id: holdTime; objectName: "speechMaxHold"; from: 0; to: 3000; stepSize: 100; value: 800; editable: true }
                    Label { text: "мс" }
                    Label { text: "Промежуток между субтитрами" }
                    DialogSpinBox { id: gapTime; objectName: "speechGap"; from: 0; to: 500; stepSize: 20; value: 80; editable: true }
                    Label { text: "мс" }
                }
            }
        }
        CheckBox { id: cpuOnly; objectName: "speechCpuOnly"; text: "Использовать только процессор"; enabled: !speech.busy }
        Label {
            visible: !speech.engineReady
            text: "Движок не найден. При запуске из исходников выполните: python scripts/build_whisper.py"
            wrapMode: Text.Wrap
            Layout.fillWidth: true
            color: dialog.colors.warning
        }
        ProgressBar { Layout.fillWidth: true; visible: speech.busy; value: speech.progress; indeterminate: speech.busy && speech.progress === 0 }
        Label { objectName: "speechStatus"; text: speech.status; color: speech.error ? dialog.colors.warning : dialog.colors.muted; wrapMode: Text.Wrap; maximumLineCount: 4; elide: Text.ElideRight; Layout.fillWidth: true }
        Label { text: "После скачивания модель работает без интернета. Аудио остаётся на компьютере. Текст и границы реплик потребуют проверки."; color: dialog.colors.muted; wrapMode: Text.Wrap; font.pixelSize: 11; Layout.fillWidth: true }
            }
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            Button { text: "Отменить результат"; visible: speech.canDiscard; onClicked: speech.discard() }
            Button { text: "Закрыть"; onClicked: dialog.close() }
            Button { text: "Остановить"; visible: speech.busy; enabled: !speech.stopping; onClicked: speech.stop() }
            Button {
                objectName: "speechStartButton"
                text: "Начать распознавание"
                highlighted: true
                visible: !speech.busy
                enabled: speech.engineReady && !!dialog.selectedModel.installed && backend.media.hasMedia && backend.media.duration > 0 && !backend.busy && (speech.canAppend || destination.currentIndex === 1)
                onClicked: {
                    if (speech.start({model: dialog.selectedModel.id, language: speech.languages[languageChoice.currentIndex].id,
                                      track: audioChoice.currentIndex, start: startTime.text, end: endTime.text,
                                      width: lineWidth.value, newDocument: destination.currentIndex === 1, cpu: cpuOnly.checked,
                                      timing: {pause_ms: pauseTime.value, min_duration_ms: minimumTime.value,
                                          max_duration_ms: maximumTime.value, reading_cps: readingSpeed.value,
                                          lead_ms: leadTime.value, tail_ms: tailTime.value, max_hold_ms: holdTime.value, gap_ms: gapTime.value}})) dialog.close()
                }
            }
        }
    }
}
