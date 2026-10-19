import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    property var suggestions: []
    property int suggestionIndex: -1
    property string pendingName: ""
    title: "Персонаж для выбранных реплик"
    modal: true
    preferredWidth: 440
    standardButtons: Dialog.NoButton

    function updateSuggestions() {
        suggestions = backend.characterSuggestions(actorName.text)
        suggestionIndex = suggestions.length ? 0 : -1
    }
    function assign(name, create) {
        if (backend.assignCharacterName(name, create)) dialog.dismiss()
    }
    function submit() {
        if (!actorName.text.trim().length) return
        if (suggestionIndex >= 0) {
            assign(suggestions[suggestionIndex].name, false)
        } else {
            pendingName = actorName.text.trim()
            createDialog.open()
        }
    }
    function moveSuggestion(delta) {
        if (suggestions.length)
            suggestionIndex = (suggestionIndex + delta + suggestions.length) % suggestions.length
    }
    onOpened: {
        actorName.text = backend.current.character
        updateSuggestions()
        actorName.forceActiveFocus()
        actorName.selectAll()
    }
    onClosed: {
        createDialog.close()
        backend.focusEditor()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        DialogTextField {
            id: actorName
            objectName: "assignCharacterName"
            Layout.fillWidth: true
            placeholderText: "Имя персонажа"
            Accessible.name: "Персонаж"
            onTextChanged: dialog.updateSuggestions()
            Keys.onReturnPressed: event => { dialog.submit(); event.accepted = true }
            Keys.onEnterPressed: event => { dialog.submit(); event.accepted = true }
            Keys.onDownPressed: event => { dialog.moveSuggestion(1); event.accepted = true }
            Keys.onUpPressed: event => { dialog.moveSuggestion(-1); event.accepted = true }
        }
        ListView {
            id: suggestionList
            objectName: "characterSuggestions"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(5, count) * 36
            visible: count > 0
            clip: true
            model: dialog.suggestions
            currentIndex: dialog.suggestionIndex
            onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
            ScrollBar.vertical: ScrollBar { }
            delegate: DialogItemDelegate {
                required property var modelData
                required property int index
                width: suggestionList.width
                height: 36
                text: modelData.name
                highlighted: index === dialog.suggestionIndex
                onClicked: dialog.assign(modelData.name, false)
            }
        }
        Label {
            Layout.fillWidth: true
            text: dialog.suggestions.length ? "↑ ↓ — выбрать · Enter — назначить" : "Новое имя · Enter — создать и назначить"
            color: dialog.colors.muted
        }
        RowLayout {
            Layout.fillWidth: true
            Button { objectName: "clearCharacterAssignment"; text: "Снять назначение"; onClicked: dialog.assign("", false) }
            Item { Layout.fillWidth: true }
            Button { text: "Отмена"; onClicked: dialog.reject() }
            Button { objectName: "confirmCharacterAssignment"; text: "Назначить"; highlighted: true; enabled: actorName.text.trim().length > 0; onClicked: dialog.submit() }
        }
    }

    NativeDialog {
        id: createDialog
        objectName: "createCharacterConfirmation"
        title: "Создать персонажа?"
        modal: true
        preferredWidth: dialog.preferredWidth
        colors: dialog.colors
        transientParent: dialog
        standardButtons: Dialog.NoButton
        function confirmCreation() {
            if (backend.assignCharacterName(dialog.pendingName, true)) {
                createDialog.close()
                dialog.dismiss()
            }
        }
        onOpened: createButton.forceActiveFocus()
        onRejected: actorName.forceActiveFocus()
        ColumnLayout {
            anchors.fill: parent
            Label { Layout.fillWidth: true; text: "Создать персонажа «" + dialog.pendingName + "» и назначить выбранным репликам?"; textFormat: Text.PlainText; wrapMode: Text.Wrap }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                Button { objectName: "cancelCharacterCreation"; text: "Нет"; onClicked: createDialog.reject() }
                Button {
                    id: createButton
                    objectName: "acceptCharacterCreation"
                    text: "Создать и назначить"
                    highlighted: true
                    onClicked: createDialog.confirmCreation()
                    Keys.onReturnPressed: event => { createDialog.confirmCreation(); event.accepted = true }
                    Keys.onEnterPressed: event => { createDialog.confirmCreation(); event.accepted = true }
                }
            }
        }
    }
}
