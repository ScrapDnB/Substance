import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    available: backend.onlineSession.active
    title: "Общий глоссарий проекта"
    preferredWidth: 1000
    preferredHeight: 720
    readonly property var session: backend.onlineSession.glossarySession
    property var form: ({})
    property var choices: ({})
    property bool loading: false
    readonly property var characterFields: [
        {key:"name", title:"Имя"}, {key:"export_name", title:"Имя в экспорте"},
        {key:"aliases", title:"Алиасы (по одному в строке)"}, {key:"description", title:"Описание"},
        {key:"speech", title:"Особенности речи"}, {key:"pronunciation", title:"Произношение"},
        {key:"relationships", title:"Отношения"}, {key:"notes", title:"Заметки"}]
    readonly property var termFields: [
        {key:"name", title:"Оригинал"}, {key:"translation", title:"Принятый перевод"},
        {key:"category", title:"Категория"}, {key:"pronunciation", title:"Произношение"},
        {key:"alternatives", title:"Допустимые варианты"}, {key:"forbidden", title:"Нежелательные варианты"},
        {key:"description", title:"Пояснение"}, {key:"example", title:"Пример"}]
    function loadDraft() {
        loading = true
        form = JSON.parse(JSON.stringify(session.draft))
        choices = ({})
        loading = false
    }
    function fieldValue(key) {
        let value = form.data ? form.data[key] : ""
        return key === "aliases" ? (value || []).join("\n") : (value || "")
    }
    function updateField(key, value) {
        if (loading || !form.data) return
        let next = JSON.parse(JSON.stringify(form))
        next.data[key] = key === "aliases" ? value.split("\n").map(v => v.trim()).filter(v => v.length) : value
        if (session.saveDraft(next)) form = next
    }
    onOpened: { loadDraft(); session.refresh() }
    Connections {
        target: dialog.session
        function onChanged() {
            // The server cache may change while typing; only explicit form actions
            // replace text. Disk-backed draft survives close and app shutdown.
            if (!dialog.session.draft.data && dialog.form.data) dialog.loadDraft()
        }
    }
    RowLayout {
        anchors.fill: parent
        spacing: 18
        ColumnLayout {
            Layout.preferredWidth: 250
            Layout.fillHeight: true
            DialogTextField { id: search; placeholderText: "Поиск карточек и терминов"; Layout.fillWidth: true }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true
                model: dialog.session.entries.filter(r => !search.text || r.data.name.toLowerCase().includes(search.text.toLowerCase()))
                delegate: DialogItemDelegate {
                    required property var modelData
                    width: ListView.view.width
                    text: (modelData.kind === "character" ? "♙ " : "≡ ") + modelData.data.name + (modelData.data.archived ? " · архив" : "")
                    enabled: !dialog.session.pending && !dialog.form.data
                    onClicked: { if (dialog.session.begin(modelData.id, modelData.kind)) dialog.loadDraft() }
                }
            }
            RowLayout {
                Button { text: "+ Персонаж"; enabled: dialog.session.canEdit && !dialog.session.pending && !dialog.form.data; onClicked: { if (dialog.session.begin("", "character")) dialog.loadDraft() } }
                Button { text: "+ Термин"; enabled: dialog.session.canEdit && !dialog.session.pending && !dialog.form.data; onClicked: { if (dialog.session.begin("", "term")) dialog.loadDraft() } }
            }
            Button { text: "Обновить"; enabled: !backend.onlineSession.busy; onClicked: dialog.session.refresh() }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            Label { text: dialog.session.status; visible: text.length > 0; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.warning }
            RowLayout {
                visible: dialog.session.pending
                Button { text: "Повторить отправку"; enabled: !backend.onlineSession.busy; onClicked: dialog.session.retry() }
                Button { text: "Вернуть в черновик"; enabled: dialog.session.canRestore && !backend.onlineSession.busy; onClicked: { if (dialog.session.restorePending()) dialog.loadDraft() } }
            }
            Label { visible: !dialog.form.data && !dialog.session.pending; text: "Выберите карточку или создайте новую. Черновик сохраняется на компьютере."; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true
                visible: !!dialog.form.data
                contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width
                    Label { text: dialog.form.kind === "term" ? "Термин" : "Персонаж"; font.bold: true }
                    Label { text: "Ревизия " + (dialog.form.base_revision || "новая карточка"); color: dialog.colors.muted }
                    Repeater {
                        model: dialog.form.kind === "term" ? dialog.termFields : dialog.characterFields
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Label { text: modelData.title }
                            DialogTextArea {
                                objectName: "glossaryField_" + modelData.key
                                Layout.fillWidth: true
                                implicitHeight: Math.max(38, Math.min(120, contentHeight + 16))
                                text: dialog.fieldValue(modelData.key)
                                textFormat: TextEdit.PlainText
                                wrapMode: TextEdit.Wrap
                                selectByMouse: true
                                readOnly: !dialog.session.canEdit
                                onTextChanged: if (activeFocus) dialog.updateField(modelData.key, text)
                            }
                        }
                    }
                    RowLayout {
                        Label { text: "Статус" }
                        ComboBox {
                            model: ["Черновик", "На проверке", "Утверждено"]
                            currentIndex: dialog.form.data ? ["draft", "review", "approved"].indexOf(dialog.form.data.status || "draft") : 0
                            enabled: dialog.session.canApprove
                            onActivated: dialog.updateField("status", ["draft", "review", "approved"][currentIndex])
                        }
                        CheckBox { text: "В архиве"; checked: !!(dialog.form.data && dialog.form.data.archived); enabled: dialog.session.canEdit; onClicked: dialog.updateField("archived", checked) }
                    }
                    Label { visible: dialog.session.stale; text: "На сервере появилась новая ревизия. Сравните поля и обновите базу черновика."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.warning }
                    Repeater {
                        model: dialog.session.conflicts
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Label { text: "Конфликт: " + modelData.title; font.bold: true }
                            Label { text: "Было: " + modelData.base; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: "Моё: " + modelData.mine; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: "Сервер: " + modelData.server; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            ComboBox {
                                model: ["Выберите значение", "Оставить моё", "Взять серверное"]
                                onActivated: { let next = Object.assign({}, dialog.choices); next[modelData.field] = currentIndex === 1 ? "mine" : currentIndex === 2 ? "server" : ""; dialog.choices = next }
                            }
                        }
                    }
                    Button { visible: dialog.session.stale; text: "Обновить базу с выбранными значениями"; enabled: !backend.onlineSession.busy; onClicked: { if (dialog.session.rebase(dialog.choices)) dialog.loadDraft() } }
                }
            }
            Label { visible: !!dialog.form.data && dialog.form.data.status === "approved" && !dialog.session.canApprove; text: "Правки утверждённой карточки будут отправлены предложением редактору."; wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                Button { text: "Закрыть"; onClicked: dialog.close() }
                Button { text: "Удалить черновик"; visible: !!dialog.form.data; enabled: !backend.onlineSession.busy; onClicked: { if (dialog.session.discardDraft()) dialog.loadDraft() } }
                Button { objectName: "glossarySend"; text: "Отправить"; highlighted: true; visible: !!dialog.form.data; enabled: dialog.session.canEdit && !dialog.session.pending && !dialog.session.stale && !backend.onlineSession.busy && !!dialog.form.data && !!dialog.form.data.name.trim(); onClicked: { if (dialog.session.send()) dialog.loadDraft() } }
            }
        }
    }
}
