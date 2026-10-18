import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Substance 1.0

NativeDialog {
    id: dialog
    objectName: "transcriptionDialog"
    title: "Распознавание речи"
    preferredWidth: 1280
    preferredHeight: 900
    minimumWidth: Math.min(800, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(680, Screen.desktopAvailableHeight - 80)
    modal: false
    readonly property var speech: backend.transcription
    readonly property var selectedModel: speech.models[modelChoice.currentIndex] || ({})
    property int previewIndex: -1
    readonly property var preview: speech.previewRows[previewIndex] || ({})
    property string viewportKey: ""
    function syncPreviewView() {
        let key = previewIndex + ":" + preview.start + ":" + preview.end
        if (preview.start !== undefined && key !== viewportKey) {
            viewportKey = key
            resultWave.setViewport(Math.max(0, preview.start - 500), Math.max(3000, preview.end - preview.start + 1000))
        }
    }
    onPreviewChanged: syncPreviewView()
    function startRecognition() {
        speech.start({model: selectedModel.id, language: speech.languages[languageChoice.currentIndex].id,
            track: audioChoice.currentIndex, start: startTime.text, end: endTime.text,
            width: lineWidth.value, newDocument: destination.currentIndex === 1, cpu: cpuOnly.checked,
            timing: {pause_ms: pauseTime.value, min_duration_ms: minimumTime.value,
                max_duration_ms: maximumTime.value, reading_cps: readingSpeed.value,
                lead_ms: leadTime.value, tail_ms: tailTime.value, max_hold_ms: holdTime.value, gap_ms: gapTime.value}})
    }
    onOpened: {
        if (speech.busy) return
        let index = speech.models.findIndex(item => item.id === speech.savedModel)
        let installed = speech.models.findIndex(item => item.installed)
        modelChoice.currentIndex = index >= 0 && speech.models[index].installed ? index : installed >= 0 ? installed : index < 0 ? 2 : index
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
    Connections {
        target: dialog.speech
        function onChanged() {
            let count = dialog.speech.previewRows.length
            if (!count) dialog.previewIndex = -1
            else if (follow.checked || dialog.previewIndex < 0 || dialog.previewIndex >= count) dialog.previewIndex = count - 1
            dialog.syncPreviewView()
        }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 14
        Label { text: "Субтитры из речи"; font.pixelSize: 24; font.weight: Font.DemiBold }
        Label { text: "Выберите аудио и язык. Распознанные реплики будут появляться здесь — их можно сразу прослушать и проверить."; color: dialog.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
        ToolCard {
            colors: dialog.colors
            Layout.fillWidth: true
            implicitHeight: setup.implicitHeight + 28
            ColumnLayout {
                id: setup
                anchors.fill: parent
                spacing: 10
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "1. Настройте распознавание"; font.weight: Font.DemiBold; Layout.fillWidth: true }
                    Button { id: advanced; objectName: "speechAdvancedToggle"; text: checked ? "Скрыть параметры" : "Дополнительные настройки"; checkable: true; enabled: !dialog.speech.busy }
                    Button { objectName: "speechChooseMedia"; text: "Открыть файл…"; enabled: !dialog.speech.busy && !backend.busy; onClicked: backend.openMedia() }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: dialog.width >= 1100 ? 6 : 4
                    columnSpacing: 10
                    rowSpacing: 10
                    enabled: !dialog.speech.busy
                    Label { text: "Аудиодорожка" }
                    ComboBox { id: audioChoice; objectName: "speechAudioTrack"; Layout.fillWidth: true; model: backend.media.audioTracks.length ? backend.media.audioTracks : ["1 · Аудиодорожка"]; onActivated: index => backend.media.setAudioTrack(index) }
                    Label { text: "Язык речи" }
                    ComboBox { id: languageChoice; objectName: "speechLanguage"; Layout.fillWidth: true; model: dialog.speech.languages; textRole: "title" }
                    Label { text: "Модель" }
                    ComboBox { id: modelChoice; objectName: "speechModel"; Layout.fillWidth: true; model: dialog.speech.modelTitles }
                }
                RowLayout {
                    Layout.fillWidth: true
                    enabled: !dialog.speech.busy
                    Label { text: "Результат" }
                    ComboBox { id: destination; objectName: "speechDestination"; Layout.fillWidth: true; model: ["В текущий документ", "В новый локальный документ"] }
                    Label { text: "Диапазон" }
                    TextField { id: startTime; objectName: "speechStart"; text: "00:00:00.000"; Layout.preferredWidth: 125; Accessible.name: "Начало распознавания"; selectByMouse: true }
                    Label { text: "—" }
                    TextField { id: endTime; objectName: "speechEnd"; placeholderText: "До конца"; Layout.preferredWidth: 125; Accessible.name: "Конец распознавания"; selectByMouse: true }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: !backend.media.hasMedia ? "Сначала откройте видео или аудио." : backend.media.name + " · " + (dialog.selectedModel.installed ? "Модель скачана" : "Нужно скачать модель (" + Math.round((dialog.selectedModel.bytes || 0) / 1048576) + " МБ)")
                        elide: Text.ElideMiddle
                        color: !backend.media.hasMedia || !dialog.selectedModel.installed ? dialog.colors.warning : dialog.colors.muted
                    }
                    Button { objectName: "speechDownloadModel"; text: "Скачать модель"; visible: !dialog.selectedModel.installed; enabled: !dialog.speech.busy; onClicked: dialog.speech.download(dialog.selectedModel.id) }
                }
                ScrollView {
                    id: optionsScroll
                    visible: advanced.checked
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(Math.max(60, Math.min(195, dialog.height - 620)), advancedOptions.implicitHeight)
                    contentWidth: availableWidth
                    clip: true
                    ColumnLayout {
                        id: advancedOptions
                        width: optionsScroll.availableWidth
                        spacing: 10
                        enabled: !dialog.speech.busy
                        Label { text: "Строки и время чтения"; font.weight: Font.DemiBold }
                        GridLayout {
                            columns: 4
                            columnSpacing: 10
                            rowSpacing: 8
                            Layout.fillWidth: true
                            Label { text: "Символов в строке" }
                            DialogSpinBox { id: lineWidth; objectName: "speechLineWidth"; from: 20; to: 100; value: 42; editable: true }
                            Label { text: "Скорость чтения, зн/с" }
                            DialogSpinBox { id: readingSpeed; objectName: "speechReadingSpeed"; from: 8; to: 40; value: 17; editable: true }
                            Label { text: "Мин. время на экране, мс" }
                            DialogSpinBox { id: minimumTime; objectName: "speechMinDuration"; from: 300; to: 3000; stepSize: 100; value: 1000; editable: true }
                            Label { text: "Макс. длина фразы, мс" }
                            DialogSpinBox { id: maximumTime; objectName: "speechMaxDuration"; from: 2000; to: 12000; stepSize: 500; value: 6000; editable: true }
                            Label { text: "Разделять по паузе от, мс" }
                            DialogSpinBox { id: pauseTime; objectName: "speechPause"; from: 150; to: 2000; stepSize: 50; value: 450; editable: true }
                            Label { text: "Промежуток реплик, мс" }
                            DialogSpinBox { id: gapTime; objectName: "speechGap"; from: 0; to: 500; stepSize: 20; value: 80; editable: true }
                            Label { text: "Появление до речи, мс" }
                            DialogSpinBox { id: leadTime; objectName: "speechLead"; from: 0; to: 500; stepSize: 20; value: 0; editable: true }
                            Label { text: "Задержка после речи, мс" }
                            DialogSpinBox { id: tailTime; objectName: "speechTail"; from: 0; to: 1000; stepSize: 20; value: 120; editable: true }
                            Label { text: "Продлить для чтения, мс" }
                            DialogSpinBox { id: holdTime; objectName: "speechMaxHold"; from: 0; to: 3000; stepSize: 100; value: 800; editable: true }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            CheckBox { id: cpuOnly; objectName: "speechCpuOnly"; text: "Использовать только процессор"; Layout.fillWidth: true }
                            Button { objectName: "speechRemoveModel"; text: "Удалить модель с компьютера"; visible: !!dialog.selectedModel.exists; onClicked: dialog.speech.removeModel(dialog.selectedModel.id) }
                        }
                        Label { text: "До двух строк в реплике. Продление для чтения ограничено следующей фразой. После скачивания модели аудио обрабатывается без интернета."; color: dialog.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { objectName: "speechStatus"; text: dialog.speech.status; color: dialog.speech.error ? dialog.colors.warning : dialog.colors.muted; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight; Layout.fillWidth: true }
            ProgressBar { Layout.preferredWidth: 160; visible: dialog.speech.busy; value: dialog.speech.progress; indeterminate: value === 0 }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 210
            spacing: 14
            ToolCard {
                colors: dialog.colors
                Layout.preferredWidth: Math.max(260, (dialog.width - 54) * .36)
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "2. Распознанные реплики"; font.weight: Font.DemiBold; Layout.fillWidth: true }
                        Label { text: resultList.count; color: dialog.colors.muted }
                    }
                    CheckBox { id: follow; objectName: "speechFollowResults"; text: "Показывать новые реплики"; checked: true }
                    ListView {
                        id: resultList
                        objectName: "speechResultList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        contentWidth: Math.max(0, width - resultsScrollBar.width - 6)
                        flickableDirection: Flickable.VerticalFlick
                        clip: true
                        spacing: 6
                        model: dialog.speech.previewRows
                        currentIndex: dialog.previewIndex
                        onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
                        activeFocusOnTab: true
                        Keys.onUpPressed: { follow.checked = false; dialog.previewIndex = Math.max(0, currentIndex - 1) }
                        Keys.onDownPressed: { follow.checked = false; dialog.previewIndex = Math.min(count - 1, currentIndex + 1) }
                        ScrollBar.vertical: ScrollBar { id: resultsScrollBar; objectName: "speechResultsScrollBar" }
                        delegate: Rectangle {
                            id: phrase
                            required property var modelData
                            required property int index
                            width: resultList.contentWidth
                            height: phraseContents.implicitHeight + 20
                            radius: 9
                            color: index === dialog.previewIndex ? Qt.alpha(dialog.colors.accent, .09) : dialog.colors.panel
                            border.color: index === dialog.previewIndex ? dialog.colors.accent : dialog.colors.separator
                            TapHandler { onTapped: { resultList.forceActiveFocus(); follow.checked = false; dialog.previewIndex = phrase.index } }
                            ColumnLayout {
                                id: phraseContents
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 5
                                Label { text: "Реплика " + (phrase.index + 1) + " · " + phrase.modelData.startText; Layout.fillWidth: true; font.weight: Font.DemiBold; color: dialog.colors.text }
                                Label { text: phrase.modelData.text; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true; color: dialog.colors.muted }
                            }
                        }
                        Label {
                            anchors.centerIn: parent
                            width: parent.width - 20
                            visible: resultList.count === 0
                            text: dialog.speech.running ? "Слушаем аудио…" : "Реплики появятся во время распознавания"
                            color: dialog.colors.muted
                            wrapMode: Text.Wrap
                            horizontalAlignment: Text.AlignHCenter
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
                    spacing: 12
                    Label { text: "3. Проверьте субтитры"; font.weight: Font.DemiBold }
                    ScrollView {
                        id: previewScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        contentWidth: availableWidth
                        clip: true
                        ColumnLayout {
                            width: previewScroll.availableWidth
                            spacing: 14
                            Label { text: dialog.preview.text === undefined ? "Превью распознанной речи" : "Реплика " + (dialog.previewIndex + 1); font.pixelSize: 20; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { visible: dialog.preview.text === undefined; text: "Здесь появятся текст, переносы и время выбранной реплики. Окно останется открытым после запуска."; color: dialog.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            SubtitlePreview { objectName: "speechSubtitlePreview"; Layout.fillWidth: true; colors: dialog.colors; cues: dialog.preview.text !== undefined ? [dialog.preview] : []; proposed: true }
                            Waveform {
                                id: resultWave
                                objectName: "speechWaveformPreview"
                                visible: dialog.preview.text !== undefined
                                Layout.fillWidth: true
                                Layout.preferredHeight: 90
                                media: backend.media
                                paletteColors: dialog.colors
                                start: dialog.preview.start || 0
                                end: dialog.preview.end || 1000
                                onSeekRequested: position => backend.media.seek(position)
                            }
                            Label { text: dialog.speech.replacing ? "Это новый вариант. Прежние машинные реплики обновятся после завершения; ручные правки сохранятся." : "При первом запуске реплики добавляются в документ по мере готовности. Повторный запуск обновляет машинный результат и сохраняет ручные правки."; color: dialog.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                    Button { objectName: "speechPlayPreview"; text: "▶ Прослушать реплику"; enabled: dialog.previewIndex >= 0 && dialog.speech.previewPlayable; onClicked: dialog.speech.playPreview(dialog.previewIndex) }
                }
            }
        }
        Label { visible: !dialog.speech.canAppend && destination.currentIndex === 0; text: "Оригинал этой онлайн-серии неизменяем. Выберите новый локальный документ."; wrapMode: Text.Wrap; color: dialog.colors.warning; Layout.fillWidth: true }
        Label { visible: !dialog.speech.engineReady; text: "Движок не найден. При запуске из исходников выполните: python scripts/build_whisper.py"; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.warning }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Аудио обрабатывается на компьютере"; color: dialog.colors.muted; Layout.fillWidth: true; Layout.minimumWidth: 0; elide: Text.ElideRight }
            Button { text: "Отменить результат"; visible: dialog.speech.canDiscard; onClicked: dialog.speech.discard() }
            Button { text: "Закрыть"; onClicked: dialog.close() }
            Button { text: "Остановить"; visible: dialog.speech.busy; enabled: !dialog.speech.stopping; onClicked: dialog.speech.stop() }
            Button {
                objectName: "speechStartButton"
                text: dialog.speech.previewRows.length ? "Распознать заново" : "Начать распознавание"
                highlighted: true
                visible: !dialog.speech.busy
                enabled: dialog.speech.engineReady && !!dialog.selectedModel.installed && backend.media.hasMedia && backend.media.duration > 0 && !backend.busy && (dialog.speech.canAppend || destination.currentIndex === 1)
                onClicked: dialog.startRecognition()
            }
        }
    }
}
