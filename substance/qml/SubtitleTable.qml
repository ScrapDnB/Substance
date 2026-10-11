import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Substance 1.0

Item {
    id: table
    required property var colors
    property bool translationMode: backend.mode === "translation"
    property bool compact: width < 900
    property real numberWidth: 44
    property real timeWidth: compact ? 94 : 106
    property real actorWidth: compact ? 86 : 110
    property real statusWidth: 96
    property real textWidth: Math.max(100, width - numberWidth - timeWidth * (translationMode ? 1 : 2) - actorWidth - statusWidth - 16)

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Pane {
            Layout.fillWidth: true
            padding: 8
            background: Rectangle { color: table.colors.surface }
            RowLayout {
                anchors.fill: parent
                Label { text: backend.visibleCount + " реплик"; color: table.colors.muted; font.pixelSize: 12 }
                Item { Layout.fillWidth: true }
                TextField { id: searchField; objectName: "tableSearch"; Layout.preferredWidth: Math.min(300, table.width * 0.35); placeholderText: "Найти в репликах"; text: backend.search; onTextEdited: searchDelay.restart(); Accessible.name: "Поиск по репликам" }
                Timer { id: searchDelay; interval: 180; onTriggered: backend.setSearch(searchField.text, false, false) }
                ControlButton { symbol: "plus"; onClicked: backend.addLine(); hint: "Добавить реплику · " + backend.shortcutLabel("newLine") }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 29
            color: table.colors.header
            Row {
                anchors.fill: parent
                anchors.leftMargin: 8
                Label { width: table.numberWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "№"; font.pixelSize: 11; color: table.colors.muted }
                Label { width: table.timeWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: table.translationMode ? "Начало" : "Начало"; font.pixelSize: 11; color: table.colors.muted }
                Label { visible: !table.translationMode; width: table.timeWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "Конец"; font.pixelSize: 11; color: table.colors.muted }
                Label { width: table.actorWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "Персонаж"; font.pixelSize: 11; color: table.colors.muted }
                Label { width: table.translationMode ? table.textWidth / 2 : table.textWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: table.translationMode ? "Оригинал" : "Текст"; font.pixelSize: 11; color: table.colors.muted }
                Label { visible: table.translationMode; width: table.textWidth / 2; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "Перевод"; font.pixelSize: 11; color: table.colors.muted }
                Label { width: table.statusWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "Проверка"; font.pixelSize: 11; color: table.colors.muted }
            }
        }
        ListView {
            id: list
            objectName: "subtitleTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: backend.cues
            reuseItems: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { }
            keyNavigationEnabled: false
            Keys.onUpPressed: backend.navigate(-1)
            Keys.onDownPressed: backend.navigate(1)
            Keys.onDeletePressed: backend.deleteLines()
            delegate: Rectangle {
                id: row
                required property int sourceIndex
                required property int number
                required property string startTime
                required property string endTime
                required property string character
                required property string cueText
                required property string originalText
                required property string translatedText
                required property string reviewStatus
                required property real cps
                required property bool warning
                required property string issues
                required property bool selected
                required property bool comment
                width: list.width
                height: 35
                color: selected ? table.colors.selection : (sourceIndex % 2 ? table.colors.alternate : table.colors.surface)
                Rectangle { anchors.left: parent.left; width: 3; height: parent.height; color: table.colors.accent; visible: row.sourceIndex === backend.currentIndex }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: table.colors.border; opacity: 0.55 }
                Row {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    Label { width: table.numberWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.number; font.pixelSize: 12; color: row.selected ? table.colors.selectedText : table.colors.muted }
                    Label { width: table.timeWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.startTime; font.family: backend.isMac ? "Menlo" : "Consolas"; font.pixelSize: 10; color: row.selected ? table.colors.selectedText : table.colors.text }
                    Label { visible: !table.translationMode; width: table.timeWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.endTime; font.family: backend.isMac ? "Menlo" : "Consolas"; font.pixelSize: 10; color: row.selected ? table.colors.selectedText : table.colors.text }
                    Label { width: table.actorWidth; rightPadding: 8; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.character || "—"; font.pixelSize: 12; color: row.selected ? table.colors.selectedText : table.colors.text; elide: Text.ElideRight }
                    Label { width: table.translationMode ? table.textWidth / 2 : table.textWidth; rightPadding: 12; height: parent.height; verticalAlignment: Text.AlignVCenter; text: table.translationMode ? row.originalText : row.cueText; font.pixelSize: 12; color: row.selected ? table.colors.selectedText : row.comment ? table.colors.muted : table.colors.text; elide: Text.ElideRight; textFormat: Text.PlainText }
                    Label { visible: table.translationMode; width: table.textWidth / 2; rightPadding: 12; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.translatedText || "Без перевода"; font.pixelSize: 12; color: row.selected ? table.colors.selectedText : row.translatedText ? table.colors.text : table.colors.muted; elide: Text.ElideRight; textFormat: Text.PlainText }
                    Label { width: table.statusWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.warning ? "⚠ " + row.cps + " зн/с" : row.reviewStatus === "done" ? "✓ Готово" : row.reviewStatus === "review" ? "○ Проверить" : "○ Черновик"; font.pixelSize: 11; color: row.selected ? table.colors.selectedText : row.warning ? table.colors.warning : row.reviewStatus === "done" ? table.colors.success : table.colors.muted }
                }
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    hoverEnabled: true
                    onClicked: mouse => {
                        list.forceActiveFocus()
                        if (mouse.button === Qt.RightButton) {
                            if (!row.selected) backend.select(row.sourceIndex, 0)
                            contextMenu.popup()
                        } else backend.select(row.sourceIndex, mouse.modifiers)
                    }
                    onDoubleClicked: { backend.seekCurrent(); backend.focusEditor() }
                    NativeToolTip { enabled: row.warning; text: row.issues }
                }
            }
            Label { anchors.centerIn: parent; visible: backend.visibleCount === 0 && backend.count > 0; text: "Реплик по этому фильтру нет"; color: table.colors.muted }
        }
    }
    Connections {
        target: backend
        function onCurrentChanged() {
            if (backend.currentVisible >= 0) list.positionViewAtIndex(backend.currentVisible, ListView.Contain)
        }
    }
    Menu {
        id: contextMenu
        MenuItem { text: "Добавить реплику"; onTriggered: backend.addLine() }
        MenuItem { text: "Дублировать"; onTriggered: backend.duplicateLines() }
        MenuItem { text: "Объединить выбранные"; enabled: backend.selectionCount > 1; onTriggered: backend.mergeLines() }
        MenuSeparator { }
        MenuItem { text: "Скопировать реплики"; onTriggered: backend.copyLines() }
        MenuItem { text: "Вставить реплики"; onTriggered: backend.pasteLines() }
        MenuSeparator { }
        MenuItem { text: "Готово"; onTriggered: backend.batch("status", "done", false) }
        MenuItem { text: "На проверку"; onTriggered: backend.batch("status", "review", false) }
        MenuItem { text: "Черновик"; onTriggered: backend.batch("status", "draft", false) }
        MenuItem { text: "Сделать комментарием"; onTriggered: backend.batch("comment", "true", false) }
        MenuItem { text: "Сделать диалогом"; onTriggered: backend.batch("comment", "false", false) }
        MenuSeparator { }
        MenuItem { text: "Удалить выбранные"; onTriggered: backend.deleteLines() }
    }
}
