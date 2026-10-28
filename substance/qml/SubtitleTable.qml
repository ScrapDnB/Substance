import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Substance 1.0

Item {
    id: table
    objectName: "subtitleTablePanel"
    required property var colors
    readonly property var appearance: backend.appearance.general
    readonly property string fontFamily: Qt.application.font.family
    readonly property real uiScale: appearance.uiScale / 100
    property bool translationMode: backend.mode === "translation"
    property bool compact: width < 900
    readonly property string columnMode: translationMode ? "translation" : "timing"
    readonly property var columnWidths: backend.appearance.columnWidths[columnMode]
    readonly property var columnVisibility: backend.appearance.columnVisibility[columnMode]
    function columnVisible(key) { return columnVisibility[key] !== false }
    readonly property bool sourceShown: columnVisible(translationMode ? "original" : "text")
    readonly property bool translationShown: translationMode && columnVisible("translation")
    readonly property int visibleTextColumns: Math.max(1, (sourceShown ? 1 : 0) + (translationShown ? 1 : 0))
    readonly property var columnOptions: translationMode ? [
        {key: "number", title: "№"}, {key: "start", title: "Начало"},
        {key: "portrait", title: "Фото"}, {key: "actor", title: "Персонаж"},
        {key: "original", title: "Оригинал"}, {key: "translation", title: "Перевод"},
        {key: "remarks", title: "Заметки и замечания"}
    ] : [
        {key: "number", title: "№"}, {key: "start", title: "Начало"}, {key: "end", title: "Конец"},
        {key: "portrait", title: "Фото"}, {key: "actor", title: "Персонаж"},
        {key: "text", title: "Текст"}, {key: "remarks", title: "Заметки и замечания"}
    ]
    function columnWidth(key, automatic) { return columnWidths[key] === undefined ? automatic : columnWidths[key] * uiScale }
    function resizeColumn(key, value) { backend.appearance.setColumnWidth(columnMode, key, value / uiScale) }
    function resetColumn(key) { backend.appearance.resetColumnWidth(columnMode, key) }
    property real numberWidth: columnWidth("number", Math.round(44 * Math.max(1, appearance.tableFont / 12)))
    property real timeWidth: Math.max(compact ? 94 : 106, Math.ceil(timecodeMetrics.advanceWidth) + 14)
    readonly property real startWidth: columnWidth("start", timeWidth)
    readonly property real endWidth: columnWidth("end", timeWidth)
    property real actorWidth: columnWidth("actor", Math.round((compact ? 86 : 110) * Math.max(1, appearance.tableFont / 12)))
    readonly property real portraitWidth: columnWidth("portrait", Math.round(44 * uiScale))
    readonly property real portraitSize: Math.round(28 * uiScale)
    readonly property bool showRemarks: columnVisible("remarks") && (backend.checksEnabled || backend.hasDocumentRemarks || columnVisibility.remarks === true)
    property real statusWidth: showRemarks ? columnWidth("remarks", 96) : 0
    readonly property real fixedWidth: (columnVisible("number") ? numberWidth : 0) + (columnVisible("start") ? startWidth : 0) + (!translationMode && columnVisible("end") ? endWidth : 0) + (columnVisible("portrait") ? portraitWidth : 0) + (columnVisible("actor") ? actorWidth : 0) + statusWidth
    readonly property real automaticTextWidth: Math.max(translationMode ? 300 : 180, tableViewport.width - fixedWidth - 16)
    readonly property real sourceWidth: sourceShown ? columnWidth(translationMode ? "original" : "text", automaticTextWidth / visibleTextColumns) : 0
    readonly property real translatedWidth: translationShown ? columnWidth("translation", automaticTextWidth / visibleTextColumns) : 0
    property real textWidth: sourceWidth + translatedWidth
    readonly property real trailingSpace: Math.max(0, tableColumns.width - fixedWidth - textWidth - 16)
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
                width: Math.max(tableViewport.width, table.fixedWidth + table.textWidth + 16)
                height: tableViewport.height - (width > tableViewport.width ? 12 : 0)
                spacing: 0
                Rectangle {
                    id: columnHeader
                    objectName: "tableColumnsHeaderArea"
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.round(29 * table.uiScale)
                    color: table.colors.panelHeader
                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        TableColumnHeader { visible: table.columnVisible("number"); width: table.numberWidth; text: "№"; columnKey: "number"; colors: table.colors; resizeSurface: table; minimumColumnWidth: 32 * table.uiScale; onWidthRequested: value => table.resizeColumn(columnKey, value); onResetRequested: table.resetColumn(columnKey) }
                        TableColumnHeader { visible: table.columnVisible("start"); width: table.startWidth; text: "Начало"; columnKey: "start"; colors: table.colors; resizeSurface: table; minimumColumnWidth: 66 * table.uiScale; onWidthRequested: value => table.resizeColumn(columnKey, value); onResetRequested: table.resetColumn(columnKey) }
                        TableColumnHeader { visible: !table.translationMode && table.columnVisible("end"); width: table.endWidth; text: "Конец"; columnKey: "end"; colors: table.colors; resizeSurface: table; minimumColumnWidth: 66 * table.uiScale; onWidthRequested: value => table.resizeColumn(columnKey, value); onResetRequested: table.resetColumn(columnKey) }
                        TableColumnHeader { visible: table.columnVisible("portrait"); width: table.portraitWidth; text: "Фото"; columnKey: "portrait"; colors: table.colors; resizeSurface: table; minimumColumnWidth: 32 * table.uiScale; onWidthRequested: value => table.resizeColumn(columnKey, value); onResetRequested: table.resetColumn(columnKey) }
                        TableColumnHeader { visible: table.columnVisible("actor"); width: table.actorWidth; text: "Персонаж"; columnKey: "actor"; colors: table.colors; resizeSurface: table; minimumColumnWidth: 56 * table.uiScale; onWidthRequested: value => table.resizeColumn(columnKey, value); onResetRequested: table.resetColumn(columnKey) }
                        TableColumnHeader { visible: table.sourceShown; width: table.sourceWidth; text: table.translationMode ? "Оригинал" : "Текст"; columnKey: table.translationMode ? "original" : "text"; colors: table.colors; resizeSurface: table; minimumColumnWidth: 100 * table.uiScale; onWidthRequested: value => table.resizeColumn(columnKey, value); onResetRequested: table.resetColumn(columnKey) }
                        TableColumnHeader { visible: table.translationShown; width: table.translatedWidth; text: "Перевод"; columnKey: "translation"; colors: table.colors; resizeSurface: table; minimumColumnWidth: 100 * table.uiScale; onWidthRequested: value => table.resizeColumn(columnKey, value); onResetRequested: table.resetColumn(columnKey) }
                        Item { width: table.trailingSpace; height: parent.height }
                        TableColumnHeader { objectName: "tableRemarksHeader"; Accessible.name: "Замечания к репликам"; visible: table.showRemarks; width: table.statusWidth; text: ""; columnKey: "remarks"; colors: table.colors; resizeSurface: table; minimumColumnWidth: 44 * table.uiScale; onWidthRequested: value => table.resizeColumn(columnKey, value); onResetRequested: table.resetColumn(columnKey) }
                    }
                    MouseArea {
                        objectName: "tableColumnsMenuArea"
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        onClicked: columnMenu.popup()
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
                        Text { id: cueMeasure; visible: false; width: Math.max(1, cueLabel.width - 12); text: table.appearance.wrapRows && table.sourceShown ? cueLabel.text : ""; font: cueLabel.font; wrapMode: Text.Wrap; textFormat: Text.PlainText }
                        Text { id: translationMeasure; visible: false; width: Math.max(1, translationLabel.width - 12); text: table.appearance.wrapRows && table.translationShown ? translationLabel.text : ""; font: translationLabel.font; wrapMode: Text.Wrap; textFormat: Text.PlainText }
                        Rectangle { anchors.left: parent.left; width: 3; height: parent.height; color: table.colors.accent; visible: row.sourceIndex === backend.currentIndex }
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; visible: table.appearance.rowLines; color: table.colors.border; opacity: 0.55 }
                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            Label { objectName: "tableNumber_" + row.sourceIndex; visible: table.columnVisible("number"); elide: Text.ElideRight; width: table.numberWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.number; font.pixelSize: table.appearance.tableFont; font.family: table.appearance.textFamily || table.fontFamily; color: row.selected ? table.colors.selectedText : table.colors.muted }
                            Label { visible: table.columnVisible("start"); width: table.startWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: row.startTime; font.family: backend.appearance.timecodeFamily; font.bold: backend.appearance.timecodeBold; font.pixelSize: table.appearance.timecodeSize; color: row.selected ? table.colors.selectedText : table.colors.text }
                            Label { visible: !table.translationMode && table.columnVisible("end"); width: table.endWidth; height: parent.height; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; text: row.endTime; font.family: backend.appearance.timecodeFamily; font.bold: backend.appearance.timecodeBold; font.pixelSize: table.appearance.timecodeSize; color: row.selected ? table.colors.selectedText : table.colors.text }
                            Item {
                                visible: table.columnVisible("portrait")
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
                            Label { objectName: "tableActor_" + row.sourceIndex; visible: table.columnVisible("actor"); width: table.actorWidth; rightPadding: 8; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.character || "—"; font.pixelSize: table.appearance.tableFont; font.family: table.appearance.textFamily || table.fontFamily; color: row.selected ? table.colors.selectedText : table.colors.text; elide: Text.ElideRight }
                            Label { id: cueLabel; objectName: "tableSource_" + row.sourceIndex; visible: table.sourceShown; width: table.sourceWidth; rightPadding: 12; height: parent.height; verticalAlignment: Text.AlignVCenter; text: table.translationMode ? row.originalText : row.cueText; font.pixelSize: table.appearance.tableFont; font.family: table.appearance.textFamily || table.fontFamily; color: row.selected ? table.colors.selectedText : row.comment ? table.colors.muted : table.colors.text; wrapMode: table.appearance.wrapRows ? Text.Wrap : Text.NoWrap; elide: table.appearance.wrapRows ? Text.ElideNone : Text.ElideRight; textFormat: Text.PlainText }
                            Label { id: translationLabel; objectName: "tableTranslation_" + row.sourceIndex; visible: table.translationShown; width: table.translatedWidth; rightPadding: 12; height: parent.height; verticalAlignment: Text.AlignVCenter; text: row.translatedText || "—"; font.pixelSize: table.appearance.tableFont; font.family: table.appearance.textFamily || table.fontFamily; color: row.selected ? table.colors.selectedText : row.translatedText ? table.colors.text : table.colors.muted; wrapMode: table.appearance.wrapRows ? Text.Wrap : Text.NoWrap; elide: table.appearance.wrapRows ? Text.ElideNone : Text.ElideRight; textFormat: Text.PlainText }
                            Item { width: table.trailingSpace; height: parent.height }
                            Label { objectName: "tableRemarks_" + row.sourceIndex; visible: table.showRemarks; width: table.statusWidth; rightPadding: 8; elide: Text.ElideRight; height: parent.height; verticalAlignment: Text.AlignVCenter; text: (row.warning ? "⚠ " : "") + (row.noteCount ? "✎ " + row.noteCount + " " : "") + (row.proposalCount ? "↔ " + row.proposalCount : ""); font.pixelSize: Math.round(11 * table.uiScale); color: row.selected ? table.colors.selectedText : row.warning ? table.colors.warning : table.colors.muted }
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
                                backend.seekCurrent()
                                backend.centerWaveform()
                                backend.focusEditor()
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
        id: columnMenu
        objectName: "tableColumnsMenu"
        Instantiator {
            model: table.columnOptions
            delegate: MenuItem {
                required property var modelData
                objectName: "columnOption_" + modelData.key
                text: modelData.title
                checkable: true
                checked: table.columnVisible(modelData.key)
                onTriggered: backend.appearance.setColumnVisible(table.columnMode, modelData.key, checked)
            }
            onObjectAdded: (index, object) => columnMenu.insertItem(index, object)
            onObjectRemoved: (index, object) => columnMenu.removeItem(object)
        }
        MenuSeparator { }
        MenuItem { objectName: "showAllTableColumns"; text: "Показать все колонки"; onTriggered: backend.appearance.showAllColumns(table.columnMode) }
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
