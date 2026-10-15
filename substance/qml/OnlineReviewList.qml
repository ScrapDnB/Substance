import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: panel
    required property var colors
    property var session: backend.onlineSession.reviewSession
    signal composeRequested(string kind)
    signal respondRequested(var entry, string state)
    spacing: 10
    RowLayout {
        Layout.fillWidth: true
        ComboBox { id: scope; model: ["Текущая реплика", "Все замечания"]; Layout.fillWidth: true }
        CheckBox { id: history; text: "Решённые" }
        Button { text: "Обновить"; enabled: !backend.onlineSession.busy; onClicked: panel.session.refresh() }
    }
    Label { visible: !panel.session.supported; text: "Для общих замечаний обновите сервер."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: panel.colors.muted }
    Label { visible: panel.session.status.length > 0; text: panel.session.status; textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true; color: panel.colors.warning }
    RowLayout {
        Layout.fillWidth: true
        Button { text: "Добавить замечание"; enabled: panel.session.canCreate && backend.current.exists && !backend.onlineSession.busy; onClicked: panel.composeRequested("note") }
        Button { text: "Предложить текст"; enabled: panel.session.canCreate && backend.current.exists && !backend.onlineSession.busy; onClicked: panel.composeRequested("proposal") }
        Button { text: "Черновик"; visible: Object.keys(panel.session.draft).length > 0; enabled: !backend.onlineSession.busy && !panel.session.pending; onClicked: panel.composeRequested("restore") }
    }
    RowLayout {
        visible: panel.session.pending
        Button { text: "Повторить отправку"; enabled: !backend.onlineSession.busy; onClicked: panel.session.retry() }
        Button { text: "Вернуть в черновик"; enabled: panel.session.canRestore && !backend.onlineSession.busy; onClicked: { if (panel.session.restorePending()) panel.composeRequested("restore") } }
    }
    Label { visible: backend.onlineSession.pending; text: "Добавить замечание можно после подтверждения текста сервером."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: panel.colors.muted }
    ListView {
        id: records
        objectName: "onlineReviewList"
        Layout.fillWidth: true; Layout.fillHeight: true
        clip: true; spacing: 10
        ScrollBar.vertical: ScrollBar {}
        model: panel.session.entries.filter(r => (scope.currentIndex !== 0 || r.cue_id === backend.current.id) && (history.checked || r.state === "open"))
        delegate: Pane {
            required property var modelData
            width: records.width
            padding: 12
            background: Rectangle { color: Qt.tint(panel.colors.surface, Qt.alpha(panel.colors.text, 0.04)); radius: 8; border.color: panel.colors.border }
            ColumnLayout {
                width: parent.width
                spacing: 8
                Label { text: modelData.caption + " · " + ({open:"Открыто", resolved:"Решено", rejected:"Отклонено"})[modelData.state]; textFormat: Text.PlainText; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Label { text: modelData.author_name + " · " + modelData.created_at.slice(0, 16).replace("T", " ") + " UTC"; textFormat: Text.PlainText; color: panel.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Label { text: modelData.text; textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Label { text: "Текст при создании: " + modelData.contextText; textFormat: Text.PlainText; color: panel.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Label { visible: modelData.kind === "proposal"; text: "Предложено: " + (modelData.replacement || "").replace(/\\N/g, "\n"); textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Label { visible: modelData.archived; text: "Реплика удалена. Обсуждение и исходный контекст сохранены."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: panel.colors.muted }
                Button { visible: modelData.has_older_messages; text: "Показать всю переписку"; enabled: !backend.onlineSession.busy; onClicked: panel.session.loadHistory(modelData.id) }
                Repeater {
                    model: modelData.messages
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Label { text: modelData.author_name + " · " + modelData.created_at.slice(0, 16).replace("T", " ") + " UTC" + (modelData.state ? " · " + ({open:"Открыто снова", resolved:"Решено", rejected:"Отклонено"})[modelData.state] : ""); textFormat: Text.PlainText; color: panel.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: modelData.text; textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 6
                    Button { text: "К реплике"; visible: !modelData.archived; onClicked: backend.selectCueId(modelData.cue_id) }
                    Button { text: "Ответить"; visible: panel.session.canReply; enabled: !backend.onlineSession.busy; onClicked: panel.respondRequested(modelData, "") }
                    Button { text: "Решено"; visible: panel.session.canDecide && modelData.state === "open"; enabled: !backend.onlineSession.busy; onClicked: panel.respondRequested(modelData, "resolved") }
                    Button { text: "Отклонить"; visible: panel.session.canDecide && modelData.state === "open"; enabled: !backend.onlineSession.busy; onClicked: panel.respondRequested(modelData, "rejected") }
                    Button { text: "Открыть снова"; visible: panel.session.canReopen && modelData.state !== "open"; enabled: !backend.onlineSession.busy; onClicked: panel.respondRequested(modelData, "open") }
                }
            }
        }
        Label { anchors.centerIn: parent; visible: records.count === 0; text: "Замечаний пока нет"; color: panel.colors.muted }
    }
}
