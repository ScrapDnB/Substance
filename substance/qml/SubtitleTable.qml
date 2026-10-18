import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Substance 1.0

Item {
    id: table
    required property var colors
    readonly property var appearance: backend.appearance.general
    readonly property string fontFamily: Qt.application.font.family
    readonly property real uiScale: appearance.uiScale / 100
    property bool translationMode: backend.mode === "translation"
    property bool compact: width < 900
    property real numberWidth: Math.round(44 * Math.max(1, appearance.tableFont / 12))
    property real timeWidth: Math.max(compact ? 94 : 106, Math.ceil(timecodeMetrics.advanceWidth) + 14)
    property real actorWidth: Math.round((compact ? 86 : 110) * Math.max(1, appearance.tableFont / 12))
    readonly property real portraitWidth: Math.round(44 * uiScale)
    readonly property real portraitSize: Math.round(28 * uiScale)
    property real statusWidth: 96
    property real textWidth: Math.max(100, tableColumns.width - numberWidth - timeWidth * (translationMode ? 1 : 2) - portraitWidth - actorWidth - statusWidth - 16)
    function showPortrait(url, character) {
        if (!url) return
        portraitPreview.portraitUrl = url
        portraitPreview.title = character ? "Портрет · " + character : "Портрет"
        portraitPreview.open()
    }
    TextMetrics {
        id: timecodeMetrics
        text: "88:88:88.888"
        font.family: backend.appearance.timecodeFamily
        font.bold: backend.appearance.timecodeBold
        font.pixelSize: table.appearance.timecodeSize
    }
    Rectangle { anchors.fill: parent; color: table.colors.surface }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        WorkspaceHeader {
            objectName: "tablePanelHeader"
            colors: table.colors
            title: "Реплики"
            detail: backend.visibleCount === backend.count ? backend.count + " всего" : backend.visibleCount + " из " + backend.count
            Layout.fillWidth: true
            TextField { id: searchField; objectName: "tableSearch"; Layout.preferredWidth: Math.min(300, table.width * 0.35); placeholderText: "Найти в репликах"; text: backend.search; onTextEdited: searchDelay.restart(); Accessible.name: "Поиск по репликам" }
            Timer { id: searchDelay; interval: 180; onTriggered: backend.setSearch(searchField.text, false, false) }
            ControlButton { symbol: "plus"; onClicked: backend.addLine(); hint: "Добавить реплику · " + backend.shortcutLabel("newLine") }
        }
        Flickable {
            id: tableViewport
            objectName: "tableHorizontalViewport"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: tableColumns.width
            contentHeight: height
            flickableDirection: Flickable.HorizontalFlick
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
            ColumnLayout {
                id: tableColumns
                width: Math.max(tableViewport.width, table.numberWidth + table.timeWidth * (table.translationMode ? 1 : 2) + table.portraitWidth + table.actorWidth + table.statusWidth + (table.translationMode ? 300 : 180) + 16)
                height: tableViewport.height - (width > tableViewport.width ? 12 : 0)
                spacing: 0
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.round(29 * table.uiScale)
                    color: table.colors.panelHeader
                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        Label { width: table.numberWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "№"; font.pixelSize: Math.round(12 * table.uiScale); font.weight: Font.Medium; color: table.colors.label }
                        Label { width: table.timeWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: table.translationMode ? "Начало" : "Начало"; font.pixelSize: Math.round(12 * table.uiScale); font.weight: Font.Medium; color: table.colors.label }
                        Label { visible: !table.translationMode; width: table.timeWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "Конец"; font.pixelSize: Math.round(12 * table.uiScale); font.weight: Font.Medium; color: table.colors.label }
                        Label { width: table.portraitWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "Фото"; font.pixelSize: Math.round(12 * table.uiScale); font.weight: Font.Medium; color: table.colors.label }
                        Label { width: table.actorWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "Персонаж"; font.pixelSize: Math.round(12 * table.uiScale); font.weight: Font.Medium; color: table.colors.label }
                        Label { width: table.translationMode ? table.textWidth / 2 : table.textWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: table.translationMode ? "Оригинал" : "Текст"; font.pixelSize: Math.round(12 * table.uiScale); font.weight: Font.Medium; color: table.colors.label }
                        Label { visible: table.translationMode; width: table.textWidth / 2; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "Перевод"; font.pixelSize: Math.round(12 * table.uiScale); font.weight: Font.Medium; color: table.colors.label }
                        Label { width: table.statusWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "Замечания"; font.pixelSize: Math.round(12 * table.uiScale); font.weight: Font.Medium; color: table.colors.label }
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
                        required property string portraitUrl
                        required property string cueText
                        required property string originalText
                        required property string translatedText
                        required property int noteCount
                        required property int proposalCount
                        required property real cps
                        required property bool warning
                        required property string issues
                        required property bool selected
                        required property bool comment
                        width: list.width
                        height: Math.max(table.appearance.rowHeight, table.appearance.tableFont + 16, timecodeMetrics.height + 12, table.appearance.wrapRows ? Math.max(cueMeasure.implicitHeight, table.translationMode ? translationMeasure.implicitHeight : 0) + 12 : 0)
                        color: selected ? table.colors.selection : (table.appearance.stripedRows && sourceIndex % 2 ? table.colors.alternate : table.colors.surface)
                        Text { id: cueMeasure; visible: false; width: Math.max(1, cueLabel.width - 12); text: table.appearance.wrapRows ? cueLabel.text : ""; font: cueLabel.font; wrapMode: Text.Wrap; textFormat: Text.PlainText }
                        Text { id: translationMeasure; visible: false; width: Math.max(1, translationLabel.width - 12); text: table.appearance.wrapRows && table.translationMode ? translationLabel.text : ""; font: translationLabel.font; wrapMode: Text.Wrap; textFormat: Text.PlainText }
                        Rectangle { anchors.left: parent.left; width: 3; height: parent.height; color: table.colors.accent; visible: row.sourceIndex === backend.currentIndex }
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; visible: table.appearance.rowLines; color: table.colors.border; opacity: 0.55 }
                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            Label { width: table.numberWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.number; font.pixelSize: table.appearance.tableFont; font.family: table.appearance.textFamily || table.fontFamily; color: row.selected ? table.colors.selectedText : table.colors.muted }
                            Label { width: table.timeWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.startTime; font.family: backend.appearance.timecodeFamily; font.bold: backend.appearance.timecodeBold; font.pixelSize: table.appearance.timecodeSize; color: row.selected ? table.colors.selectedText : table.colors.text }
                            Label { visible: !table.translationMode; width: table.timeWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.endTime; font.family: backend.appearance.timecodeFamily; font.bold: backend.appearance.timecodeBold; font.pixelSize: table.appearance.timecodeSize; color: row.selected ? table.colors.selectedText : table.colors.text }
                            Item {
                                width: table.portraitWidth
                                height: parent.height
                                Image {
                                    id: portraitImage
                                    objectName: "cuePortrait_" + row.sourceIndex
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: Math.min(table.portraitSize, parent.height - 8)
                                    height: width
                                    source: row.portraitUrl
                                    sourceSize: Qt.size(Math.round(width * Screen.devicePixelRatio), Math.round(height * Screen.devicePixelRatio))
                                    fillMode: Image.PreserveAspectCrop
                                    clip: true
                                    visible: source.toString().length > 0
                                    activeFocusOnTab: visible
                                    Accessible.name: "Увеличить портрет: " + row.character
                                    Accessible.role: Accessible.Button
                                    Accessible.onPressAction: table.showPortrait(row.portraitUrl, row.character)
                                    Keys.onReturnPressed: table.showPortrait(row.portraitUrl, row.character)
                                    Keys.onSpacePressed: table.showPortrait(row.portraitUrl, row.character)
                                }
                            }
                            Label { width: table.actorWidth; rightPadding: 8; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.character || "—"; font.pixelSize: table.appearance.tableFont; font.family: table.appearance.textFamily || table.fontFamily; color: row.selected ? table.colors.selectedText : table.colors.text; elide: Text.ElideRight }
                            Label { id: cueLabel; width: table.translationMode ? table.textWidth / 2 : table.textWidth; rightPadding: 12; height: parent.height; verticalAlignment: Text.AlignVCenter; text: table.translationMode ? row.originalText : row.cueText; font.pixelSize: table.appearance.tableFont; font.family: table.appearance.textFamily || table.fontFamily; color: row.selected ? table.colors.selectedText : row.comment ? table.colors.muted : table.colors.text; wrapMode: table.appearance.wrapRows ? Text.Wrap : Text.NoWrap; elide: table.appearance.wrapRows ? Text.ElideNone : Text.ElideRight; textFormat: Text.PlainText }
                            Label { id: translationLabel; visible: table.translationMode; width: table.textWidth / 2; rightPadding: 12; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.translatedText || "—"; font.pixelSize: table.appearance.tableFont; font.family: table.appearance.textFamily || table.fontFamily; color: row.selected ? table.colors.selectedText : row.translatedText ? table.colors.text : table.colors.muted; wrapMode: table.appearance.wrapRows ? Text.Wrap : Text.NoWrap; elide: table.appearance.wrapRows ? Text.ElideNone : Text.ElideRight; textFormat: Text.PlainText }
                            Label { width: table.statusWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: (row.warning ? "⚠ " : "") + (row.noteCount ? "✎ " + row.noteCount + " " : "") + (row.proposalCount ? "↔ " + row.proposalCount : ""); font.pixelSize: Math.round(11 * table.uiScale); color: row.selected ? table.colors.selectedText : row.warning ? table.colors.warning : table.colors.muted }
                        }
                        MouseArea {
                            id: rowMouse
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            hoverEnabled: true
                            function overPortrait(x, y) {
                                if (!row.portraitUrl) return false
                                let point = mapToItem(portraitImage, x, y)
                                return point.x >= 0 && point.y >= 0 && point.x < portraitImage.width && point.y < portraitImage.height
                            }
                            cursorShape: containsMouse && overPortrait(mouseX, mouseY) ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: mouse => {
                                if (mouse.button === Qt.LeftButton && overPortrait(mouse.x, mouse.y)) {
                                    table.showPortrait(row.portraitUrl, row.character)
                                    return
                                }
                                list.forceActiveFocus()
                                if (mouse.button === Qt.RightButton) {
                                    if (!row.selected) backend.select(row.sourceIndex, 0)
                                    contextMenu.popup()
                                } else backend.select(row.sourceIndex, mouse.modifiers)
                            }
                            onDoubleClicked: mouse => {
                                if (overPortrait(mouse.x, mouse.y)) return
                                backend.seekCurrent(); backend.focusEditor()
                            }
                            NativeToolTip { enabled: row.warning || rowMouse.overPortrait(rowMouse.mouseX, rowMouse.mouseY); text: rowMouse.overPortrait(rowMouse.mouseX, rowMouse.mouseY) ? "Увеличить портрет" : row.issues }
                        }
                    }
                    Label { anchors.centerIn: parent; visible: backend.visibleCount === 0 && backend.count > 0; text: "Реплик по этому фильтру нет"; color: table.colors.muted }
                }
            }
        }
    }
    Connections {
        target: backend
        function onDocumentReplaced() { portraitPreview.close() }
        function onCurrentChanged() {
            if (backend.currentVisible >= 0) list.positionViewAtIndex(backend.currentVisible, ListView.Contain)
        }
    }
    NativeDialog {
        id: portraitPreview
        objectName: "tablePortraitPreview"
        colors: table.colors
        property url portraitUrl: ""
        preferredWidth: 640
        preferredHeight: 680
        standardButtons: Dialog.Close
        onClosed: portraitUrl = ""
        Image {
            objectName: "tablePortraitPreviewImage"
            anchors.fill: parent
            source: portraitPreview.portraitUrl
            fillMode: Image.PreserveAspectFit
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
        MenuItem { text: "Заметки и предложения…"; onTriggered: backend.openReviews() }
        MenuItem { text: "Карточка персонажа…"; onTriggered: backend.openCharacters(backend.current.characterId || "") }
        MenuItem { text: "Сделать комментарием"; onTriggered: backend.batch("comment", "true", false) }
        MenuItem { text: "Сделать диалогом"; onTriggered: backend.batch("comment", "false", false) }
        MenuSeparator { }
        MenuItem { text: "Удалить выбранные"; onTriggered: backend.deleteLines() }
    }
}
