import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "editorToolsDialog"
    preferredWidth: 1280
    preferredHeight: 900
    minimumWidth: Math.min(800, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(660, Screen.desktopAvailableHeight - 80)
    modal: false
    property string kind: "checks"
    readonly property var tools: backend.editorTools
    readonly property bool reflow: ["balance", "split", "merge"].indexOf(kind) >= 0
    readonly property bool scenes: kind === "scenes"
    property var qualityOptions: ({})
    function qualityValues() {
        return Object.assign({}, qualityOptions, {cps: qualityCps.value, width: lineWidth.value,
            minimum: minimum.value, maximum: maximum.value, gap: gap.value,
            readingSpeed: checkSpeed.checked, lineLength: checkLength.checked, lineCount: checkLines.checked,
            lineCountLimit: lineCount.value, overlaps: checkOverlaps.checked})
    }
    function loadQuality(name) {
        backend.qualityProfiles.select(name)
        let p = backend.qualityProfiles.profile
        qualityOptions = p
        qualityCps.value = p.cps; lineWidth.value = p.width; minimum.value = p.minimum; maximum.value = p.maximum; gap.value = p.gap
        checkSpeed.checked = p.readingSpeed; checkLength.checked = p.lineLength; checkLines.checked = p.lineCount
        checkOverlaps.checked = p.overlaps; lineCount.value = p.lineCountLimit
        tools.invalidate()
    }
    title: scenes ? "Смены планов" : reflow ? "Переносы и разбиения" : "Проверить и исправить"
    function prepare(value) { kind = value; advanced.checked = false; if (kind === "checks") { qualityChoice.currentIndex = 0; loadQuality(backend.qualityProfiles.names[0]) }; open() }
    function analyze() {
        tools.analyze(kind, {selected: scope.currentIndex === 1, width: lineWidth.value,
            minimum: minimum.value, maximum: maximum.value, gap: gap.value, cps: backend.cpsLimit,
            spaces: spaces.checked, punctuation: punctuation.checked, timing: timing.checked,
            threshold: threshold.value, profile: kind === "checks" ? qualityValues() : null})
    }
    onClosed: tools.cancel()
    ColumnLayout {
        anchors.fill: parent
        spacing: 14
        Label { text: dialog.title; font.pixelSize: 24; font.weight: Font.DemiBold }
        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            color: dialog.colors.muted
            text: dialog.scenes ? "Найдите монтажные склейки в видео и проверьте маркеры перед применением."
                : dialog.reflow ? "Настройте длину строк, сравните варианты и примените подходящие изменения."
                : "Найдите ошибки в тексте и времени реплик. Проверьте предлагаемые исправления перед применением."
        }
        ToolCard {
            colors: dialog.colors
            Layout.fillWidth: true
            implicitHeight: Math.min(setup.implicitHeight + 28, dialog.height * .34)
            ScrollView {
                id: setupScroll
                anchors.fill: parent
                contentWidth: availableWidth
                clip: true
            ColumnLayout {
                id: setup
                width: setupScroll.availableWidth
                spacing: 10
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: dialog.scenes ? "1. Найдите смены планов" : "1. Настройте проверку"; font.weight: Font.DemiBold; Layout.fillWidth: true }
                    Button {
                        id: advanced
                        objectName: "toolsAdvancedToggle"
                        visible: !dialog.scenes
                        text: checked ? "Скрыть параметры" : "Дополнительные настройки"
                        checkable: true
                        enabled: !dialog.tools.busy
                    }
                    Button {
                        objectName: "analyzeToolsButton"
                        text: dialog.tools.analysisReady ? "Повторить анализ" : dialog.scenes ? "Найти склейки" : dialog.reflow ? "Подготовить варианты" : "Проверить документ"
                        enabled: !dialog.tools.busy && !backend.busy && (dialog.scenes || (backend.count > 0 && (scope.currentIndex === 0 || backend.selectionCount > 0)))
                        visible: !dialog.tools.busy
                        onClicked: dialog.analyze()
                    }
                    Button { text: "Остановить"; visible: dialog.tools.busy; onClicked: dialog.tools.cancel() }
                }
                RowLayout {
                    visible: !dialog.scenes
                    Layout.fillWidth: true
                    enabled: !dialog.tools.busy
                    Label { text: "Область" }
                    ComboBox { id: scope; objectName: "toolsScope"; model: ["Весь документ", "Выделенные реплики (" + backend.selectionCount + ")"]; Layout.preferredWidth: 220; onActivated: dialog.tools.invalidate() }
                    Label { visible: dialog.reflow; text: "Действие" }
                    ComboBox {
                        objectName: "toolsOperation"
                        visible: dialog.reflow
                        model: ["Сбалансировать строки", "Разделить длинные реплики", "Объединить короткие реплики"]
                        currentIndex: dialog.kind === "split" ? 1 : dialog.kind === "merge" ? 2 : 0
                        onActivated: index => dialog.tools.open(["balance", "split", "merge"][index])
                        Layout.fillWidth: true
                    }
                    Item { visible: !dialog.reflow; Layout.fillWidth: true }
                }
                RowLayout {
                    visible: dialog.kind === "checks"
                    Layout.fillWidth: true
                    enabled: !dialog.tools.busy
                    Label { text: "Профиль проверки" }
                    ComboBox { id: qualityChoice; objectName: "qualityProfileChoice"; Layout.fillWidth: true; Layout.minimumWidth: 0; model: backend.qualityProfiles.names; onActivated: dialog.loadQuality(currentText) }
                    Button { id: manageQuality; text: "Свой профиль…"; checkable: true }
                    Button { objectName: "qualityReport"; text: "Сохранить отчёт…"; onClicked: backend.qualityProfiles.exportReport(dialog.qualityValues()) }
                }
                RowLayout {
                    visible: dialog.kind === "checks" && manageQuality.checked
                    Layout.fillWidth: true
                    DialogTextField { id: qualityName; Layout.fillWidth: true; placeholderText: "Название своего профиля" }
                    Button { text: "Сохранить профиль"; onClicked: backend.qualityProfiles.save(qualityName.text, dialog.qualityValues()) }
                    Button { text: "Удалить профиль"; visible: qualityChoice.currentIndex > 1; onClicked: { backend.qualityProfiles.remove(qualityChoice.currentText); qualityChoice.currentIndex = 0; dialog.loadQuality(backend.qualityProfiles.names[0]) } }
                }
                Flow {
                    visible: dialog.kind === "checks"
                    Layout.fillWidth: true
                    spacing: 8
                    CheckBox { id: checkSpeed; text: "Скорость чтения"; checked: true; onClicked: dialog.tools.invalidate() }
                    DialogSpinBox { id: qualityCps; from: 1; to: 100; value: 20; editable: true; onValueModified: dialog.tools.invalidate(); Accessible.name: "Символов в секунду" }
                    Label { text: "зн/с"; height: qualityCps.height; verticalAlignment: Text.AlignVCenter }
                    CheckBox { id: checkLength; text: "Длина строк"; checked: true; onClicked: dialog.tools.invalidate() }
                    CheckBox { id: checkLines; text: "Количество строк"; checked: true; onClicked: dialog.tools.invalidate() }
                    DialogSpinBox { id: lineCount; from: 1; to: 10; value: 2; editable: true; onValueModified: dialog.tools.invalidate(); Accessible.name: "Максимум строк" }
                    CheckBox { id: checkOverlaps; text: "Пересечения"; checked: true; onClicked: dialog.tools.invalidate() }
                }
                Label { visible: dialog.kind === "checks" && !!text; Layout.fillWidth: true; text: backend.qualityProfiles.status; wrapMode: Text.Wrap; color: dialog.colors.muted }
                Flow {
                    visible: !dialog.reflow && !dialog.scenes
                    Layout.fillWidth: true
                    spacing: 12
                    enabled: !dialog.tools.busy
                    CheckBox { id: spaces; text: "Лишние пробелы"; checked: true; onClicked: dialog.tools.invalidate() }
                    CheckBox { id: punctuation; text: "Пунктуация"; checked: true; onClicked: dialog.tools.invalidate() }
                    CheckBox { id: timing; text: "Время и интервалы"; checked: true; onClicked: dialog.tools.invalidate() }
                }
                GridLayout {
                    visible: advanced.checked && !dialog.scenes
                    enabled: !dialog.tools.busy
                    Layout.fillWidth: true
                    columns: dialog.width < 1050 ? 4 : 8
                    columnSpacing: 10
                    Label { text: "Символов в строке" }
                    DialogSpinBox { id: lineWidth; objectName: "toolsLineWidth"; enabled: dialog.reflow || checkLength.checked; from: dialog.reflow ? 20 : 10; to: dialog.reflow ? 100 : 200; value: backend.lineLimit; editable: true; onValueModified: dialog.tools.invalidate() }
                    Label { text: "Мин. время, мс" }
                    DialogSpinBox { id: minimum; from: 100; to: 20000; stepSize: 100; value: 1000; editable: true; onValueModified: dialog.tools.invalidate() }
                    Label { text: "Макс. время, мс" }
                    DialogSpinBox { id: maximum; from: 100; to: 60000; stepSize: 100; value: 6000; editable: true; onValueModified: dialog.tools.invalidate() }
                    Label { text: "Промежуток, мс" }
                    DialogSpinBox { id: gap; from: 0; to: 2000; value: 80; editable: true; onValueModified: dialog.tools.invalidate() }
                }
                Label {
                    visible: dialog.reflow
                    Layout.fillWidth: true
                    text: dialog.kind === "balance" ? "Переносы меняются внутри реплики; её время сохраняется. Лимит: " + lineWidth.value + " символа в строке."
                        : dialog.kind === "split" ? "Длинные реплики станут несколькими короткими. Время делится приблизительно — прослушайте результат."
                        : "Соседние короткие реплики одного персонажа объединятся, если промежуток не больше " + gap.value + " мс."
                    color: dialog.colors.muted
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    visible: dialog.scenes
                    enabled: !dialog.tools.busy
                    Layout.fillWidth: true
                    Label { text: "Чувствительность, %" }
                    DialogSpinBox { id: threshold; from: 1; to: 100; value: 10; editable: true; onValueModified: dialog.tools.invalidate() }
                    Label { text: "Меньше — больше маркеров"; color: dialog.colors.muted; Layout.fillWidth: true }
                    Button { text: "◀ Склейка"; onClicked: dialog.tools.seekScene(-1) }
                    Button { text: "Склейка ▶"; onClicked: dialog.tools.seekScene(1) }
                    Button { objectName: "toggleSceneButton"; text: "Добавить / убрать здесь"; onClicked: dialog.tools.toggleScene(backend.media.position) }
                }
            }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label {
                objectName: "toolsStatus"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: dialog.tools.stale ? "Документ или настройки изменились. Повторите анализ перед применением." : dialog.tools.status || "После анализа здесь появятся предложения."
                color: dialog.tools.stale || dialog.tools.error ? dialog.colors.warning : dialog.colors.muted
                wrapMode: Text.Wrap
            }
            ProgressBar { visible: dialog.tools.busy; Layout.preferredWidth: 160; value: dialog.tools.progress; indeterminate: value === 0 }
        }
        ToolReviewPane {
            objectName: "toolsReviewPane"
            visible: !dialog.scenes
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 230
            colors: dialog.colors
            controller: dialog.tools
            emptyTitle: dialog.reflow ? "Превью переносов и реплик" : "Превью исправлений"
            emptyDescription: dialog.reflow ? "Подготовьте варианты. Здесь можно сравнить исходный текст с новыми строками и временем каждой получившейся реплики." : "Запустите проверку. Выберите замечание слева, чтобы увидеть текст и время до и после исправления."
        }
        ListView {
            objectName: "sceneMarkerList"
            visible: dialog.scenes
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: dialog.tools.sceneRows
            ScrollBar.vertical: ScrollBar {}
            delegate: ItemDelegate {
                required property var modelData
                width: ListView.view.width
                text: modelData.label + "   ·   Перейти к склейке"
                onClicked: backend.media.seek(modelData.time)
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: dialog.scenes ? "Изменения можно отменить" : "Выбрано: " + dialog.tools.summary.selected + " · Изменения можно отменить"; color: dialog.colors.muted; Layout.fillWidth: true; Layout.minimumWidth: 0; elide: Text.ElideRight }
            Button { text: "Закрыть"; onClicked: dialog.dismiss() }
            Button { objectName: "applyToolsButton"; text: dialog.scenes ? "Применить маркеры" : "Применить выбранное (" + dialog.tools.summary.selected + ")"; highlighted: true; enabled: dialog.tools.canApply; onClicked: dialog.tools.apply() }
        }
    }
}
