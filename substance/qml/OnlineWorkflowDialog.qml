import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    available: backend.onlineSession.active
    property string action: "return"
    title: action === "return" ? "Вернуть перевод на доработку" : "Переоткрыть работу над серией"
    preferredWidth: 560
    preferredHeight: 340
    function beginAction(value) { action = value; reason.text = ""; open() }
    Connections { target: backend.onlineSession; function onWorkflowCompleted(value) { if (dialog.visible && dialog.action === value) dialog.close() } }
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: "Укажите причину. Она сохранится в журнале проекта."; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Label { text: backend.onlineSession.status; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true
            DialogTextArea { id: reason; objectName: "onlineWorkflowReason"; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap; selectByMouse: true }
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            Button { text: "Отмена"; onClicked: dialog.close() }
            Button { objectName: "onlineWorkflowSubmit"; text: "Подтвердить"; highlighted: true; enabled: reason.text.trim().length > 0 && !backend.onlineSession.busy && !backend.onlineSession.pending && !backend.onlineSession.reviewSession.pending; onClicked: { backend.onlineSession.workflow(dialog.action, reason.text) } }
        }
    }
}
