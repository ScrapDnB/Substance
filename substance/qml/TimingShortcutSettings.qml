import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

DialogSection {
    id: section
    required property var colors
    title: "Управление границами с клавиатуры"
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label {
            text: "← сдвигает раньше, → — позже. Команды меняют текущую реплику, в том числе при вводе текста. Shift включает точный шаг."
            color: section.colors.muted
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
        Repeater {
            model: [{key: "step", title: "Обычный шаг"}, {key: "fineStep", title: "Точный шаг · с Shift"}]
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                Label { text: modelData.title; Layout.fillWidth: true; wrapMode: Text.Wrap }
                DialogSpinBox {
                    objectName: "timing_" + modelData.key
                    Layout.preferredWidth: 110
                    from: 1; to: 5000; editable: true
                    value: backend.timingSteps[modelData.key]
                    onValueModified: backend.setTimingStep(modelData.key, value)
                    Accessible.name: modelData.title
                }
                Label { text: "мс"; color: section.colors.muted }
            }
        }
        ColumnLayout {
            spacing: 6
            Layout.fillWidth: true
            RowLayout {
                spacing: 8
                Layout.fillWidth: true
                Label { text: "Сдвиг"; color: section.colors.muted; Layout.fillWidth: true }
                Label { text: "Обычный шаг"; color: section.colors.muted; Layout.preferredWidth: 130; horizontalAlignment: Text.AlignHCenter }
                Label { text: "Точный шаг"; color: section.colors.muted; Layout.preferredWidth: 130; horizontalAlignment: Text.AlignHCenter }
            }
            Repeater {
                model: [
                    {key: "nudgeStartBack", title: "Начало ←"},
                    {key: "nudgeStartForward", title: "Начало →"},
                    {key: "nudgeEndBack", title: "Конец ←"},
                    {key: "nudgeEndForward", title: "Конец →"},
                    {key: "nudgeBothBack", title: "Вся реплика ←"},
                    {key: "nudgeBothForward", title: "Вся реплика →"}
                ]
                delegate: RowLayout {
                    id: commandRow
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 8
                    Label { text: commandRow.modelData.title; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    Repeater {
                        model: ["", "Fine"]
                        Button {
                            required property string modelData
                            readonly property string actionKey: commandRow.modelData.key + modelData
                            objectName: "timingShortcut_" + actionKey
                            Layout.preferredWidth: 130
                            text: { let revision = backend.shortcuts; return backend.shortcutLabel(actionKey) }
                            Accessible.name: commandRow.modelData.title + (modelData ? ", точный шаг: " : ", обычный шаг: ") + text
                            onClicked: backend.editShortcutDialog(actionKey)
                        }
                    }
                }
            }
        }
        Label {
            text: "Нажмите сочетание, чтобы изменить его. У нулевой отметки и соседней границы сдвиг останавливается. Сдвиг всей реплики сохраняет её длительность. Отмена — «Отменить»."
            color: section.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 11
        }
        Label {
            text: { let revision = backend.shortcuts; return "Покадровый просмотр: " + backend.shortcutLabel("frameBack") + " / " + backend.shortcutLabel("frameForward") }
            color: section.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 11
        }
        Button {
            objectName: "resetTimingControls"
            text: "Восстановить шаги и сочетания тайминга"
            onClicked: backend.resetTimingControls()
        }
    }
}
