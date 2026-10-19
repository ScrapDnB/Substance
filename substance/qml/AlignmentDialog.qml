import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "alignmentDialog"
    title: "Уточнить речь"
    preferredWidth: 1280
    preferredHeight: 900
    minimumWidth: Math.min(800, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(680, Screen.desktopAvailableHeight - 80)
    modal: false
    readonly property var tools: backend.editorTools
    readonly property var speech: backend.transcription
    property int stage: 0
    readonly property var selectedModel: speech.models[modelChoice.currentIndex] || ({id: "", title: "", installed: false, bytes: 0})
    readonly property bool ready: backend.count > 0 && backend.media.hasMedia && speech.engineReady && selectedModel.installed && !speech.busy && !tools.busy && !backend.busy && (scopeChoice.currentIndex !== 1 || backend.selectionCount > 0)
    function runAnalysis() {
        tools.analyze("align", {scope: scopeChoice.currentIndex === 0 ? "current" : "all", selected: scopeChoice.currentIndex === 1,
            model: selectedModel.id, language: speech.languages[languageChoice.currentIndex].id,
            maxShift: searchWindow.value, edges: ["both", "start", "end"][edgesChoice.currentIndex],
            lead: leadTime.value, tail: tailTime.value, cps: readingSpeed.value, cpu: cpuOnly.checked})
    }
    onOpened: {
        stage = tools.analysisReady ? 1 : 0
        advanced.checked = false
        if (!tools.busy) {
            scopeChoice.currentIndex = backend.selectionCount > 1 ? 1 : 0
            let models = speech.models
            let saved = models.findIndex(m => m.id === speech.savedModel && m.installed)
            let installed = models.findIndex(m => m.installed)
            modelChoice.currentIndex = saved >= 0 ? saved : installed >= 0 ? installed : 2
            let lang = speech.languages.findIndex(l => l.id === speech.savedLanguage)
            languageChoice.currentIndex = Math.max(0, lang)
        }
    }
    onClosed: tools.cancel()
    Connections {
        target: dialog.tools
        function onAnalysisCompleted() { dialog.stage = 1; advanced.checked = false }
    }
    ScrollView {
        id: bodyScroll
        objectName: "alignmentDialogScroll"
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            width: bodyScroll.availableWidth
            height: Math.max(bodyScroll.availableHeight, implicitHeight)
            spacing: 12
            Label { text: "Уточните время по речи"; font.pixelSize: 24; font.weight: Font.DemiBold }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: "Найдите точные границы звучащих фраз, сравните время и прослушайте результат. Текст реплик сохранится."
                color: dialog.colors.muted
            }
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
                        Label { text: "1. Найдите границы речи"; font.weight: Font.DemiBold; Layout.fillWidth: true }
                        Button { objectName: "alignmentBack"; visible: dialog.stage === 1; text: "Настройки"; onClicked: dialog.stage = 0 }
                        Button { id: advanced; objectName: "alignmentAdvancedToggle"; visible: dialog.stage === 0; text: checked ? "Скрыть параметры" : "Дополнительные настройки"; checkable: true; enabled: !dialog.tools.busy }
                        Button { objectName: "alignmentAnalyze"; text: dialog.tools.analysisReady ? "Повторить анализ" : "Найти границы речи"; visible: !dialog.tools.busy; enabled: dialog.ready; onClicked: dialog.runAnalysis() }
                        Button { text: "Остановить"; visible: dialog.tools.busy; onClicked: dialog.tools.cancel() }
                    }
                    GridLayout {
                        objectName: "alignmentSetup"
                        visible: dialog.stage === 0
                        Layout.fillWidth: true
                        columns: dialog.width >= 1100 ? 6 : 4
                        columnSpacing: 10
                        rowSpacing: 10
                        enabled: !dialog.tools.busy
                        Label { text: "Реплики" }
                        ComboBox {
                            id: scopeChoice
                            objectName: "alignmentScope"
                            Layout.fillWidth: true
                            model: ["Текущая реплика", "Выделенные (" + backend.selectionCount + ")", "Весь документ (" + backend.count + ")"]
                            onActivated: dialog.tools.invalidate()
                        }
                        Label { text: "Аудиодорожка" }
                        ComboBox {
                            objectName: "alignmentAudioTrack"
                            Layout.fillWidth: true
                            model: backend.media.audioTracks.length ? backend.media.audioTracks : ["Основная аудиодорожка"]
                            currentIndex: Math.max(0, backend.media.activeAudio)
                            onActivated: index => { backend.media.setAudioTrack(index); dialog.tools.invalidate() }
                        }
                        Label { text: "Язык речи" }
                        ComboBox { id: languageChoice; objectName: "alignmentLanguage"; Layout.fillWidth: true; model: dialog.speech.languages; textRole: "title"; onActivated: dialog.tools.invalidate() }
                    }
                    RowLayout {
                        visible: dialog.stage === 0
                        Layout.fillWidth: true
                        enabled: !dialog.tools.busy
                        ComboBox {
                            id: edgesChoice
                            objectName: "alignmentEdges"
                            Layout.fillWidth: true
                            model: ["Уточнить начало и конец", "Уточнить только начало", "Уточнить только конец"]
                            onActivated: dialog.tools.invalidate()
                        }
                        Label { text: "Искать рядом: " + (searchWindow.value / 1000).toLocaleString(Qt.locale(), 'f', 1) + " с" }
                        AppSlider { id: searchWindow; objectName: "alignmentSearchWindow"; Layout.preferredWidth: 150; from: 100; to: 5000; stepSize: 100; value: 1000; onMoved: dialog.tools.invalidate(); Accessible.name: "Насколько далеко искать речь от текущего времени" }
                    }
                    ScrollView {
                        id: advancedScroll
                        visible: advanced.checked && dialog.stage === 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(dialog.height < 780 ? 90 : 165, advancedOptions.implicitHeight)
                        Layout.minimumHeight: 0
                        Layout.maximumHeight: Layout.preferredHeight
                        clip: true
                        contentWidth: availableWidth
                        ColumnLayout {
                            id: advancedOptions
                            width: advancedScroll.availableWidth
                            spacing: 8
                            GridLayout {
                                Layout.fillWidth: true
                                columns: 4
                                columnSpacing: 10
                                enabled: !dialog.tools.busy
                                Label { text: "Модель" }
                                ComboBox { id: modelChoice; objectName: "alignmentModel"; Layout.fillWidth: true; model: dialog.speech.models; textRole: "title"; currentIndex: 2; enabled: !dialog.speech.busy; onActivated: dialog.tools.invalidate() }
                                Label { text: "Показать до речи, мс" }
                                DialogSpinBox { id: leadTime; from: 0; to: 1000; stepSize: 20; value: 0; editable: true; onValueModified: dialog.tools.invalidate() }
                                Label { text: "Оставить после, мс" }
                                DialogSpinBox { id: tailTime; from: 0; to: 2000; stepSize: 20; value: 120; editable: true; onValueModified: dialog.tools.invalidate() }
                                Label { text: "Скорость чтения, зн/с" }
                                DialogSpinBox { id: readingSpeed; from: 8; to: 40; value: 17; editable: true; onValueModified: dialog.tools.invalidate() }
                            }
                            CheckBox { id: cpuOnly; objectName: "alignmentCpu"; text: "Использовать только процессор"; enabled: !dialog.tools.busy; onClicked: dialog.tools.invalidate() }
                            Label { text: "Для перевода выберите язык оригинального аудио. Обычно достаточно поиска в пределах 1 секунды; неоднозначные совпадения нужно прослушать."; color: dialog.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { visible: !dialog.speech.engineReady; text: "При запуске из исходников выполните scripts/build_whisper.py для сборки движка распознавания."; color: dialog.colors.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            wrapMode: Text.Wrap
                            text: !backend.media.hasMedia ? "Сначала откройте видео или аудио." : dialog.selectedModel.installed ? backend.media.name + " · Модель: " + dialog.selectedModel.title : "Скачайте модель один раз (" + Math.round(dialog.selectedModel.bytes / 1048576) + " МБ). Аудио обрабатывается на компьютере."
                            color: !backend.media.hasMedia || !dialog.selectedModel.installed ? dialog.colors.warning : dialog.colors.muted
                        }
                        Button { text: "Открыть файл…"; visible: !backend.media.hasMedia && dialog.stage === 0; enabled: !dialog.tools.busy; onClicked: backend.openMedia() }
                        Button { objectName: "alignmentDownload"; visible: !dialog.selectedModel.installed; text: "Скачать модель"; enabled: !dialog.speech.busy && !dialog.tools.busy; onClicked: dialog.speech.download(dialog.selectedModel.id) }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Label {
                    objectName: "alignmentStatus"
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: dialog.speech.downloading ? dialog.speech.status : dialog.tools.stale ? "Документ, аудио или настройки изменились. Повторите анализ." : dialog.tools.status || (!dialog.speech.engineReady ? "Движок распознавания отсутствует. Обновите сборку приложения." : "После анализа здесь появятся предложенные границы реплик.")
                    color: dialog.tools.error || dialog.tools.stale || dialog.speech.error || !dialog.speech.engineReady ? dialog.colors.warning : dialog.colors.muted
                }
                ProgressBar { visible: dialog.tools.busy || dialog.speech.downloading; Layout.preferredWidth: 160; value: dialog.tools.busy ? dialog.tools.progress : dialog.speech.progress; indeterminate: value === 0 }
            }
            ToolReviewPane {
                objectName: "alignmentResults"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 210
                Layout.preferredHeight: 210
                colors: dialog.colors
                controller: dialog.tools
                timing: true
                emptyTitle: "Превью границ речи"
                emptyDescription: "Запустите анализ. Здесь появятся исходное и предложенное время, текст реплики и две звуковые волны для сравнения."
            }
        }
    }
    footer: Pane {
        padding: 16
        leftPadding: 20
        rightPadding: 20
        topPadding: 8
        background: null
        contentItem: RowLayout {
            objectName: "alignmentDialogActions"
            Label { text: "Выбрано: " + dialog.tools.summary.selected + " · Прослушать: " + dialog.tools.summary.review + " · Изменения можно отменить"; color: dialog.colors.muted; elide: Text.ElideRight; Layout.minimumWidth: 0; Layout.fillWidth: true }
            Button { text: "Закрыть"; onClicked: dialog.dismiss() }
            Button { objectName: "alignmentApply"; text: "Применить выбранное (" + dialog.tools.summary.selected + ")"; highlighted: true; enabled: dialog.tools.canApply; onClicked: { if (dialog.tools.apply()) dialog.dismiss() } }
        }
    }
}
