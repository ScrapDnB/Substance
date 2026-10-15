import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    signal composeRequested(string kind)
    signal editRequested(var entry)
    title: backend.onlineSession.active ? "Общие замечания серии" : "Заметки и предложения правок"
    preferredWidth: 800
    preferredHeight: 740
    modal: true
    standardButtons: Dialog.Close
    ColumnLayout {
        anchors.fill: parent
        visible: !backend.onlineSession.active
        RowLayout {
            Layout.fillWidth: true
            SegmentedSelector { id: scope; Layout.fillWidth: true; property int selectedScope: 0; labels: ["Текущая реплика", "Все записи"]; selectedIndex: selectedScope; onActivated: index => selectedScope = index }
            CheckBox { id: history; text: "История" }
        }
        RowLayout {
            Button { text: "Добавить заметку"; enabled: backend.current.exists; onClicked: dialog.composeRequested("note") }
            Button { text: "Предложить правку"; enabled: backend.current.exists; onClicked: dialog.composeRequested("proposal") }
        }
        ListView {
            id: records
            objectName: "reviewList"
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 10
            ScrollBar.vertical: ScrollBar { }
            model: (scope.currentIndex === 0 ? backend.currentReviews : backend.reviewEntries).filter(r => history.checked || r.state === "open")
            delegate: Pane {
                required property var modelData
                width: records.width
                padding: 12
                background: Rectangle { color: dialog.colors.alternate; radius: 8; border.color: dialog.colors.border }
                ColumnLayout {
                    width: parent.width
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: modelData.kind === "note" ? "Заметка" : "Предложение правки"; font.bold: true }
                        Label { text: modelData.caption; color: dialog.colors.muted; textFormat: Text.PlainText }
                        Item { Layout.fillWidth: true }
                        Label { text: ({open:"Открыто", resolved:"Решено", applied:"Применено", rejected:"Отклонено"})[modelData.state]; color: dialog.colors.muted }
                    }
                    Label { text: modelData.text; visible: text.length > 0; textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Label { text: modelData.diff; visible: modelData.kind === "proposal"; textFormat: Text.RichText; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Label { text: "Текст изменился — предложение нужно пересмотреть."; visible: modelData.kind === "proposal" && modelData.state === "open" && modelData.stale && !modelData.archived; color: dialog.colors.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Label { text: "Реплика удалена. Запись сохранена в архиве.\n" + modelData.context.replace(/\\N/g, "\n"); visible: modelData.archived; textFormat: Text.PlainText; color: dialog.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    RowLayout {
                        Layout.fillWidth: true
                        Button { text: "К реплике"; visible: !modelData.archived; onClicked: { backend.selectCueId(modelData.cue_ids[0]); dialog.close() } }
                        Button { text: "Изменить"; visible: modelData.kind === "note"; onClicked: dialog.editRequested(modelData) }
                        Button { text: modelData.state === "open" ? "Решено" : "Открыть снова"; visible: modelData.kind === "note"; onClicked: backend.reviewAction(modelData.id, modelData.state === "open" ? "resolved" : "open") }
                        Button { text: "Применить"; highlighted: true; visible: modelData.kind === "proposal" && modelData.state === "open"; enabled: !modelData.stale; onClicked: backend.reviewAction(modelData.id, "apply") }
                        Button { text: "Пересмотреть"; visible: modelData.kind === "proposal" && modelData.state === "open"; enabled: backend.count > 0; onClicked: dialog.editRequested(modelData) }
                        Button { text: "Отклонить"; visible: modelData.kind === "proposal" && modelData.state === "open"; onClicked: backend.reviewAction(modelData.id, "rejected") }
                        Item { Layout.fillWidth: true }
                        Button { text: "Удалить"; visible: modelData.kind === "note"; flat: true; onClicked: backend.reviewAction(modelData.id, "delete") }
                    }
                    Label { text: modelData.created.slice(0, 16).replace("T", " ") + " UTC"; color: dialog.colors.muted; font.pixelSize: 10 }
                }
            }
            Label { anchors.centerIn: parent; visible: records.count === 0; text: "Записей пока нет"; color: dialog.colors.muted }
        }
    }
    OnlineReviewList {
        anchors.fill: parent
        visible: backend.onlineSession.active
        colors: dialog.colors
        onComposeRequested: kind => dialog.composeRequested(kind)
        onRespondRequested: (entry, state) => dialog.editRequested({onlineReply: true, entry: entry, state: state})
    }
}
