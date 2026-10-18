import QtQuick
import QtQuick.Controls

DialogTextField {
    id: field
    property var choices: []
    property string selectedId: ""
    property string contextKey: ""
    property bool canCreate: false
    readonly property string selectedName: choices.find(c => c.id === selectedId)?.name || ""
    property var matches: []
    signal chosen(string characterId)
    signal createRequested(string name)

    placeholderText: "Начните вводить имя персонажа…"
    Accessible.name: "Поиск персонажа по имени"
    rightPadding: clearButton.visible ? clearButton.width + 6 : 6

    function restoreSelection() {
        suggestions.close();
        text = selectedName;
    }
    function updateSuggestions() {
        let query = text.trim().toLocaleLowerCase();
        matches = query.length ? choices.filter(c => c.name.toLocaleLowerCase().includes(query)).sort((a, b) => Number(!a.name.toLocaleLowerCase().startsWith(query)) - Number(!b.name.toLocaleLowerCase().startsWith(query))) : [];
        if (query.length && canCreate && !choices.some(c => c.name.toLocaleLowerCase() === query))
            matches = matches.concat([
                {
                    id: "",
                    name: text.trim(),
                    create: true
                }
            ]);
        suggestionList.currentIndex = matches.length ? 0 : -1;
        if (query.length)
            suggestions.open();
        else
            suggestions.close();
    }
    function choose(character) {
        suggestions.close();
        if (character.create) {
            createRequested(character.name);
            text = selectedName;
            return;
        }
        text = character.name;
        deselect();
        chosen(character.id);
    }
    function submit() {
        if (!text.trim().length)
            choose({
                id: "",
                name: ""
            });
        else if (suggestions.opened && suggestionList.currentIndex >= 0)
            choose(matches[suggestionList.currentIndex]);
    }
    function moveSuggestion(delta) {
        if (!suggestions.opened) {
            updateSuggestions();
            return;
        }
        if (matches.length)
            suggestionList.currentIndex = (suggestionList.currentIndex + delta + matches.length) % matches.length;
    }

    Component.onCompleted: restoreSelection()
    onSelectedNameChanged: restoreSelection()
    onContextKeyChanged: restoreSelection()
    onEnabledChanged: if (!enabled)
        restoreSelection()
    onVisibleChanged: if (!visible)
        suggestions.close()
    onTextEdited: updateSuggestions()
    onActiveFocusChanged: {
        if (activeFocus)
            selectAll();
        else
            restoreSelection();
    }
    Keys.onDownPressed: event => {
        moveSuggestion(1);
        event.accepted = true;
    }
    Keys.onUpPressed: event => {
        moveSuggestion(-1);
        event.accepted = true;
    }
    Keys.onReturnPressed: event => {
        submit();
        event.accepted = true;
    }
    Keys.onEnterPressed: event => {
        submit();
        event.accepted = true;
    }
    Keys.onEscapePressed: event => {
        if (suggestions.opened || text !== selectedName) {
            restoreSelection();
            event.accepted = true;
        } else {
            event.accepted = false;
        }
    }

    ToolButton {
        id: clearButton
        objectName: field.objectName + "Clear"
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: 28
        height: parent.height
        visible: field.text.length > 0 || field.selectedId.length > 0
        text: "×"
        focusPolicy: Qt.NoFocus
        Accessible.name: "Снять назначение персонажа"
        ToolTip.visible: hovered
        ToolTip.text: Accessible.name
        onClicked: field.choose({
            id: "",
            name: ""
        })
    }
    Popup {
        id: suggestions
        objectName: field.objectName + "Suggestions"
        y: field.height + 4
        width: field.width
        height: Math.max(1, Math.min(8, field.matches.length)) * 36 + topPadding + bottomPadding
        focus: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: field.text = field.selectedName
        contentItem: ListView {
            id: suggestionList
            objectName: field.objectName + "Matches"
            clip: true
            model: field.matches
            onCurrentIndexChanged: if (currentIndex >= 0)
                positionViewAtIndex(currentIndex, ListView.Contain)
            ScrollBar.vertical: ScrollBar {}
            delegate: DialogItemDelegate {
                required property var modelData
                required property int index
                width: suggestionList.width
                height: 36
                text: modelData.create ? "＋ Создать персонажа «" + modelData.name + "»" : modelData.name
                highlighted: index === suggestionList.currentIndex
                focusPolicy: Qt.NoFocus
                onClicked: field.choose(modelData)
            }
            Label {
                anchors.fill: parent
                visible: !field.matches.length
                text: "Персонаж не найден в глоссарии"
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
            }
        }
    }
}
