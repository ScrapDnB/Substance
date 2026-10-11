import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    required property var colors
    popupType: Popup.Item
    property string kind: "note"
    property string entryId: ""
    property string targetField: "text"
    property string sourceText: ""
    property string originalBase: ""
    property bool revising: false
    title: kind === "note" ? (entryId ? "Изменить заметку" : "Заметка к реплике") : (entryId ? "Пересмотреть предложение" : "Предложение правки")
    width: Math.min(680, parent.width - 40)
    height: Math.min(kind === "note" ? 340 : 620, parent.height - 60)
    modal: true
    anchors.centerIn: Overlay.overlay
    standardButtons: Dialog.NoButton
    function create(type) {
        if (!backend.ensureProject() || !backend.current.exists) return
        kind = type; entryId = ""; revising = false
        targetField = backend.mode === "translation" ? "translation" : "text"
        sourceText = backend.current.editText
        originalBase = sourceText
        comment.text = ""; replacement.text = sourceText
        open()
    }
    function edit(entry) {
        kind = entry.kind; entryId = entry.id; revising = true
        targetField = entry.currentField || entry.field
        originalBase = entry.base.replace(/\\N/g, "\n")
        comment.text = entry.text
        replacement.text = entry.replacement.replace(/\\N/g, "\n")
        let choices = backend.cueChoices
        target.currentIndex = Math.max(0, choices.findIndex(c => c.id === (entry.cueId || backend.current.id)))
        sourceText = choices.length ? (targetField === "translation" ? choices[target.currentIndex].translation : choices[target.currentIndex].text) : ""
        open()
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        Label { text: dialog.kind === "note" ? "Заметка не меняет текст субтитра." : "После применения предложенный вариант заменит рабочий текст реплики."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted }
        ComboBox {
            id: target
            objectName: "proposalTarget"
            visible: dialog.kind === "proposal" && dialog.revising
            Layout.fillWidth: true
            model: backend.cueChoices
            textRole: "label"
            onActivated: dialog.sourceText = dialog.targetField === "translation" ? model[currentIndex].translation : model[currentIndex].text
        }
        Label { visible: dialog.kind === "proposal" && dialog.revising && dialog.originalBase !== dialog.sourceText; text: "При создании предложения: " + dialog.originalBase; textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true; maximumLineCount: 4; elide: Text.ElideRight; color: dialog.colors.muted }
        Label { visible: dialog.kind === "proposal"; text: "Текущий текст"; color: dialog.colors.muted }
        ScrollView {
            visible: dialog.kind === "proposal"
            Layout.fillWidth: true; Layout.preferredHeight: 90
            TextArea { text: dialog.sourceText; readOnly: true; wrapMode: TextEdit.Wrap; selectByMouse: true; textFormat: TextEdit.PlainText }
        }
        Label { visible: dialog.kind === "proposal"; text: "Предложенный вариант" }
        ScrollView {
            visible: dialog.kind === "proposal"
            Layout.fillWidth: true; Layout.fillHeight: true
            TextArea { id: replacement; objectName: "proposedText"; wrapMode: TextEdit.Wrap; selectByMouse: true; textFormat: TextEdit.PlainText }
        }
        Label { text: dialog.kind === "note" ? "Текст заметки" : "Пояснение" }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: dialog.kind === "note"; Layout.preferredHeight: 85
            TextArea { id: comment; objectName: "reviewComment"; wrapMode: TextEdit.Wrap; selectByMouse: true; textFormat: TextEdit.PlainText }
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            Button { text: "Отмена"; onClicked: dialog.close() }
            Button {
                objectName: "saveReview"
                text: dialog.revising && dialog.kind === "proposal" ? "Сохранить пересмотр" : "Сохранить"
                highlighted: true
                enabled: dialog.kind === "proposal" ? replacement.text !== dialog.sourceText && (!dialog.revising || target.count > 0) : comment.text.trim().length > 0
                onClicked: {
                    let ok = dialog.entryId ? (dialog.kind === "note" ? backend.editNote(dialog.entryId, comment.text) : backend.rebaseProposal(dialog.entryId, target.model[target.currentIndex].id, replacement.text, comment.text)) : backend.addReview(dialog.kind, comment.text, replacement.text)
                    if (ok) dialog.close()
                }
            }
        }
    }
}
