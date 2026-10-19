import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    property bool loading: false
    property bool modified: false
    property string editedId: ""
    title: "Персонажи проекта"
    preferredWidth: 860
    preferredHeight: 760
    modal: false
    standardButtons: Dialog.NoButton
    function stage() {
        if (backend.onlineSession.active) return
        if (loading) return
        modified = true
        backend.stageCard(editedId, cardName.text, aliases.text, exportName.text, description.text, speech.text, notes.text)
    }
    function reload() {
        loading = true
        let card = backend.currentCard
        editedId = card.id; cardName.text = card.name; aliases.text = card.aliases.join(", "); exportName.text = card.export_name
        description.text = card.description; speech.text = card.speech; notes.text = card.notes
        modified = backend.hasCardDraft; loading = false
    }
    function save() {
        let ok = backend.saveCharacter(editedId, cardName.text, aliases.text, exportName.text, description.text, speech.text, notes.text)
        if (ok) reload()
        return ok
    }
    function switchCard(id) {
        if (modified && !save()) return
        backend.selectCard(id); reload()
    }
    onOpened: reload()

    Connections {
        target: backend
        function onChanged() { if (dialog.presented && !dialog.modified) dialog.reload() }
        function onCardSaved(cardId) { if (dialog.presented) { dialog.editedId = cardId; dialog.modified = false } }
    }
    RowLayout {
        anchors.fill: parent
        spacing: 16
        ColumnLayout {
            Layout.preferredWidth: 180; Layout.fillHeight: true
            Label { visible: backend.onlineSession.active; Layout.fillWidth: true; text: "Общий глоссарий. Правки карточек — в DubbingManager."; wrapMode: Text.WordWrap; font.pixelSize: 11 }
            ListView {
                id: cards
                objectName: "characterList"
                Layout.fillHeight: true; Layout.fillWidth: true
                clip: true; spacing: 4
                ScrollBar.vertical: ScrollBar { }
                model: backend.characterCards
                delegate: DialogItemDelegate {
                    required property var modelData
                    width: cards.width; height: 56
                    highlighted: dialog.editedId === modelData.id
                    onClicked: dialog.switchCard(modelData.id)
                    contentItem: RowLayout {
                        Image { source: modelData.portraitUrl; Layout.preferredWidth: 40; Layout.preferredHeight: 40; sourceSize.width: 80; sourceSize.height: 80; fillMode: Image.PreserveAspectCrop; visible: source.toString().length > 0 }
                        Label { text: modelData.name; color: dialog.editedId === modelData.id ? dialog.colors.selectedText : dialog.colors.text; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true }
                    }
                }
            }
            Button { text: "Новый персонаж"; enabled: !backend.onlineSession.active; Layout.fillWidth: true; onClicked: dialog.switchCard("") }
            Button { objectName: "autoPortraitsButton"; text: "Автопортреты…"; Layout.fillWidth: true; onClicked: { if (!dialog.modified || dialog.save()) backend.portraitTools.open() } }
            Button { text: "Удалить карточку"; enabled: !backend.onlineSession.active && dialog.editedId.length > 0 && backend.currentCard.cues.length === 0; Layout.fillWidth: true; onClicked: backend.deleteCharacter(dialog.editedId) }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        Image { source: backend.currentCard.portraitUrl; Layout.preferredWidth: 80; Layout.preferredHeight: 100; fillMode: Image.PreserveAspectFit; visible: source.toString().length > 0 }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Label { text: "Имя персонажа" }
                            DialogTextField { readOnly: backend.onlineSession.active; id: cardName; objectName: "characterName"; Layout.fillWidth: true; placeholderText: "Имя"; onTextEdited: dialog.stage() }
                            Label { text: "Имя в экспорте"; color: dialog.colors.muted }
                            DialogTextField { readOnly: backend.onlineSession.active; id: exportName; Layout.fillWidth: true; placeholderText: cardName.text; onTextEdited: dialog.stage() }
                        }
                    }
                    Label { text: "Альтернативные имена через запятую"; color: dialog.colors.muted }
                    DialogTextField { readOnly: backend.onlineSession.active; id: aliases; Layout.fillWidth: true; onTextEdited: dialog.stage() }
                    Label { text: "Описание" }
                    DialogTextArea { readOnly: backend.onlineSession.active; id: description; Layout.fillWidth: true; Layout.preferredHeight: 80; wrapMode: TextEdit.Wrap; selectByMouse: true; textFormat: TextEdit.PlainText; onTextChanged: dialog.stage() }
                    Label { text: "Особенности речи и произношение" }
                    DialogTextArea { readOnly: backend.onlineSession.active; id: speech; Layout.fillWidth: true; Layout.preferredHeight: 80; wrapMode: TextEdit.Wrap; selectByMouse: true; textFormat: TextEdit.PlainText; onTextChanged: dialog.stage() }
                    Label { text: "Заметки о персонаже" }
                    DialogTextArea { readOnly: backend.onlineSession.active; id: notes; Layout.fillWidth: true; Layout.preferredHeight: 80; wrapMode: TextEdit.Wrap; selectByMouse: true; textFormat: TextEdit.PlainText; onTextChanged: dialog.stage() }
                    RowLayout {
                        Button { text: "Из видео…"; enabled: !backend.onlineSession.active && backend.media.hasVideo; onClicked: { if (dialog.modified || !dialog.editedId) { if (!dialog.save()) return } backend.capturePortrait(dialog.editedId) } }
                        Button { text: "Из файла…"; enabled: !backend.onlineSession.active; onClicked: { if (dialog.modified || !dialog.editedId) { if (!dialog.save()) return } backend.importPortrait(dialog.editedId) } }
                    }
                    Repeater {
                        model: backend.currentCard.portraits
                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Image { source: modelData.url; Layout.preferredWidth: 90; Layout.preferredHeight: 90; sourceSize.width: 180; sourceSize.height: 180; fillMode: Image.PreserveAspectFit }
                            ColumnLayout {
                                Label { text: modelData.id === backend.currentCard.primary ? "Основной портрет" : "Дополнительное изображение"; color: dialog.colors.muted }
                                RowLayout {
                                    Button { text: "Обрезать"; enabled: !backend.onlineSession.active; onClicked: backend.recropPortrait(dialog.editedId, modelData.id) }
                                    Button { text: "Основной"; enabled: !backend.onlineSession.active && modelData.id !== backend.currentCard.primary; onClicked: backend.portraitAction(dialog.editedId, modelData.id, "primary") }
                                    Button { text: "Удалить"; enabled: !backend.onlineSession.active; onClicked: backend.portraitAction(dialog.editedId, modelData.id, "delete") }
                                }
                                Button { text: "К кадру видео"; visible: modelData.media_path.length > 0; onClicked: { backend.seekPortrait(dialog.editedId, modelData.id); dialog.dismiss() } }
                            }
                        }
                    }
                    Label { text: "Реплики персонажа · " + backend.currentCard.cues.length; font.bold: true }
                    Repeater {
                        model: backend.currentCard.cues
                        delegate: DialogItemDelegate { required property var modelData; Layout.fillWidth: true; text: modelData.number + " · " + modelData.time + " · " + modelData.text; onClicked: { backend.selectCueId(modelData.id); dialog.dismiss() } }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Button { text: "Назначить выбранным репликам"; enabled: dialog.editedId.length > 0 && backend.current.exists; onClicked: { if (!dialog.modified || dialog.save()) backend.assignCharacter(dialog.editedId) } }
                Button { text: "Снять назначение"; enabled: backend.current.exists; onClicked: backend.assignCharacter("") }
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                Button { text: "Отменить изменения"; visible: dialog.modified; onClicked: { dialog.modified = false; backend.discardCardDraft(); dialog.reload() } }
                Button { text: "Закрыть"; onClicked: { if (!dialog.modified || dialog.save()) dialog.dismiss() } }
                Button { objectName: "saveCharacterCard"; text: "Сохранить карточку"; highlighted: true; enabled: !backend.onlineSession.active && cardName.text.trim().length > 0; onClicked: dialog.save() }
            }
        }
    }
}
