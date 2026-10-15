import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    property string kind: "note"
    property string entryId: ""
    property string targetField: "text"
    property string sourceText: ""
    property string originalBase: ""
    property bool revising: false
    property bool onlineReply: false
    property string replyState: ""
    property string onlineCueId: ""
    property int baseRevision: 0
    property int baseVersion: 0
    property bool saved: false
    property var reviewSession: backend.onlineSession.reviewSession
    property var onlineEntry: reviewSession.entries.find(r => r.id === entryId) || null
    property bool outdated: backend.onlineSession.active && (onlineReply ? !onlineEntry || onlineEntry.version !== baseVersion : baseRevision !== backend.onlineSession.revision)
    function storeDraft() {
        if (!visible || !backend.onlineSession.active || saved) return
        reviewSession.saveDraft({action: onlineReply ? (replyState ? "state" : "replies") : "create", thread_id: entryId, kind: kind, text: comment.text, replacement: replacement.text, state: replyState, cue_id: onlineCueId, revision: baseRevision, base_version: baseVersion})
    }
    function restoreDraft() {
        let draft = reviewSession.draft
        if (!Object.keys(draft).length) return
        onlineReply = draft.action !== "create"
        entryId = draft.thread_id || ""
        kind = draft.kind || "note"
        replyState = draft.state || ""
        onlineCueId = draft.cue_id || ""
        baseRevision = draft.revision || 0
        baseVersion = draft.base_version || 0
        revising = false; saved = false
        comment.text = draft.text || ""
        replacement.text = (draft.replacement || "").replace(/\\N/g, "\n")
        if (!onlineReply) backend.selectCueId(onlineCueId)
        sourceText = onlineReply ? "" : backend.current.editText
        open()
    }
    onClosed: { draftTimer.stop(); if (!saved && backend.onlineSession.active) { reviewSession.saveDraft({action: onlineReply ? (replyState ? "state" : "replies") : "create", thread_id: entryId, kind: kind, text: comment.text, replacement: replacement.text, state: replyState, cue_id: onlineCueId, revision: baseRevision, base_version: baseVersion}) } }
    Connections { target: dialog.reviewSession; function onSaveDraftRequested() { dialog.storeDraft() } }
    Timer { id: draftTimer; interval: 200; onTriggered: dialog.storeDraft() }
    title: onlineReply ? ({resolved:"Решить замечание", rejected:"Отклонить замечание", open:"Открыть замечание снова"})[replyState] || "Ответ на замечание" : kind === "note" ? (entryId ? "Изменить заметку" : "Заметка к реплике") : (entryId ? "Пересмотреть предложение" : "Предложение правки")
    preferredWidth: 680
    preferredHeight: onlineReply || kind === "note" ? 420 : 660
    modal: true
    standardButtons: Dialog.NoButton
    function create(type) {
        if (backend.onlineSession.active && Object.keys(reviewSession.draft).length) { restoreDraft(); return }
        if (type === "restore") return
        onlineReply = false; replyState = ""; saved = false
        baseRevision = backend.onlineSession.revision
        onlineCueId = backend.current.id || ""
        if (!backend.ensureProject() || !backend.current.exists) return
        kind = type; entryId = ""; revising = false
        targetField = backend.mode === "translation" ? "translation" : "text"
        sourceText = backend.current.editText
        originalBase = sourceText
        comment.text = ""; replacement.text = sourceText
        open()
    }
    function edit(entry) {
        if (entry.onlineReply) {
            if (Object.keys(reviewSession.draft).length) { restoreDraft(); return }
            onlineReply = true; replyState = entry.state; entryId = entry.entry.id
            baseVersion = entry.entry.version; onlineCueId = entry.entry.cue_id
            kind = "note"; revising = false; saved = false; comment.text = ""; replacement.text = ""
            open(); return
        }
        onlineReply = false; saved = false
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
        Label { text: dialog.onlineReply ? "Ответ или решение сохранятся в общей истории обсуждения." : backend.onlineSession.active ? "Замечание привязано к ревизии " + dialog.baseRevision + ". Предложенный текст вносится в реплику при редактировании." : dialog.kind === "note" ? "Заметка не меняет текст субтитра." : "После применения предложенный вариант заменит рабочий текст реплики."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted }
        Label { visible: dialog.onlineReply && dialog.onlineEntry !== null; text: dialog.onlineEntry ? dialog.onlineEntry.text : ""; textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Label { visible: dialog.outdated; text: "Версия изменилась. Просмотрите актуальный текст или обсуждение перед отправкой."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.warning }
        Button { visible: dialog.outdated; text: "Обновить привязку черновика"; enabled: dialog.onlineReply ? dialog.onlineEntry !== null : backend.current.id === dialog.onlineCueId; onClicked: { dialog.baseRevision = backend.onlineSession.revision; dialog.baseVersion = dialog.onlineEntry ? dialog.onlineEntry.version : 0; dialog.sourceText = backend.current.editText; dialog.storeDraft() } }
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
            DialogTextArea { text: dialog.sourceText; readOnly: true; wrapMode: TextEdit.Wrap; selectByMouse: true; textFormat: TextEdit.PlainText }
        }
        Label { visible: dialog.kind === "proposal"; text: "Предложенный вариант" }
        ScrollView {
            visible: dialog.kind === "proposal"
            Layout.fillWidth: true; Layout.fillHeight: true
            DialogTextArea { id: replacement; objectName: "proposedText"; wrapMode: TextEdit.Wrap; selectByMouse: true; textFormat: TextEdit.PlainText; onTextChanged: { if (dialog.visible && backend.onlineSession.active) draftTimer.restart() } }
        }
        Label { text: dialog.onlineReply ? "Ответ / причина решения" : dialog.kind === "note" ? "Текст заметки" : "Пояснение" }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: dialog.kind === "note"; Layout.preferredHeight: 85
            DialogTextArea { id: comment; objectName: "reviewComment"; wrapMode: TextEdit.Wrap; selectByMouse: true; textFormat: TextEdit.PlainText; onTextChanged: { if (dialog.visible && backend.onlineSession.active) draftTimer.restart() } }
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            Button { text: "Удалить черновик"; visible: backend.onlineSession.active; onClicked: { if (dialog.reviewSession.saveDraft({})) { dialog.saved = true; draftTimer.stop(); dialog.close() } } }
            Button { text: "Отмена"; onClicked: { dialog.storeDraft(); dialog.close() } }
            Button {
                objectName: "saveReview"
                text: dialog.revising && dialog.kind === "proposal" ? "Сохранить пересмотр" : "Сохранить"
                highlighted: true
                enabled: !dialog.outdated && (!backend.onlineSession.active || !backend.onlineSession.busy && !dialog.reviewSession.pending && (dialog.onlineReply ? (dialog.replyState ? dialog.reviewSession.canDecide : dialog.reviewSession.canReply) : dialog.reviewSession.canCreate && backend.current.id === dialog.onlineCueId)) && (dialog.kind === "proposal" ? replacement.text !== dialog.sourceText && (!dialog.revising || target.count > 0) : comment.text.trim().length > 0) && (!backend.onlineSession.active || comment.text.trim().length > 0 && comment.text.length <= 10000)
                onClicked: {
                    let ok
                    if (backend.onlineSession.active) {
                        dialog.storeDraft()
                        ok = dialog.onlineReply ? dialog.reviewSession.respondAt(dialog.entryId, dialog.replyState, comment.text, dialog.baseVersion) : dialog.reviewSession.createAt(dialog.kind, comment.text, replacement.text, dialog.onlineCueId, dialog.baseRevision)
                    } else ok = dialog.entryId ? (dialog.kind === "note" ? backend.editNote(dialog.entryId, comment.text) : backend.rebaseProposal(dialog.entryId, target.model[target.currentIndex].id, replacement.text, comment.text)) : backend.addReview(dialog.kind, comment.text, replacement.text)
                    if (ok) { dialog.saved = true; draftTimer.stop(); dialog.close() }
                }
            }
        }
    }
}
