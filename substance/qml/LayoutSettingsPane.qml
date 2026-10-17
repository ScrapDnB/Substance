import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: pane
    required property string mode
    required property var colors
    readonly property var config: backend.appearance[mode]
    readonly property bool timing: mode === "timing"
    clip: true
    contentWidth: availableWidth
    ColumnLayout {
        width: pane.availableWidth
        spacing: 18
        WorkspacePreview { colors: pane.colors; mode: pane.mode; Layout.fillWidth: true }
        Label { text: "Схема обновляется вместе с рабочим окном. Настройки " + (pane.timing ? "перевода" : "тайминга") + " сохраняются отдельно."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: pane.colors.muted; font.pixelSize: 11 }
        DialogSection {
            title: "Видео и редактор"
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                spacing: 12
                CheckBox { text: "Показывать видео"; checked: pane.config.videoVisible; onClicked: backend.appearance.setValue(pane.mode, "videoVisible", checked) }
                SettingsChoice { title: "Расположение видео"; group: pane.mode; setting: "videoSide"; labels: ["Слева", "Справа"]; values: ["left", "right"]; Layout.fillWidth: true; enabled: pane.config.videoVisible }
                SettingsNumber { title: "Ширина области видео"; description: "Доля от ширины рабочего пространства"; group: pane.mode; setting: "videoPercent"; from: 25; to: 60; unit: "%"; Layout.fillWidth: true; enabled: pane.config.videoVisible }
                SettingsNumber { visible: pane.timing; title: "Высота видео и редактора"; description: "Доля от высоты рабочего пространства"; group: "timing"; setting: "topPercent"; from: 32; to: 65; unit: "%"; Layout.fillWidth: true }
                SettingsChoice { visible: !pane.timing; title: "Таблица реплик"; group: "translation"; setting: "tableFirst"; labels: ["Над редактором", "Под редактором"]; values: [true, false]; Layout.fillWidth: true }
                SettingsChoice { visible: !pane.timing; title: "Оригинал и перевод"; group: "translation"; setting: "originalBelow"; labels: ["Рядом", "Друг под другом"]; values: [false, true]; Layout.fillWidth: true }
                SettingsNumber { visible: !pane.timing; title: "Высота редактора"; group: "translation"; setting: "editorHeight"; from: 315; to: 650; Layout.fillWidth: true }
                CheckBox { visible: !pane.timing; text: "Показывать контекст и проверку реплики"; enabled: pane.config.videoVisible; checked: backend.appearance.translation.contextVisible; onClicked: backend.appearance.setValue("translation", "contextVisible", checked) }
            }
        }
        DialogSection {
            title: "Аудиопанель"
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                spacing: 12
                CheckBox { text: "Показывать аудиопанель"; checked: pane.config.audioVisible; onClicked: backend.appearance.setValue(pane.mode, "audioVisible", checked) }
                SettingsChoice { visible: pane.timing; enabled: pane.config.audioVisible; title: "Расположение аудио"; group: "timing"; setting: "audioPosition"; labels: ["Над таблицей", "Под таблицей"]; values: ["middle", "bottom"]; Layout.fillWidth: true }
                SettingsNumber { enabled: pane.config.audioVisible; title: "Высота аудиопанели"; group: pane.mode; setting: "audioHeight"; from: 145; to: 350; Layout.fillWidth: true }
            }
        }
        Button { text: "Восстановить раскладку «" + (pane.timing ? "Тайминг" : "Перевод") + "»"; onClicked: backend.appearance.reset(pane.mode) }
    }
}
