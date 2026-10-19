import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: tool
    objectName: "workflowFilesTool"
    property bool delivery: false
    title: delivery ? "Выпуск и отчёт" : "Исходники и медиа"
    preferredWidth: 800
    preferredHeight: 620
    minimumWidth: 560
    minimumHeight: 520
    modal: false
    onOpened: {
        if (delivery) {
            reportProfile.currentIndex = 0
            backend.qualityProfiles.select(backend.qualityProfiles.names[0])
        }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 16
        Label { text: tool.title; font.pixelSize: 24; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
        Label { text: backend.title + " · Реплик: " + backend.count; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText }
        Label { text: backend.documentPath || "Документ ещё не сохранён"; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText; color: tool.colors.muted }
        DialogSection {
            visible: !tool.delivery
            title: "Текст и проект"
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                Label { text: "Откройте ASS, SRT, VTT, TXT или проект Substance. Импорт текстовой дорожки из видео создаёт документ из выбранной дорожки."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: tool.colors.muted }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Button { objectName: "preparationOpenFile"; text: "Открыть файл…"; enabled: !backend.busy; onClicked: backend.openDialog() }
                    Button { text: "Новый документ"; enabled: !backend.busy; onClicked: backend.newDocument() }
                    Button { text: "Импорт дорожки из видео…"; enabled: !backend.busy; onClicked: backend.importEmbedded() }
                }
            }
        }
        DialogSection {
            visible: !tool.delivery
            title: "Видео и аудио"
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                Label { text: backend.media.hasMedia ? backend.media.name : "Подключите видео или аудио для распознавания, тайминга и просмотра субтитров."; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText; color: tool.colors.muted }
                Button { objectName: "preparationOpenMedia"; text: backend.media.hasMedia ? "Заменить медиа…" : "Подключить медиа…"; enabled: !backend.busy; onClicked: backend.openMedia() }
            }
        }
        DialogSection {
            visible: tool.delivery
            title: "Субтитры для выпуска"
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                Label { text: "ASS сохраняет итоговый текст и оформление. SRT, VTT и TXT содержат итоговый текст без оформления ASS. В окне сохранения выберите нужный формат."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: tool.colors.muted }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Button { objectName: "postExportSubtitles"; text: "Экспорт субтитров…"; highlighted: true; enabled: backend.count > 0 && !backend.busy; onClicked: backend.exportDialog(false) }
                    Button { text: "Экспорт оригинала…"; enabled: backend.count > 0 && !backend.busy; onClicked: backend.exportDialog(true) }
                }
            }
        }
        DialogSection {
            visible: tool.delivery
            title: "Отчёт проверки"
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                Label { text: "Сохраните замечания по выбранному профилю в HTML или CSV. Профиль и отдельные исправления можно настроить в инструменте «Проверить и исправить»."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: tool.colors.muted }
                RowLayout {
                    Layout.fillWidth: true
                    ComboBox { id: reportProfile; Layout.fillWidth: true; model: backend.qualityProfiles.names; onActivated: backend.qualityProfiles.select(currentText) }
                    Button { objectName: "postExportReport"; text: "Сохранить отчёт…"; enabled: backend.count > 0 && !backend.busy; onClicked: backend.qualityProfiles.exportReport() }
                }
            }
        }
        Label { text: "Проект .substance сохраняет оригинал, перевод, персонажей, заметки и историю работы вместе."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: tool.colors.muted }
        Button { objectName: "workflowSaveProject"; text: backend.isProject ? "Сохранить проект" : "Сохранить как проект…"; enabled: !backend.busy; onClicked: backend.isProject ? backend.save() : backend.ensureProject() }
        Item { Layout.fillHeight: true }
    }
}
