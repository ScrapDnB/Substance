import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: panel
    required property var colors
    property bool translationMode: backend.mode === "translation"
    property bool loading: true
    property string stagedText: ""
    property bool inheritancePending: false
    property bool keepFormatting: backend.preserveAssFormatting
    onKeepFormattingChanged: if (keepFormatting) panel.scheduleInheritance()
    readonly property var formatState: backend.current.exists ? backend.assFormattingState(editTextArea.text, editTextArea.selectionStart, editTextArea.selectionEnd) : ({})
    property int cursorPosition: editTextArea.cursorPosition
    signal editorCursorChanged(int position)
    signal composeRequested(string kind)
    readonly property var appearance: backend.appearance.general
    readonly property real uiScale: appearance.uiScale / 100
    readonly property real timecodeFieldWidth: Math.max(120, Math.ceil(timecodeMetrics.advanceWidth) + 24)
    TextMetrics {
        id: timecodeMetrics
        text: "88:88:88.888"
        font.family: backend.appearance.timecodeFamily
        font.bold: backend.appearance.timecodeBold
        font.pixelSize: panel.appearance.timecodeSize
    }
    padding: 0
    background: Rectangle { color: panel.colors.panel }

    function scheduleInheritance() {
        inheritancePending = true
        Qt.callLater(panel.applyPendingInheritance)
    }
    function applyPendingInheritance() {
        if (!inheritancePending) return
        inheritancePending = false
        syncInheritedFormatting()
    }
    function syncInheritedFormatting() {
        if (loading || !translationMode || !backend.current.exists) return
        let result = backend.prepareTranslationFormatting(editTextArea.text, editTextArea.selectionStart, editTextArea.selectionEnd, editTextArea.cursorPosition)
        if (result.text === editTextArea.text) return
        loading = true
        editTextArea.text = result.text
        if (result.start === result.end) editTextArea.cursorPosition = result.cursor
        else if (result.cursor === result.start) editTextArea.select(result.end, result.start)
        else editTextArea.select(result.start, result.end)
        stagedText = result.text
        loading = false
        backend.stage("text", result.text)
    }
    function stageText() {
        // Rehighlighting can emit textChanged without changing plain text.
        if (loading || editTextArea.text === stagedText) return
        stagedText = editTextArea.text
        backend.stage("text", editTextArea.text)
        // TextEdit finishes moving its cursor after textChanged during typing.
        scheduleInheritance()
    }
    function selectionChanged(area, field) {
        if (!loading && translationMode && backend.appearance.translation.contextVisible)
            backend.languageAssistance.selectText(area.text, area.selectionStart, area.selectionEnd, field)
    }
    function formatAss(kind) {
        let result = backend.applyAssFormat(editTextArea.text, editTextArea.selectionStart, editTextArea.selectionEnd, kind)
        if (result.text === undefined) return
        // Formatting controls act visually; raw codes remain available through
        // the explicit display toggle.
        if (!backend.assFormatted) backend.setAssFormatted(true)
        loading = true
        editTextArea.text = result.text
        editTextArea.forceActiveFocus()
        editTextArea.select(result.start, result.end)
        stagedText = result.text
        inheritancePending = false
        loading = false
    }
    Shortcut { sequence: backend.shortcuts.formatBold; enabled: editTextArea.activeFocus && !backend.busy; onActivated: panel.formatAss("b") }
    Shortcut { sequence: backend.shortcuts.formatItalic; enabled: editTextArea.activeFocus && !backend.busy; onActivated: panel.formatAss("i") }
    Shortcut { sequence: backend.shortcuts.formatUnderline; enabled: editTextArea.activeFocus && !backend.busy; onActivated: panel.formatAss("u") }

    function reload() {
        inheritancePending = false
        loading = true
        let cue = backend.current
        startField.text = cue.startTime
        endField.text = cue.endTime
        characterField.text = cue.character
        editTextArea.text = cue.editText
        stagedText = cue.editText
        loading = false
    }
    Component.onCompleted: {
        reload()
        backend.attachAssDocument(editTextArea.textDocument)
        backend.attachAssDocument(original.textDocument, true)
    }
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
        spacing: 0
        WorkspaceHeader {
            objectName: "cueEditorHeader"
            colors: panel.colors
            title: backend.current.exists ? "Реплика " + backend.current.number + " из " + backend.count : "Новая реплика"
            detail: backend.current.comment ? "ASS-комментарий" : ""
            Layout.fillWidth: true
            ControlButton { symbol: "chevron-left"; enabled: backend.currentIndex > 0; onClicked: backend.navigate(-1); hint: "Предыдущая реплика · " + backend.shortcutLabel("previous") }
            ControlButton { symbol: "chevron-right"; enabled: backend.currentIndex < backend.count - 1; onClicked: backend.navigate(1); hint: "Следующая реплика · " + backend.shortcutLabel("next") }
        }
        ScrollView {
            id: editorScroll
            objectName: "cueEditorScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: Math.round(14 * panel.uiScale)
            Layout.rightMargin: Math.round(14 * panel.uiScale)
            Layout.topMargin: Math.round(10 * panel.uiScale)
            Layout.bottomMargin: Math.round(10 * panel.uiScale)
            // Reserve a stable gutter: a width tied to scrollbar visibility
            // can oscillate when wrapped text changes the content height.
            rightPadding: Math.round(14 * panel.uiScale)
            bottomPadding: 0
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: editorScroll.availableWidth
                height: Math.max(editorScroll.availableHeight, implicitHeight)
                spacing: Math.round(8 * panel.uiScale)
                GridLayout {
                    objectName: "timecodeFieldsLayout"
                    Layout.fillWidth: true
                    columnSpacing: 10
                    rowSpacing: 8
                    columns: width >= 2 * panel.timecodeFieldWidth + Math.max(85, durationColumn.implicitWidth) + 20 ? 3 : width >= 2 * panel.timecodeFieldWidth + 10 ? 2 : 1
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Label { text: "Начало"; font.pixelSize: Math.round(12 * panel.uiScale); color: panel.colors.label }
                        TextField { id: startField; objectName: "startField"; Layout.fillWidth: true; Layout.minimumWidth: panel.timecodeFieldWidth; enabled: backend.current.exists; font.family: backend.appearance.timecodeFamily; font.bold: backend.appearance.timecodeBold; font.pixelSize: panel.appearance.timecodeSize; selectByMouse: true; onTextEdited: backend.stage("start", text); onEditingFinished: backend.flush(); Accessible.name: "Время начала реплики" }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Label { text: "Конец"; font.pixelSize: Math.round(12 * panel.uiScale); color: panel.colors.label }
                        TextField { id: endField; objectName: "endField"; Layout.fillWidth: true; Layout.minimumWidth: panel.timecodeFieldWidth; enabled: backend.current.exists; font.family: backend.appearance.timecodeFamily; font.bold: backend.appearance.timecodeBold; font.pixelSize: panel.appearance.timecodeSize; selectByMouse: true; onTextEdited: backend.stage("end", text); onEditingFinished: backend.flush(); Accessible.name: "Время конца реплики" }
                    }
                    ColumnLayout {
                        id: durationColumn
                        spacing: 3
                        Label { text: "Длительность"; font.pixelSize: Math.round(12 * panel.uiScale); color: panel.colors.label }
                        Label { text: Number(backend.current.duration || 0).toFixed(3) + " с"; color: panel.colors.text; font.pixelSize: Math.round(12 * panel.uiScale); Layout.minimumWidth: 66 }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Image { source: backend.currentPortraitUrl; Layout.preferredWidth: 28; Layout.preferredHeight: 32; fillMode: Image.PreserveAspectCrop; visible: source.toString().length > 0; MouseArea { anchors.fill: parent; onClicked: backend.openCharacters(backend.current.characterId) } }
                    Label { text: "Персонаж"; color: panel.colors.label; font.pixelSize: Math.round(12 * panel.uiScale) }
                    TextField { id: characterField; Layout.fillWidth: true; placeholderText: "Имя или роль"; enabled: backend.current.exists; onTextEdited: backend.stage("character", text); onEditingFinished: backend.flush(); Accessible.name: "Персонаж" }
                    Button { text: "Карточка…"; flat: true; enabled: backend.current.exists; onClicked: backend.openCharacters(backend.current.characterId || "") }
                }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: panel.colors.separator }
                GridLayout {
                    objectName: "editorTextLayout"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: panel.translationMode && backend.appearance.translation.originalBelow ? 200 : 120
                    Layout.preferredHeight: Layout.minimumHeight
                    columns: panel.translationMode && !backend.appearance.translation.originalBelow ? 2 : 1
                    columnSpacing: 12
                    rowSpacing: 8
                    ColumnLayout {
                        visible: panel.translationMode
                        Layout.preferredWidth: 1
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 5
                        GridLayout {
                            Layout.fillWidth: true
                            columns: width > 280 * panel.uiScale ? 2 : 1
                            rowSpacing: 0
                            Label { text: "Оригинал"; font.pixelSize: Math.round(12 * panel.uiScale); font.weight: Font.DemiBold; color: panel.colors.label; Layout.fillWidth: true }
                            CheckBox {
                                objectName: "originalAssFormattingToggle"
                                text: "Оформление"
                                font.pixelSize: Math.round(11 * panel.uiScale)
                                checked: backend.assOriginalFormatted
                                onClicked: backend.setAssOriginalFormatted(checked)
                                ToolTip.visible: hovered
                                ToolTip.text: "Показывать оформление ASS прямо в оригинале. Оригинал доступен только для чтения."
                            }
                        }
                        Item { Layout.fillWidth: true; Layout.preferredHeight: formattingTools.implicitHeight }
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumHeight: 48
                            contentWidth: availableWidth
                            rightPadding: Math.round(14 * panel.uiScale)
                            bottomPadding: 0
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            clip: true
                            DialogTextArea { id: original; textFormat: TextEdit.PlainText; objectName: "originalEditor"; text: backend.current.original; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; font.pixelSize: panel.appearance.originalFont; font.family: panel.appearance.textFamily || panel.font.family; color: panel.colors.editorText; palette.base: panel.colors.editorBackground
                                persistentSelection: true
                                onSelectionStartChanged: panel.selectionChanged(original, "original")
                                onSelectionEndChanged: panel.selectionChanged(original, "original")
                                Accessible.name: "Оригинальный текст" }
                        }
                    }
                    ColumnLayout {
                        Layout.preferredWidth: 1
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 5
                        GridLayout {
                            Layout.fillWidth: true
                            columns: width > 280 * panel.uiScale ? 2 : 1
                            rowSpacing: 0
                            Label { text: panel.translationMode ? "Перевод" : "Текст реплики"; font.pixelSize: Math.round(12 * panel.uiScale); font.weight: Font.DemiBold; color: panel.colors.label; Layout.fillWidth: true }
                            CheckBox {
                                objectName: "assFormattingToggle"
                                text: "Оформление"
                                font.pixelSize: Math.round(11 * panel.uiScale)
                                checked: backend.assFormatted
                                onClicked: backend.setAssFormatted(checked)
                                ToolTip.visible: hovered
                                ToolTip.text: "Скрыть коды тегов и показать жирный, курсив, подчёркивание и зачёркивание. Теги остаются в тексте и при копировании. Полное оформление ASS смотрите на видео."
                            }
                        }
                        RowLayout {
                            id: formattingTools
                            Layout.fillWidth: true
                            spacing: 4
                            AssFormatButton { editor: panel; tag: "b"; label: "Жирный"; command: "formatBold" }
                            AssFormatButton { editor: panel; tag: "i"; label: "Курсив"; command: "formatItalic" }
                            AssFormatButton { editor: panel; tag: "u"; label: "Подчёркивание"; command: "formatUnderline" }
                            AssFormatButton { editor: panel; tag: "s"; label: "Зачёркивание" }
                            Item { Layout.fillWidth: true }
                        }
                        ScrollView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumHeight: 48
                            contentWidth: availableWidth
                            rightPadding: Math.round(14 * panel.uiScale)
                            bottomPadding: 0
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            clip: true
                            DialogTextArea {
                                id: editTextArea
                                objectName: "subtitleEditor"
                                textFormat: TextEdit.PlainText
                                enabled: backend.current.exists
                                placeholderText: panel.translationMode ? "Введите перевод…" : "Введите текст…"
                                wrapMode: TextEdit.Wrap
                                selectByMouse: true
                                persistentSelection: true
                                font.pixelSize: panel.appearance.editorFont
                                font.family: panel.appearance.textFamily || panel.font.family
                                color: panel.colors.editorText
                                palette.base: panel.colors.editorBackground
                                selectionColor: panel.colors.selection
                                selectedTextColor: panel.colors.selectedText
                                onTextChanged: { panel.stageText(); panel.selectionChanged(editTextArea, "translation") }
                                onSelectionStartChanged: panel.selectionChanged(editTextArea, "translation")
                                onSelectionEndChanged: panel.selectionChanged(editTextArea, "translation")
                                onCursorPositionChanged: panel.editorCursorChanged(cursorPosition)
                                Accessible.name: panel.translationMode ? "Текст перевода" : "Текст реплики"
                            }
                        }
                    }
                }
                Rectangle { visible: checksToggle.checked || reviewsToggle.checked; Layout.fillWidth: true; implicitHeight: 1; color: panel.colors.separator }
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: checksToggle.checked || reviewsToggle.checked
                    spacing: 4
                    Label {
                        objectName: "cueChecksDetails"
                        visible: checksToggle.checked
                        Layout.fillWidth: true
                        Layout.margins: 4
                        text: backend.current.issues.length ? "⚠ " + backend.current.issues.join("\n⚠ ") : "Читаемость в норме"
                        color: backend.current.issues.length ? panel.colors.warning : panel.colors.label
                        font.pixelSize: Math.round(12 * panel.uiScale)
                        wrapMode: Text.Wrap
                        textFormat: Text.PlainText
                    }
                    ColumnLayout {
                        visible: reviewsToggle.checked
                        Layout.fillWidth: true
                        Label {
                            Layout.fillWidth: true
                            text: { let entry = backend.currentReviews.find(r => r.state === "open"); return entry ? (entry.kind === "note" ? "✎ " : "↔ ") + (entry.text || entry.replacement.replace(/\\N/g, " ")) : "Нет открытых заметок и предложений правок" }
                            textFormat: Text.PlainText
                            color: panel.colors.label
                            font.pixelSize: Math.round(12 * panel.uiScale)
                            wrapMode: Text.Wrap
                            maximumLineCount: 3
                            elide: Text.ElideRight
                        }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: width >= 500 * panel.uiScale ? 3 : 1
                            Button { text: "Все заметки и правки…"; Layout.fillWidth: true; onClicked: backend.openReviews() }
                            Button { text: "+ Заметка"; Layout.fillWidth: true; onClicked: panel.composeRequested("note") }
                            Button { text: "Предложить правку"; Layout.fillWidth: true; onClicked: panel.composeRequested("proposal") }
                        }
                    }
                }
            }
        }
        Pane {
            Layout.fillWidth: true
            padding: Math.round(10 * panel.uiScale)
            background: Rectangle {
                color: panel.colors.panelHeader
                Rectangle { width: parent.width; height: 1; color: panel.colors.separator }
            }
            ColumnLayout {
                anchors.fill: parent
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    Button {
                        id: checksToggle
                        objectName: "cueChecksToggle"
                        Layout.fillWidth: true
                        flat: true
                        checkable: true
                        onToggled: if (checked) Qt.callLater(() => { let view = editorScroll.contentItem; view.contentY = Math.max(0, view.contentHeight - view.height) })
                        text: (checked ? "▾  " : "▸  ") + "Проверка · " + (backend.current.issues.length ? backend.current.issues.length : "в норме")
                        palette.buttonText: backend.current.issues.length ? panel.colors.warning : panel.colors.label
                        Accessible.name: "Проверка текущей реплики"
                    }
                    Button {
                        id: reviewsToggle
                        objectName: "cueReviewsToggle"
                        Layout.fillWidth: true
                        flat: true
                        checkable: true
                        onToggled: if (checked) Qt.callLater(() => { let view = editorScroll.contentItem; view.contentY = Math.max(0, view.contentHeight - view.height) })
                        text: (checked ? "▾  " : "▸  ") + (panel.width < 520 * panel.uiScale ? "Заметки · " : "Заметки и правки · ") + backend.currentReviews.filter(r => r.state === "open").length
                        Accessible.name: "Заметки и предложения правок текущей реплики"
                        enabled: backend.current.exists && !backend.onlineSession.active
                    }
                }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: panel.colors.separator }
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: backend.current.cps + " зн/с"; color: backend.reviewSettings.readingSpeed && backend.current.cps > backend.cpsLimit ? panel.colors.warning : panel.colors.muted; font.pixelSize: Math.round(12 * panel.uiScale) }
                    Label { text: "Строка · " + (backend.current.maxLine || 0) + " / " + backend.lineLimit; visible: panel.width >= 450 * panel.uiScale; color: panel.colors.label; font.pixelSize: Math.round(12 * panel.uiScale); ToolTip.text: "Длина самой длинной строки / ограничение"; ToolTip.visible: metricHover.hovered; HoverHandler { id: metricHover } }
                    Item { Layout.fillWidth: true }
                    ControlButton { objectName: "playCueButton"; symbol: "play"; enabled: backend.media.hasMedia && backend.current.exists; onClicked: backend.playCurrent(false); hint: "Воспроизвести реплику · " + backend.shortcutLabel("playLine") }
                    ControlButton {
                        objectName: "applyCueButton"
                        text: (panel.translationMode ? "Применить и дальше" : "Применить") + (panel.width >= 500 * panel.uiScale ? "  " + backend.shortcutLabel("apply") : "")
                        enabled: backend.current.exists
                        highlighted: true
                        palette.buttonText: Qt.platform.os !== "osx" || (Window.active && enabled) ? panel.colors.accentText : panel.colors.text
                        onClicked: backend.apply(panel.translationMode)
                    }
                }
            }
        }
    }
}
