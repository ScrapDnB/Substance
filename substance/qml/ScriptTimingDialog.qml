import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "scriptTimingDialog"
    title: "Тайминг готового сценария"
    preferredWidth: 1280
    preferredHeight: 920
    minimumWidth: Math.min(820, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(700, Screen.desktopAvailableHeight - 80)
    modal: false
    readonly property var controller: backend.editorTools
    readonly property var models: backend.alignmentModels
    readonly property var model: models.models[modelChoice.currentIndex] || ({})
    function prepare() {
        scope.currentIndex = backend.selectionCount > 1 ? 0 : 1
        fromTime.text = "00:00:00.000"
        toTime.text = backend.media.duration > 0 ? new Date(backend.media.duration).toISOString().slice(11, 23) : ""
        open()
    }
    onClosed: controller.cancel()
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: "Найдите звучание уже написанных реплик"; font.pixelSize: 24; font.weight: Font.DemiBold }
        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "Текст должен совпадать с речью и быть на том же языке. Программа найдёт границы заданных слов; затем вы сможете прослушать и принять результат."; wrapMode: Text.Wrap; color: dialog.colors.muted }
        ToolCard {
            colors: dialog.colors
            Layout.fillWidth: true
            implicitHeight: setup.implicitHeight + 28
            ColumnLayout {
                id: setup
                anchors.fill: parent
                spacing: 8
                enabled: !dialog.controller.busy
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "1. Подготовьте текст и звук"; font.weight: Font.DemiBold; Layout.fillWidth: true }
                    Button { text: "Добавить сценарий…"; onClicked: dialog.models.importScript() }
                    Button { text: "Подключить медиа…"; onClicked: backend.openMedia() }
                }
                Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "Сценарий TXT: одна реплика на строку; допустимо «Персонаж: текст». Добавленные реплики можно отменить."; wrapMode: Text.Wrap; color: dialog.colors.muted; font.pixelSize: 11 }
                GridLayout {
                    Layout.fillWidth: true
                    columns: dialog.width < 1000 ? 4 : 6
                    Label { text: "Реплики" }
                    ComboBox { id: scope; Layout.fillWidth: true; model: ["Выделенные (" + backend.selectionCount + ")", "Весь документ (" + backend.count + ")"]; onActivated: dialog.controller.invalidate() }
                    Label { text: "Какой текст звучит" }
                    ComboBox { id: textChoice; Layout.fillWidth: true; model: ["Оригинал", "Рабочий текст / перевод"]; onActivated: dialog.controller.invalidate() }
                    Label { text: "Аудиодорожка" }
                    ComboBox { Layout.fillWidth: true; model: backend.media.audioTracks; currentIndex: Math.max(0, backend.media.activeAudio); onActivated: index => backend.media.setAudioTrack(index) }
                    Label { text: "Начало диапазона" }
                    DialogTextField { id: fromTime; objectName: "scriptStart"; text: "00:00:00.000"; Layout.fillWidth: true; onTextEdited: dialog.controller.invalidate() }
                    Label { text: "Конец диапазона" }
                    DialogTextField { id: toTime; objectName: "scriptEnd"; placeholderText: "00:05:00.000"; Layout.fillWidth: true; onTextEdited: dialog.controller.invalidate() }
                    Label { text: "Язык и модель" }
                    ComboBox { id: modelChoice; objectName: "scriptModel"; Layout.fillWidth: true; model: dialog.models.models; textRole: "title"; onActivated: dialog.controller.invalidate() }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.model.installed ? "Модель установлена. Анализ работает локально." : "Для выбранного языка сначала скачайте модель. Аудио останется на компьютере."; color: dialog.colors.muted; wrapMode: Text.Wrap }
                    Button { visible: !dialog.models.busy; text: dialog.model.installed ? "Скачать заново" : "Скачать модель"; onClicked: dialog.models.download(dialog.model.id) }
                    Button { visible: dialog.models.busy; text: "Остановить загрузку"; onClicked: dialog.models.cancel() }
                    Button { objectName: "scriptAnalyze"; text: "Найти время реплик"; enabled: dialog.model.installed && !dialog.models.busy && backend.media.hasMedia && backend.count > 0; onClicked: dialog.controller.analyze("forced", {selected: scope.currentIndex === 0, original: textChoice.currentIndex === 0, model: dialog.model.id, start: fromTime.text, end: toTime.text}) }
                }
                Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.models.status; visible: !!text; color: dialog.colors.muted; wrapMode: Text.Wrap }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.controller.stale ? "Текст, параметры или медиа изменились. Повторите анализ." : dialog.controller.status; wrapMode: Text.Wrap; color: dialog.controller.stale || dialog.controller.error ? dialog.colors.warning : dialog.colors.muted }
            ProgressBar { visible: dialog.controller.busy || dialog.models.busy; Layout.preferredWidth: 160; value: dialog.models.busy ? dialog.models.progress : dialog.controller.progress; indeterminate: value === 0 }
            Button { visible: dialog.controller.busy; text: "Остановить"; onClicked: dialog.controller.cancel() }
        }
        ToolReviewPane { Layout.fillWidth: true; Layout.fillHeight: true; colors: dialog.colors; controller: dialog.controller; timing: true; emptyDescription: "Выберите реплики и диапазон аудио. После анализа прослушайте предложения и отметьте те, которые нужно применить." }
        RowLayout {
            Layout.fillWidth: true
            Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "Прослушайте интервалы и отметьте нужные. Текст реплик сохраняется."; wrapMode: Text.Wrap; color: dialog.colors.muted }
            Button { text: "Закрыть"; onClicked: dialog.dismiss() }
            Button { objectName: "scriptApply"; text: "Применить выбранное (" + dialog.controller.summary.selected + ")"; enabled: dialog.controller.canApply; highlighted: true; onClicked: dialog.controller.apply() }
        }
    }
}
