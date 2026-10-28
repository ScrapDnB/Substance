import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "semanticTimingDialog"
    title: "Сопоставление по смыслу"
    preferredWidth: 1280
    preferredHeight: 940
    minimumWidth: Math.min(820, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(700, Screen.desktopAvailableHeight - 80)
    modal: false
    readonly property var controller: backend.editorTools
    readonly property var speech: backend.transcription
    readonly property var models: backend.alignmentModels
    readonly property var selectedModel: speech.models[modelChoice.currentIndex] || ({})
    property bool reviewing: false
    readonly property bool ready: backend.count > 0 && backend.media.hasMedia && speech.engineReady
        && !!selectedModel.installed && models.semanticInstalled && !speech.busy && !models.busy
        && !controller.busy && !backend.busy && !backend.onlineSession.active
        && (scope.currentIndex !== 0 || backend.selectionCount > 0)
    function prepare() {
        reviewing = false
        scope.currentIndex = backend.selectionCount > 1 ? 0 : 1
        fromTime.text = "00:00:00.000"
        toTime.text = backend.media.duration > 0 ? new Date(backend.media.duration).toISOString().slice(11, 23) : ""
        let saved = speech.models.findIndex(m => m.id === speech.savedModel && m.installed)
        let installed = speech.models.findIndex(m => m.installed)
        modelChoice.currentIndex = saved >= 0 ? saved : installed >= 0 ? installed : 2
        open()
    }
    function runAnalysis() {
        controller.analyze("semantic", {selected: scope.currentIndex === 0,
            role: ["auto", "original", "translation"][roleChoice.currentIndex],
            language: speech.languages[audioLanguage.currentIndex].id,
            textLanguage: speech.languages[textLanguage.currentIndex].id,
            model: selectedModel.id, start: fromTime.text, end: toTime.text,
            mode: modeChoice.currentIndex === 0 ? "sentences" : "precise",
            width: lineWidth.value, maximum: maxDuration.value * 1000, cpu: cpuOnly.checked,
            stripScriptMarks: stripMarks.checked})
    }
    onClosed: controller.cancel()
    Connections { target: dialog.controller; function onAnalysisCompleted() { dialog.reviewing = true } }
    ScrollView {
        id: body
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            width: body.availableWidth
            height: Math.max(body.availableHeight, implicitHeight)
            spacing: 10
            Label { text: "Предложения перевода — в границы речи"; font.pixelSize: 24; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
            Label {
                Layout.fillWidth: true
                text: "Найдём предложения в видео по смыслу, даже если перевод на другом языке. Старые строки и таймкоды не ограничивают поиск. Текст распределится между оригиналом и переводом при применении."
                color: dialog.colors.muted
                wrapMode: Text.Wrap
            }
            ToolCard {
                colors: dialog.colors
                Layout.fillWidth: true
                implicitHeight: setup.implicitHeight + 28
                ColumnLayout {
                    id: setup
                    anchors.fill: parent
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "1. Текст и речь"; font.weight: Font.DemiBold; Layout.fillWidth: true }
                        Button { visible: dialog.reviewing; text: "Настройки"; enabled: !dialog.controller.busy; onClicked: dialog.reviewing = false }
                        Button { text: dialog.controller.analysisReady ? "Повторить анализ" : "Сопоставить"; objectName: "semanticAnalyze"; enabled: dialog.ready; onClicked: dialog.runAnalysis() }
                    }
                    GridLayout {
                        visible: !dialog.reviewing
                        enabled: !dialog.controller.busy
                        Layout.fillWidth: true
                        columns: dialog.width >= 1100 ? 6 : 4
                        Label { text: "Режим" }
                        ComboBox { id: modeChoice; objectName: "semanticMode"; Layout.fillWidth: true; model: ["По предложениям", "Точный"]; onActivated: dialog.controller.invalidate() }
                        Label { text: "Реплики" }
                        ComboBox { id: scope; objectName: "semanticScope"; Layout.fillWidth: true; model: ["Выделенные (" + backend.selectionCount + ")", "Весь документ (" + backend.count + ")"]; onActivated: dialog.controller.invalidate() }
                        Label { text: "Если одна колонка" }
                        ComboBox { id: roleChoice; objectName: "semanticRole"; Layout.fillWidth: true; model: ["Определить по языкам", "Загружен оригинал", "Загружен перевод"]; onActivated: dialog.controller.invalidate() }
                        Label { text: "Аудиодорожка" }
                        ComboBox { objectName: "semanticAudioTrack"; Layout.fillWidth: true; model: backend.media.audioTracks.length ? backend.media.audioTracks : ["Основная аудиодорожка"]; currentIndex: Math.max(0, backend.media.activeAudio); onActivated: index => { backend.media.setAudioTrack(index); dialog.controller.invalidate() } }
                        Label { text: "Язык речи в видео" }
                        ComboBox { id: audioLanguage; objectName: "semanticAudioLanguage"; Layout.fillWidth: true; model: dialog.speech.languages; textRole: "title"; onActivated: dialog.controller.invalidate() }
                        Label { text: "Язык текста / перевода" }
                        ComboBox { id: textLanguage; objectName: "semanticTextLanguage"; Layout.fillWidth: true; model: dialog.speech.languages; textRole: "title"; onActivated: dialog.controller.invalidate() }
                        Label { text: "Знаков в строке"; enabled: modeChoice.currentIndex === 1 }
                        DialogSpinBox { id: lineWidth; objectName: "semanticLineWidth"; enabled: modeChoice.currentIndex === 1; from: 20; to: 80; value: 42; editable: true; onValueModified: dialog.controller.invalidate() }
                        Label { text: "Начало аудио" }
                        DialogTextField { id: fromTime; objectName: "semanticStart"; text: "00:00:00.000"; Layout.fillWidth: true; onTextEdited: dialog.controller.invalidate() }
                        Label { text: "Конец аудио" }
                        DialogTextField { id: toTime; objectName: "semanticEnd"; placeholderText: "00:05:00.000"; Layout.fillWidth: true; onTextEdited: dialog.controller.invalidate() }
                        Label { text: "Длительность, с"; enabled: modeChoice.currentIndex === 1 }
                        DialogSpinBox { id: maxDuration; objectName: "semanticMaxDuration"; enabled: modeChoice.currentIndex === 1; from: 2; to: 10; value: 6; editable: true; onValueModified: dialog.controller.invalidate() }
                    }
                    Label { visible: !dialog.reviewing; Layout.fillWidth: true; text: modeChoice.currentIndex === 0 ? "Быстрее: сравниваем смысл целых предложений и переносим перевод в границы оригинальной речи. Предложения сохраняются целиком, без разбиения на короткие субтитры." : "Подробно сравниваем сочетания фраз и их части, затем делим текст на субтитры по звучащим словам. Этот режим требует больше времени."; color: dialog.colors.muted; wrapMode: Text.Wrap; font.pixelSize: 11 }
                    Label { visible: !dialog.reviewing; Layout.fillWidth: true; text: "При одном языке текст считается оригиналом, при разных — переводом. Этот выбор можно изменить. Если оригинала нет, в его колонке появится распознанная речь; ваш текст останется переводом."; color: dialog.colors.muted; wrapMode: Text.Wrap; font.pixelSize: 11 }
                    Flow {
                        visible: !dialog.reviewing
                        Layout.fillWidth: true
                        spacing: 6
                        enabled: !dialog.controller.busy
                        Button { text: "Добавить текст…"; onClicked: dialog.models.importScript("semantic") }
                        Button { text: "Подключить медиа…"; onClicked: backend.openMedia() }
                        ComboBox { id: modelChoice; objectName: "semanticSpeechModel"; width: Math.min(310, parent.width); model: dialog.speech.models; textRole: "title"; currentIndex: 2; enabled: !dialog.speech.busy; onActivated: dialog.controller.invalidate() }
                        Button { text: "Скачать модель речи"; visible: !dialog.selectedModel.installed; enabled: !dialog.speech.busy; onClicked: dialog.speech.download(dialog.selectedModel.id) }
                        Button { text: "Остановить загрузку речи"; visible: dialog.speech.downloading; onClicked: dialog.speech.stop() }
                        Button { objectName: "semanticDownload"; text: "Скачать модель смысла (" + Math.round(dialog.models.semanticBytes / 1048576) + " МБ)"; visible: !dialog.models.semanticInstalled; enabled: !dialog.models.busy; onClicked: dialog.models.downloadSemantic() }
                        Button { visible: dialog.models.busy; text: "Остановить загрузку"; onClicked: dialog.models.cancel() }
                        CheckBox { id: cpuOnly; objectName: "semanticCpu"; text: "Только процессор"; onClicked: dialog.controller.invalidate() }
                        CheckBox { id: stripMarks; objectName: "semanticStripMarks"; text: "Убрать метки / и //(таймкод)"; checked: true; onClicked: dialog.controller.invalidate() }
                    }
                    Label { Layout.fillWidth: true; visible: !dialog.reviewing; text: "Анализ работает локально. Неоднозначные варианты можно выбрать и применить: они отмечены предупреждениями. Текст без соответствия речи сохраняется с исходным временем."; color: dialog.colors.muted; wrapMode: Text.Wrap; font.pixelSize: 11 }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.controller.stale ? "Текст, настройки или медиа изменились. Повторите анализ." : dialog.models.busy ? dialog.models.status : dialog.speech.downloading || dialog.speech.error ? dialog.speech.status : dialog.controller.status || dialog.models.status || (!dialog.speech.engineReady ? "Движок распознавания недоступен. Обновите сборку приложения." : ""); wrapMode: Text.Wrap; color: dialog.controller.error || dialog.controller.stale || dialog.speech.error ? dialog.colors.warning : dialog.colors.muted }
                ProgressBar { visible: dialog.controller.busy || dialog.models.busy || dialog.speech.downloading; Layout.preferredWidth: 120; value: dialog.models.busy ? dialog.models.progress : dialog.speech.downloading ? dialog.speech.progress : dialog.controller.progress; indeterminate: value === 0 }
                Button { visible: dialog.controller.busy; text: "Остановить"; onClicked: dialog.controller.cancel() }
            }
            ToolReviewPane {
                objectName: "semanticReview"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 300
                Layout.preferredHeight: 400
                colors: dialog.colors
                controller: dialog.controller
                timing: true
                bilingual: true
                emptyTitle: "Предпросмотр новых субтитров"
                emptyDescription: "После анализа проверьте разбиение, обе колонки текста и звучание. Выберите подходящие изменения; исходный документ изменится только при применении."
            }
        }
    }
    footer: Pane {
        padding: 12
        background: null
        contentItem: RowLayout {
            Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "Выбрано: " + dialog.controller.summary.selected + " · Все изменения — одной отменой"; color: dialog.colors.muted; wrapMode: Text.Wrap }
            Button { text: "Закрыть"; onClicked: dialog.dismiss() }
            Button { objectName: "semanticApply"; text: "Применить выбранное"; highlighted: true; enabled: dialog.controller.canApply; onClicked: dialog.controller.apply() }
        }
    }
}
