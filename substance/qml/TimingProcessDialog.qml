import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "timingProcessDialog"
    title: "Обработать интервалы"
    preferredWidth: 1280
    preferredHeight: 900
    minimumWidth: Math.min(820, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(680, Screen.desktopAvailableHeight - 80)
    modal: false
    readonly property var controller: backend.editorTools
    function options() { return {selected: scope.currentIndex === 1, padding: padding.checked, lead: lead.value, tail: tail.value,
        bridge: bridge.checked, bridgeGap: gap.value, bias: bias.value, snapCuts: cuts.checked,
        startBefore: startBefore.value, startAfter: startAfter.value, endBefore: endBefore.value, endAfter: endAfter.value,
        frames: frames.checked, protectOverlap: protect.checked, trimOverlap: trim.checked, styles: styles.text, actors: actors.text, minimum: minimum.value} }
    function loadPreset(name) {
        let p = controller.timingPresets[name]
        if (!p) return
        padding.checked = p.padding !== false; bridge.checked = p.bridge !== false
        cuts.checked = p.snapCuts === true; frames.checked = p.frames === true; protect.checked = p.protectOverlap !== false
        trim.checked = p.trimOverlap === true
        lead.value = p.lead === undefined ? 100 : p.lead; tail.value = p.tail === undefined ? 200 : p.tail
        gap.value = p.bridgeGap === undefined ? 80 : p.bridgeGap; bias.currentIndex = p.bias === 0 ? 1 : p.bias === 50 ? 2 : 0
        startBefore.value = p.startBefore || 120; startAfter.value = p.startAfter || 120
        endBefore.value = p.endBefore || 120; endAfter.value = p.endAfter || 120
        styles.text = p.styles || ""; actors.text = p.actors || ""; minimum.value = p.minimum || 100
        controller.invalidate()
    }
    onClosed: controller.cancel()
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: "Доведите время реплик за один проход"; font.pixelSize: 24; font.weight: Font.DemiBold }
        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "Добавьте отступы, соедините близкие реплики и привяжите границы к кадрам. Ниже появятся варианты для сравнения и прослушивания."; wrapMode: Text.Wrap; color: dialog.colors.muted }
        ToolCard {
            Layout.fillWidth: true
            colors: dialog.colors
            implicitHeight: Math.min(setup.implicitHeight + 28, dialog.height * .39)
            ScrollView {
                id: settingsScroll
                anchors.fill: parent
                contentWidth: availableWidth
                clip: true
                ColumnLayout {
                    id: setup
                    width: settingsScroll.availableWidth
                    spacing: 8
                    enabled: !dialog.controller.busy
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "1. Настройте обработку"; font.weight: Font.DemiBold }
                        ComboBox { id: preset; Layout.fillWidth: true; model: ["Свои параметры"].concat(Object.keys(dialog.controller.timingPresets)); onActivated: dialog.loadPreset(currentText) }
                        ComboBox { id: scope; model: ["Весь документ", "Выделенные реплики"]; onActivated: dialog.controller.invalidate() }
                        Button { objectName: "timingProcessAnalyze"; text: "Подготовить результат"; enabled: backend.count > 0; onClicked: dialog.controller.analyze("retime", dialog.options()) }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        CheckBox { id: padding; text: "Отступы от речи"; checked: true; onClicked: dialog.controller.invalidate() }
                        Item { Layout.fillWidth: true }
                        Label { text: "До начала, мс" }
                        DialogSpinBox { id: lead; from: 0; to: 5000; value: 100; editable: true; onValueModified: dialog.controller.invalidate() }
                        Label { text: "После окончания, мс" }
                        DialogSpinBox { id: tail; from: 0; to: 5000; value: 200; editable: true; onValueModified: dialog.controller.invalidate() }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        CheckBox { id: bridge; text: "Закрыть паузы"; checked: true; onClicked: dialog.controller.invalidate() }
                        Label { text: "до, мс" }
                        DialogSpinBox { id: gap; from: 0; to: 2000; value: 80; editable: true; onValueModified: dialog.controller.invalidate() }
                        Label { text: "за счёт" }
                        ComboBox { id: bias; Layout.fillWidth: true; property int value: currentIndex === 0 ? 100 : currentIndex === 1 ? 0 : 50; model: ["Продления первой реплики", "Раннего начала второй", "Обеих реплик поровну"]; onActivated: dialog.controller.invalidate() }
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        CheckBox { id: cuts; text: "Привязать к склейкам"; onClicked: dialog.controller.invalidate() }
                        CheckBox { id: frames; text: "Округлить к кадрам"; onClicked: dialog.controller.invalidate() }
                        CheckBox { id: trim; text: "Сократить пересечения одного персонажа"; onClicked: { if (checked) protect.checked = false; dialog.controller.invalidate() } }
                    }
                    GridLayout {
                        visible: cuts.checked
                        Layout.fillWidth: true
                        columns: dialog.width < 1100 ? 4 : 8
                        Label { text: "Начало до, мс" }
                        DialogSpinBox { id: startBefore; from: 0; to: 2000; value: 120; editable: true; onValueModified: dialog.controller.invalidate() }
                        Label { text: "Начало после, мс" }
                        DialogSpinBox { id: startAfter; from: 0; to: 2000; value: 120; editable: true; onValueModified: dialog.controller.invalidate() }
                        Label { text: "Конец до, мс" }
                        DialogSpinBox { id: endBefore; from: 0; to: 2000; value: 120; editable: true; onValueModified: dialog.controller.invalidate() }
                        Label { text: "Конец после, мс" }
                        DialogSpinBox { id: endAfter; from: 0; to: 2000; value: 120; editable: true; onValueModified: dialog.controller.invalidate() }
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        CheckBox { id: protect; text: "Сохранить время одновременной речи"; checked: true; onClicked: { if (checked) trim.checked = false; dialog.controller.invalidate() } }
                        Label { text: "Минимум, мс"; height: minimum.height; verticalAlignment: Text.AlignVCenter }
                        DialogSpinBox { id: minimum; from: 1; to: 10000; value: 100; editable: true; onValueModified: dialog.controller.invalidate() }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Персонажи" }
                        DialogTextField { id: actors; Layout.fillWidth: true; placeholderText: "Все; или имена через запятую"; onTextEdited: dialog.controller.invalidate() }
                        Label { text: "Стили" }
                        DialogTextField { id: styles; Layout.fillWidth: true; placeholderText: "Все; или названия через запятую"; onTextEdited: dialog.controller.invalidate() }
                        DialogTextField { id: presetName; Layout.preferredWidth: 160; placeholderText: "Название профиля" }
                        Button { text: "Сохранить профиль"; onClicked: dialog.controller.saveTimingPreset(presetName.text, dialog.options()) }
                    }
                }
            }
        }
        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.controller.stale ? "Параметры или документ изменились. Подготовьте результат заново." : dialog.controller.status; wrapMode: Text.Wrap; color: dialog.controller.error || dialog.controller.stale ? dialog.colors.warning : dialog.colors.muted }
        ToolReviewPane { Layout.fillWidth: true; Layout.fillHeight: true; colors: dialog.colors; controller: dialog.controller; timing: true; emptyDescription: "Нажмите «Подготовить результат», затем сравните и прослушайте предложенные интервалы." }
        RowLayout {
            Layout.fillWidth: true
            Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "Изменения применяются одной отменяемой операцией"; color: dialog.colors.muted }
            Button { text: "Закрыть"; onClicked: dialog.dismiss() }
            Button { objectName: "timingProcessApply"; text: "Применить выбранное (" + dialog.controller.summary.selected + ")"; enabled: dialog.controller.canApply; highlighted: true; onClicked: dialog.controller.apply() }
        }
    }
}
