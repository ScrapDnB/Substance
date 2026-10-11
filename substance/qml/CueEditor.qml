import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: panel
    required property var colors
    property bool translationMode: backend.mode === "translation"
    property bool loading: true
    property int cursorPosition: editTextArea.cursorPosition
    signal editorCursorChanged(int position)
    signal composeRequested(string kind)
    padding: 16
    background: Rectangle { color: panel.colors.surface }

    function reload() {
        loading = true
        let cue = backend.current
        startField.text = cue.startTime
        endField.text = cue.endTime
        characterField.text = cue.character
        editTextArea.text = cue.editText
        loading = false
    }
    Component.onCompleted: reload()
    Connections {
        target: backend
        function onCurrentChanged() { panel.reload() }
        function onFocusEditor() { editTextArea.forceActiveFocus() }
        function onHighlightWord(word) {
            let start = editTextArea.text.indexOf(word)
            if (start >= 0) {
                editTextArea.forceActiveFocus()
                editTextArea.select(start, start + word.length)
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Image { source: backend.currentPortraitUrl; Layout.preferredWidth: 28; Layout.preferredHeight: 32; fillMode: Image.PreserveAspectCrop; visible: source.toString().length > 0; MouseArea { anchors.fill: parent; onClicked: backend.openCharacters(backend.current.characterId) } }
            Label { text: backend.current.exists ? "Реплика " + backend.current.number : "Новая реплика"; font.bold: true; font.pixelSize: 16; color: panel.colors.text }
            Label { visible: backend.current.comment; text: "ASS-комментарий"; color: panel.colors.muted }
            Item { Layout.fillWidth: true }
            ControlButton { symbol: "chevron-left"; enabled: backend.currentIndex > 0; onClicked: backend.navigate(-1); hint: "Предыдущая реплика · " + backend.shortcutLabel("previous") }
            ControlButton { symbol: "chevron-right"; enabled: backend.currentIndex < backend.count - 1; onClicked: backend.navigate(1); hint: "Следующая реплика · " + backend.shortcutLabel("next") }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Label { text: "Начало"; font.pixelSize: 11; color: panel.colors.muted }
                TextField { id: startField; objectName: "startField"; Layout.fillWidth: true; Layout.minimumWidth: 120; enabled: backend.current.exists; font.family: backend.isMac ? "Menlo" : "Consolas"; font.pixelSize: 12; selectByMouse: true; onTextEdited: backend.stage("start", text); onEditingFinished: backend.flush(); Accessible.name: "Время начала реплики" }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Label { text: "Конец"; font.pixelSize: 11; color: panel.colors.muted }
                TextField { id: endField; objectName: "endField"; Layout.fillWidth: true; Layout.minimumWidth: 120; enabled: backend.current.exists; font.family: backend.isMac ? "Menlo" : "Consolas"; font.pixelSize: 12; selectByMouse: true; onTextEdited: backend.stage("end", text); onEditingFinished: backend.flush(); Accessible.name: "Время конца реплики" }
            }
            ColumnLayout {
                spacing: 3
                Label { text: "Длительность"; font.pixelSize: 11; color: panel.colors.muted }
                Label { text: Number(backend.current.duration || 0).toFixed(3) + " с"; color: panel.colors.text; font.pixelSize: 12; Layout.minimumWidth: 66 }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Персонаж"; color: panel.colors.muted; font.pixelSize: 12 }
            TextField { id: characterField; Layout.fillWidth: true; placeholderText: "Имя или роль"; enabled: backend.current.exists; onTextEdited: backend.stage("character", text); onEditingFinished: backend.flush(); Accessible.name: "Персонаж" }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12
            ColumnLayout {
                visible: panel.translationMode
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 5
                Label { text: "Оригинал · только чтение"; font.pixelSize: 11; color: panel.colors.muted }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    TextArea { id: original; objectName: "originalEditor"; text: backend.current.original; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; font.pixelSize: 15; color: panel.colors.muted; Accessible.name: "Оригинальный текст" }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 5
                Label { text: panel.translationMode ? "Перевод" : "Текст реплики"; font.pixelSize: 11; color: panel.colors.muted }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    TextArea {
                        id: editTextArea
                        objectName: "subtitleEditor"
                        enabled: backend.current.exists
                        placeholderText: panel.translationMode ? "Введите перевод…" : "Введите текст…"
                        wrapMode: TextEdit.Wrap
                        selectByMouse: true
                        font.pixelSize: 16
                        color: panel.colors.text
                        onTextChanged: if (!panel.loading) backend.stage("text", text)
                        onCursorPositionChanged: panel.editorCursorChanged(cursorPosition)
                        Accessible.name: panel.translationMode ? "Текст перевода" : "Текст реплики"
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Button { text: "Заметки и правки" + (backend.currentReviews.length ? " · " + backend.currentReviews.filter(r => r.state === "open").length : ""); enabled: backend.current.exists; onClicked: backend.openReviews() }
            Button { text: "+ Заметка"; enabled: backend.current.exists; onClicked: panel.composeRequested("note") }
            Button { text: "Предложить правку"; enabled: backend.current.exists; onClicked: panel.composeRequested("proposal") }
            Item { Layout.fillWidth: true }
            Button { text: "Карточка"; flat: true; onClicked: backend.openCharacters(backend.current.characterId || "") }
        }
        Label {
            Layout.fillWidth: true
            visible: backend.currentReviews.some(r => r.state === "open")
            text: { let entry = backend.currentReviews.find(r => r.state === "open"); return entry ? (entry.kind === "note" ? "✎ " : "↔ ") + (entry.text || entry.replacement.replace(/\\N/g, " ")) : "" }
            textFormat: Text.PlainText; color: panel.colors.muted; font.pixelSize: 11; elide: Text.ElideRight
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: backend.current.cps + " зн/с"; color: backend.reviewSettings.readingSpeed && backend.current.cps > backend.cpsLimit ? panel.colors.warning : panel.colors.muted; font.pixelSize: 12 }
            Label { text: (backend.current.maxLine || 0) + " / " + backend.lineLimit; color: panel.colors.muted; font.pixelSize: 12 }
            Item { Layout.fillWidth: true }
            ControlButton { objectName: "playCueButton"; symbol: "play"; enabled: backend.media.hasMedia && backend.current.exists; onClicked: backend.playCurrent(false); hint: "Воспроизвести реплику · " + backend.shortcutLabel("playLine") }
            ControlButton {
                objectName: "applyCueButton"
                text: (panel.translationMode ? "Следующая реплика" : "Применить") + "  " + backend.shortcutLabel("apply")
                enabled: backend.current.exists
                highlighted: true
                palette.buttonText: Qt.platform.os !== "osx" || (Window.active && enabled) ? panel.colors.selectedText : panel.colors.text
                onClicked: backend.apply(panel.translationMode)
            }
        }
    }
}
