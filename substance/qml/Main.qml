import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Substance 1.0

ApplicationWindow {
    id: window
    objectName: "substanceWindow"
    width: 1440
    height: 940
    minimumWidth: 980
    minimumHeight: 650
    property var macOSIntegration: null
    property bool startupChromeReady: true
    readonly property bool nativeToolbar: macOSIntegration !== null && macOSIntegration.nativeToolbarActive
    readonly property bool modalOpen: settingsDialog.visible || spellingDialog.visible || findDialog.visible
                                     || assTagsDialog.visible || shiftDialog.visible || leadDialog.visible || actorDialog.visible
                                     || onlineConflictDialog.visible || onlineGlossaryDialog.visible || onlineWorkflowDialog.visible || reviewsDialog.visible || reviewCompose.visible || characterDialog.visible || portraitCropDialog.visible
    visible: startupChromeReady
    title: (backend.dirty ? "● " : "") + backend.title + " — Substance"
    font.pixelSize: 13
    SystemPalette { id: systemPalette }
    readonly property var nativeColors: macOSIntegration !== null ? macOSIntegration.platformPalette : ({})
    property bool dark: backend.theme === "dark" || (backend.theme === "system" && systemPalette.window.hslLightness < 0.5)
    property bool sidebarVisible: true
    property int editCursor: 0
    property var colors: ({
        dark: window.dark,
        text: nativeColors.text || systemPalette.text,
        muted: nativeColors.muted || Qt.alpha(systemPalette.windowText, 0.6),
        surface: nativeColors.surface || systemPalette.base,
        alternate: nativeColors.alternate || systemPalette.alternateBase,
        sidebar: nativeColors.sidebar || systemPalette.window,
        header: nativeColors.header || systemPalette.button,
        button: nativeColors.button || systemPalette.button,
        border: nativeColors.border || systemPalette.mid,
        selection: nativeColors.selection || systemPalette.highlight,
        selectedText: nativeColors.selectedText || systemPalette.highlightedText,
        accent: nativeColors.accent || systemPalette.highlight,
        warning: nativeColors.warning || (window.dark ? "#fbbb66" : "#ad6416"),
        success: nativeColors.success || (window.dark ? "#7ed6a4" : "#228657")
    })
    palette.window: colors.surface
    palette.windowText: colors.text
    palette.base: colors.surface
    palette.text: colors.text
    palette.buttonText: colors.text
    palette.button: colors.button
    palette.highlight: colors.accent
    palette.highlightedText: colors.selectedText
    color: colors.surface

    function closeAuxiliaryWindows() {
        assTagsDialog.close()
        notification.close()
        onlineConflictDialog.close()
        onlineGlossaryDialog.close()
        onlineWorkflowDialog.close()
        reviewCompose.close()
        portraitCropDialog.close()
        actorDialog.close()
        reviewsDialog.close()
        characterDialog.close()
        settingsDialog.close()
        spellingDialog.close()
        findDialog.close()
        shiftDialog.close()
        leadDialog.close()
    }
    onClosing: close => {
        close.accepted = backend.requestClose()
        if (close.accepted) closeAuxiliaryWindows()
    }
    Connections {
        target: backend.onlineSession
        function onCloseReady() { window.close() }
    }
    Connections {
        target: window.macOSIntegration
        function onSidebarRequested() { window.sidebarVisible = !window.sidebarVisible }
    }

    Action { id: newAction; text: "Новый документ"; shortcut: backend.shortcuts.new; enabled: !backend.busy; onTriggered: backend.newDocument() }
    Action { id: openAction; text: "Открыть…"; shortcut: backend.shortcuts.open; enabled: !backend.busy; onTriggered: backend.openDialog() }
    Action { id: saveAction; text: "Сохранить"; shortcut: backend.shortcuts.save; onTriggered: backend.save() }
    Action { id: saveAsAction; text: "Сохранить как…"; shortcut: backend.shortcuts.saveAs; onTriggered: backend.saveAs() }
    Action { id: exportAction; text: "Экспорт…"; shortcut: backend.shortcuts.export; onTriggered: backend.exportDialog(false) }
    Action { id: undoAction; text: "Отменить"; shortcut: backend.shortcuts.undo; enabled: backend.canUndo || backend.dirty; onTriggered: backend.undo() }
    Action { id: redoAction; text: "Повторить"; shortcut: backend.shortcuts.redo; enabled: backend.canRedo; onTriggered: backend.redo() }
    Action { id: findAction; text: "Найти…"; shortcut: backend.shortcuts.find; onTriggered: { findDialog.replaceMode = false; findDialog.open(); findInput.forceActiveFocus() } }
    Action { id: replaceAction; text: "Найти и заменить…"; shortcut: backend.shortcuts.replace; onTriggered: { findDialog.replaceMode = true; findDialog.open(); findInput.forceActiveFocus() } }
    Action { id: applyAction; text: "Применить / следующая реплика"; shortcut: backend.shortcuts.apply; enabled: backend.current.exists; onTriggered: backend.apply(backend.mode === "translation") }
    Action { id: addAction; text: "Добавить реплику"; shortcut: backend.shortcuts.newLine; onTriggered: backend.addLine() }
    Action { id: duplicateAction; text: "Дублировать выбранные"; shortcut: backend.shortcuts.duplicate; enabled: backend.current.exists; onTriggered: backend.duplicateLines() }
    Action { id: splitAction; text: "Разделить по курсору"; shortcut: backend.shortcuts.split; enabled: backend.current.exists; onTriggered: backend.splitLine(window.editCursor) }
    Action { id: mergeAction; text: "Объединить выбранные"; shortcut: backend.shortcuts.merge; enabled: backend.selectionCount > 1; onTriggered: backend.mergeLines() }
    Action { id: copyAction; text: "Скопировать реплики"; shortcut: backend.shortcuts.copyLines; enabled: backend.current.exists; onTriggered: backend.copyLines() }
    Action { id: pasteAction; text: "Вставить реплики"; shortcut: backend.shortcuts.pasteLines; onTriggered: backend.pasteLines() }
    Action { id: deleteAction; text: "Удалить выбранные"; shortcut: backend.shortcuts.deleteLines; enabled: backend.current.exists; onTriggered: backend.deleteLines() }
    Action { id: previousAction; text: "Предыдущая реплика"; shortcut: backend.shortcuts.previous; onTriggered: backend.navigate(-1) }
    Action { id: nextAction; text: "Следующая реплика"; shortcut: backend.shortcuts.next; onTriggered: backend.navigate(1) }
    Action { id: playAction; text: "Воспроизведение / пауза"; shortcut: backend.shortcuts.play; enabled: backend.media.hasMedia; onTriggered: backend.media.toggle() }
    Action { id: playLineAction; text: "Воспроизвести реплику"; shortcut: backend.shortcuts.playLine; enabled: backend.media.hasMedia && backend.current.exists; onTriggered: backend.playCurrent(false) }
    Action { id: setStartAction; text: "Начало по текущему кадру"; shortcut: backend.shortcuts.setStart; enabled: backend.current.exists && backend.media.hasMedia; onTriggered: backend.setEdge("start") }
    Action { id: setEndAction; text: "Конец по текущему кадру"; shortcut: backend.shortcuts.setEnd; enabled: backend.current.exists && backend.media.hasMedia; onTriggered: backend.setEdge("end") }
    Action { id: frameBackAction; text: "Предыдущий кадр"; shortcut: backend.shortcuts.frameBack; enabled: backend.media.hasMedia; onTriggered: backend.stepFrame(-1) }
    Action { id: frameForwardAction; text: "Следующий кадр"; shortcut: backend.shortcuts.frameForward; enabled: backend.media.hasMedia; onTriggered: backend.stepFrame(1) }
    Action { id: shiftAction; text: "Сдвиг времени…"; shortcut: backend.shortcuts.shift; enabled: backend.count > 0; onTriggered: shiftDialog.open() }
    Action { id: assignCharacterAction; text: "Назначить персонажа…"; shortcut: backend.shortcuts.assignCharacter; enabled: backend.current.exists && !backend.busy && !window.modalOpen; onTriggered: { if (backend.flush()) actorDialog.open() } }
    Action { id: quitAction; text: "Выйти из Substance"; shortcut: StandardKey.Quit; onTriggered: window.close() }
    Shortcut { sequence: "Space"; enabled: backend.media.hasMedia && !window.textInputFocused(); onActivated: backend.media.toggle() }

    function textInputFocused() {
        let item = activeFocusItem
        return item && (item.hasOwnProperty("cursorPosition") || item.hasOwnProperty("inputMethodComposing"))
    }

    menuBar: MenuBar {
        Menu {
            title: "Файл"
            MenuItem { action: newAction }
            MenuItem { action: openAction }
            Menu {
                id: recentMenu
                title: "Недавние файлы"
                enabled: backend.recentFiles.length > 0
                Instantiator {
                    model: backend.recentFiles
                    delegate: MenuItem { required property string modelData; text: modelData; onTriggered: backend.openPath(modelData) }
                    onObjectAdded: (index, object) => recentMenu.insertItem(index, object)
                    onObjectRemoved: (index, object) => recentMenu.removeItem(object)
                }
            }
            MenuSeparator { }
            MenuItem { action: saveAction }
            MenuItem { action: saveAsAction }
            MenuItem { action: exportAction }
            MenuItem { text: "Экспорт исходного текста…"; onTriggered: backend.exportDialog(true) }
            MenuSeparator { }
            MenuItem { text: "Открыть видео или аудио…"; onTriggered: backend.openMedia() }
            MenuItem { text: "Импорт субтитров из видео…"; onTriggered: backend.importEmbedded() }
            MenuSeparator { }
            MenuItem { action: Action { text: "Закрыть окно"; shortcut: StandardKey.Close; enabled: !window.modalOpen; onTriggered: window.close() } }
            MenuItem { action: quitAction; visible: !backend.isMac }
        }
        Menu {
            title: "Правка"
            MenuItem { action: undoAction }
            MenuItem { action: redoAction }
            MenuSeparator { }
            MenuItem { action: findAction }
            MenuItem { action: replaceAction }
            MenuItem {
                objectName: "useAssStylesMenuItem"
                text: "Учитывать стили ASS"
                checkable: true
                checked: backend.useAssStyles
                onTriggered: backend.setUseAssStyles(checked)
            }
            MenuItem {
                objectName: "preserveAssFormattingMenuItem"
                text: "Сохранять оформление"
                checkable: true
                checked: backend.preserveAssFormatting
                onTriggered: backend.setPreserveAssFormatting(checked)
            }
            MenuItem { text: "Удалить ASS-теги…"; enabled: backend.count > 0 && !backend.busy; onTriggered: { if (backend.flush()) assTagsDialog.open() } }
            MenuItem { text: "Заметки и предложения…"; enabled: !backend.onlineSession.active; onTriggered: backend.openReviews() }
            MenuItem { text: "Персонажи проекта…"; onTriggered: backend.openCharacters("") }
            MenuItem { text: "Проверить орфографию…"; onTriggered: spellingDialog.open() }
            MenuSeparator { }
            MenuItem { action: copyAction }
            MenuItem { action: pasteAction }
            MenuItem { text: "Выделить все реплики"; onTriggered: backend.selectAll() }
            MenuSeparator { }
            MenuItem { action: Action { text: "Настройки…"; shortcut: "Ctrl+,"; onTriggered: settingsDialog.open() } }
        }
        Menu {
            title: "Вид"
            MenuItem { text: "Боковая панель"; checkable: true; checked: window.sidebarVisible; onTriggered: window.sidebarVisible = !window.sidebarVisible }
            MenuItem { text: "Режим тайминга"; checkable: true; checked: backend.mode === "timing"; onTriggered: backend.setMode("timing") }
            MenuItem { text: "Режим перевода"; checkable: true; checked: backend.mode === "translation"; onTriggered: backend.setMode("translation") }
            MenuSeparator { }
            MenuItem { text: "Системная тема"; onTriggered: backend.preference("theme", "system") }
            MenuItem { text: "Светлая тема"; onTriggered: backend.preference("theme", "light") }
            MenuItem { text: "Тёмная тема"; onTriggered: backend.preference("theme", "dark") }
        }
        Menu {
            title: "Реплики"
            MenuItem { action: addAction }
            MenuItem { action: applyAction }
            MenuItem { action: duplicateAction }
            MenuItem { action: splitAction }
            MenuItem { action: mergeAction }
            MenuItem { action: deleteAction }
            MenuSeparator { }
            MenuItem { action: previousAction }
            MenuItem { action: nextAction }
            MenuSeparator { }
            MenuItem { action: assignCharacterAction }
            MenuItem { text: "Сортировать по началу"; onTriggered: backend.batch("sort", "", true) }
        }
        Menu {
            title: "Тайминг"
            MenuItem { action: playAction }
            MenuItem { action: playLineAction }
            MenuItem { action: frameBackAction }
            MenuItem { action: frameForwardAction }
            MenuSeparator { }
            MenuItem { action: setStartAction }
            MenuItem { action: setEndAction }
            MenuItem { action: shiftAction }
            MenuItem { text: "Округлить выбранные к кадрам"; onTriggered: backend.batch("frames", "", false) }
            MenuItem { text: "Добавить отступы…"; onTriggered: leadDialog.open() }
            MenuItem { text: "Убрать пересечения выбранных"; onTriggered: backend.batch("remove_overlap", "", false) }
        }
        Menu {
            title: "Справка"
            MenuItem { text: "Открыть пример"; onTriggered: backend.openExample() }
            MenuItem { text: "Замечания импорта…"; onTriggered: backend.showImportWarnings() }
            MenuItem { text: "О Substance…"; onTriggered: backend.about() }
        }
    }

    header: ToolBar {
        visible: !window.nativeToolbar
        implicitHeight: visible ? 50 : 0
        background: Rectangle { color: window.colors.surface }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 14
            spacing: 10
            ControlButton { symbol: "sidebar"; onClicked: window.sidebarVisible = !window.sidebarVisible; hint: "Показать или скрыть боковую панель" }
            Label { text: backend.title; font.bold: true; font.pixelSize: 14; color: window.colors.text; elide: Text.ElideRight; Layout.maximumWidth: 280 }
            Label { text: backend.onlineSession.active ? (backend.dirty ? "Изменено" : backend.onlineSession.pending ? "На компьютере" : "На сервере") : backend.dirty ? "Изменено" : "✓ Сохранено"; color: backend.dirty ? window.colors.muted : window.colors.success; font.pixelSize: 11 }
            Item { Layout.fillWidth: true }
            SegmentedSelector {
                id: modeTabs
                Layout.preferredWidth: 220
                labels: ["Тайминг", "Перевод"]
                selectedIndex: backend.mode === "translation" ? 1 : 0
                onActivated: index => backend.setMode(index ? "translation" : "timing")
                Accessible.name: "Режим редактора"
            }
            Item { Layout.fillWidth: true }
            Control {
                padding: 3
                implicitHeight: 36
                background: Item { }
                contentItem: RowLayout {
                    spacing: 5
                    ControlButton { text: "Открыть медиа…"; onClicked: backend.openMedia() }
                    ControlButton { text: "Экспорт…"; onClicked: backend.exportDialog(false) }
                }
            }
        }
    }

    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal
        handle: Rectangle { implicitWidth: 1; implicitHeight: 1; color: window.colors.border }
        Pane {
            id: sidebarPane
            visible: window.sidebarVisible
            SplitView.preferredWidth: glassSidebar.active ? 232 : 192
            SplitView.minimumWidth: glassSidebar.active ? 212 : 156
            SplitView.maximumWidth: 340
            padding: 10
            background: Rectangle { color: glassSidebar.active ? window.colors.surface : window.colors.sidebar }
            NativeGlassSidebar {
                id: glassSidebar
                objectName: "nativeGlassSidebar"
                // Native content floats in its reserved navigation area. The
                // table, text editor and media remain opaque Qt content.
                x: -2; y: -2
                width: sidebarPane.availableWidth + 4
                height: sidebarPane.availableHeight + 4
                integration: window.macOSIntegration
                obscured: window.modalOpen
            }
            ColumnLayout {
                visible: !glassSidebar.active || window.modalOpen
                anchors.fill: parent
                spacing: 4
                Label { text: "ДОКУМЕНТ"; color: window.colors.muted; font.pixelSize: 10; font.bold: true; Layout.margins: 8 }
                Repeater {
                    model: [ {key:"all", title:"Все реплики", symbol:"≡"}, {key:"warnings", title:"Замечания", symbol:"⚠"}, {key:"notes", title:"С заметками", symbol:"✎"}, {key:"proposals", title:"Предложения правок", symbol:"↔"}, {key:"characters", title:"Персонажи", symbol:"♙"} ]
                    delegate: ItemDelegate {
                        id: filterItem
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 32
                        highlighted: backend.activeFilter === modelData.key
                        background: Rectangle {
                            radius: 6
                            color: parent.highlighted ? window.colors.selection : parent.hovered ? window.colors.header : "transparent"
                            Behavior on color { ColorAnimation { duration: backend.motion ? 100 : 0 } }
                        }
                        onClicked: backend.setFilter(modelData.key)
                        contentItem: RowLayout {
                            spacing: 8
                            Label { text: modelData.symbol; color: filterItem.highlighted ? window.colors.selectedText : modelData.key === "warnings" ? window.colors.warning : window.colors.muted; Layout.preferredWidth: 18 }
                            Label { text: modelData.title; color: filterItem.highlighted ? window.colors.selectedText : window.colors.text; Layout.fillWidth: true; font.pixelSize: 12; elide: Text.ElideRight }
                            Label { text: backend.counts[modelData.key]; color: filterItem.highlighted ? window.colors.selectedText : window.colors.muted; font.pixelSize: 11 }
                        }
                    }
                }
                Label { text: "ПЕРСОНАЖ"; color: window.colors.muted; font.pixelSize: 10; font.bold: true; Layout.topMargin: 18; Layout.leftMargin: 8 }
                ComboBox { Layout.fillWidth: true; model: ["Все персонажи"].concat(backend.characters); onActivated: backend.setCharacterFilter(currentIndex ? currentText : "") }
                Rectangle { Layout.fillWidth: true; Layout.topMargin: 14; Layout.bottomMargin: 10; height: 1; color: window.colors.border }
                Label { text: "МЕДИА"; color: window.colors.muted; font.pixelSize: 10; font.bold: true; Layout.leftMargin: 8 }
                Label { text: backend.media.name; color: window.colors.text; font.pixelSize: 12; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true; Layout.margins: 8 }
                Label { text: backend.media.keyframeCount ? backend.media.keyframeCount + " ключевых кадров" : "Ключевые кадры не загружены"; color: window.colors.muted; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.fillWidth: true; Layout.leftMargin: 8 }
                Button { text: "Подключить…"; flat: true; onClicked: backend.openMedia() }
                Item { Layout.fillHeight: true }
                Label { text: "Substance " + backend.version; color: window.colors.muted; font.pixelSize: 10; Layout.leftMargin: 8; Layout.bottomMargin: 6 }
            }
        }
        Item {
            SplitView.fillWidth: true
            ColumnLayout {
                visible: backend.count === 0 && !backend.busy
                anchors.centerIn: parent
                width: Math.min(500, parent.width - 80)
                spacing: 18
                Label { text: "Substance"; font.pixelSize: 34; font.weight: Font.DemiBold; color: window.colors.text; Layout.alignment: Qt.AlignHCenter }
                Label { text: "Текст, перевод и точный тайминг"; font.pixelSize: 16; color: window.colors.muted; Layout.alignment: Qt.AlignHCenter }
                Label { text: "Создайте ASS с нуля или откройте готовые субтитры. Видео и аудио можно подключить в любой момент."; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; color: window.colors.muted; Layout.fillWidth: true }
                RowLayout { Layout.alignment: Qt.AlignHCenter; Button { objectName: "createFirstLine"; text: "Создать субтитры"; highlighted: true; onClicked: backend.addLine() } Button { text: "Открыть файл…"; onClicked: backend.openDialog() } }
                Button { text: "Открыть пример"; flat: true; Layout.alignment: Qt.AlignHCenter; onClicked: backend.openExample() }
                Label { text: "ASS · SRT · VTT · TXT · .substance\nИли перетащите файл в окно"; color: window.colors.muted; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 11; Layout.alignment: Qt.AlignHCenter }
            }
            BusyIndicator { running: backend.busy; anchors.centerIn: parent }
            SplitView {
                visible: backend.count > 0
                enabled: !backend.busy
                anchors.fill: parent
                orientation: Qt.Vertical
                handle: Rectangle { implicitHeight: 5; color: window.colors.header; Rectangle { width: 40; height: 2; radius: 1; color: window.colors.border; anchors.centerIn: parent } }
                Loader {
                    id: workspace
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 350
                    sourceComponent: backend.mode === "timing" ? timingWorkspace : translationWorkspace
                }
                AudioPane { visible: backend.mode === "translation"; colors: window.colors; SplitView.preferredHeight: 192; SplitView.minimumHeight: 145; SplitView.maximumHeight: 350 }
            }
        }
    }

    Component {
        id: timingWorkspace
        SplitView {
            orientation: Qt.Vertical
            handle: Rectangle { implicitHeight: 5; color: window.colors.header; Rectangle { width: 40; height: 2; color: window.colors.border; anchors.centerIn: parent } }
            SplitView {
                SplitView.preferredHeight: 400
                SplitView.minimumHeight: 240
                orientation: Qt.Horizontal
                handle: Rectangle { implicitWidth: 1; color: window.colors.border }
                VideoPane { colors: window.colors; SplitView.preferredWidth: workspace.width * 0.47; SplitView.minimumWidth: 280 }
                CueEditor { colors: window.colors; SplitView.fillWidth: true; SplitView.minimumWidth: 390; onEditorCursorChanged: position => window.editCursor = position; onComposeRequested: kind => reviewCompose.create(kind) }
            }
            AudioPane { colors: window.colors; SplitView.preferredHeight: 192; SplitView.minimumHeight: 145; SplitView.maximumHeight: 350 }
            SubtitleTable { colors: window.colors; SplitView.fillHeight: true; SplitView.minimumHeight: 130 }
        }
    }
    Component {
        id: translationWorkspace
        SplitView {
            orientation: Qt.Horizontal
            handle: Rectangle { implicitWidth: 1; color: window.colors.border }
            SplitView {
                SplitView.preferredWidth: workspace.width * 0.65
                SplitView.minimumWidth: 460
                orientation: Qt.Vertical
                handle: Rectangle { implicitHeight: 5; color: window.colors.header }
                SubtitleTable { colors: window.colors; SplitView.fillHeight: true; SplitView.minimumHeight: 130 }
                CueEditor { colors: window.colors; SplitView.preferredHeight: 395; SplitView.minimumHeight: 315; onEditorCursorChanged: position => window.editCursor = position; onComposeRequested: kind => reviewCompose.create(kind) }
            }
            ColumnLayout {
                SplitView.fillWidth: true
                SplitView.minimumWidth: 250
                spacing: 0
                VideoPane { colors: window.colors; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 190 }
                Pane {
                    Layout.fillWidth: true
                    padding: 16
                    background: Rectangle { color: window.colors.surface }
                    ColumnLayout {
                        width: parent.width
                        spacing: 12
                        Label { text: "Контекст"; color: window.colors.text; font.bold: true }
                        Repeater {
                            model: backend.contextLines
                            delegate: ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 3
                                Label { text: modelData.number + " · " + (modelData.character || "Без персонажа"); font.pixelSize: 10; color: window.colors.muted }
                                Label { text: modelData.text; color: modelData.active ? window.colors.accent : window.colors.text; wrapMode: Text.Wrap; font.pixelSize: 12; Layout.fillWidth: true; maximumLineCount: 3; elide: Text.ElideRight; textFormat: Text.PlainText }
                            }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: window.colors.border }
                        Label { text: "Проверка реплики"; font.bold: true; color: window.colors.text }
                        Label { text: backend.current.issues.length ? "⚠ " + backend.current.issues.join("\n⚠ ") : "✓ Читаемость в норме"; color: backend.current.issues.length ? window.colors.warning : window.colors.success; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 12 }
                    }
                }
            }
        }
    }

    footer: Rectangle {
        objectName: "documentStatusBar"
        height: backend.onlineSession.active ? 66 : 30
        color: window.colors.header
        Rectangle { width: parent.width; height: 1; color: window.colors.border }
        RowLayout {
            id: onlineStatus
            objectName: "onlineStatus"
            visible: backend.onlineSession.active
            enabled: backend.onlineSession.active
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 6
            height: 30
            Label { text: backend.onlineSession.status; Layout.fillWidth: true; elide: Text.ElideRight; color: window.colors.text; font.pixelSize: 11 }
            Button { objectName: "onlineCompareButton"; text: "Сравнить версии…"; visible: backend.onlineSession.conflictSession.available; enabled: !backend.onlineSession.busy; onClicked: onlineConflictDialog.open() }
            Button { objectName: "onlineGlossaryButton"; text: "Глоссарий…"; visible: backend.onlineSession.glossarySession.supported; onClicked: onlineGlossaryDialog.open() }
            Button { text: "Повторить"; enabled: !backend.onlineSession.busy; onClicked: backend.onlineSession.retry() }
            Button { text: "Начать перевод"; visible: backend.onlineSession.canStartTranslation; enabled: !backend.onlineSession.busy; onClicked: backend.onlineSession.workflow("start_translation", "") }
            Button { text: "Сдать перевод"; visible: backend.onlineSession.canSubmit; enabled: !backend.onlineSession.busy && !backend.onlineSession.pending; onClicked: backend.onlineSession.workflow("submit_translation", "") }
            Button { text: "Начать редактуру"; visible: backend.onlineSession.canReview; enabled: !backend.onlineSession.busy && !backend.onlineSession.pending; onClicked: backend.onlineSession.workflow("start_review", "") }
            Button { text: "Вернуть на доработку…"; visible: backend.onlineSession.canReturn; enabled: !backend.onlineSession.busy && !backend.onlineSession.pending && !backend.onlineSession.reviewSession.pending; onClicked: onlineWorkflowDialog.beginAction("return") }
            Button { text: "Переоткрыть…"; visible: backend.onlineSession.canReopenWork; enabled: !backend.onlineSession.busy && !backend.onlineSession.pending && !backend.onlineSession.reviewSession.pending; onClicked: onlineWorkflowDialog.beginAction("reopen") }
            Button { text: "Принять"; visible: backend.onlineSession.canAccept; enabled: !backend.onlineSession.busy && !backend.onlineSession.pending; onClicked: backend.onlineSession.workflow("accept", "") }
        }
        RowLayout {
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            height: 30
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 16
            Label { text: backend.current.exists ? backend.current.number + " из " + backend.count : backend.count + " реплик"; color: window.colors.muted; font.pixelSize: 11 }
            Label { text: "ASS · " + backend.encoding.toUpperCase() + " · " + Number(backend.fps).toFixed(3) + " fps"; color: window.colors.muted; font.pixelSize: 11 }
            Label { text: backend.selectionCount > 1 ? "Выбрано " + backend.selectionCount : backend.message; Layout.fillWidth: true; color: window.colors.muted; font.pixelSize: 11; elide: Text.ElideRight }
            Label { text: backend.shortcutLabel("apply") + " — применить"; color: window.colors.muted; font.pixelSize: 10 }
        }
    }

    DropArea {
        anchors.fill: parent
        onDropped: drop => {
            if (!drop.hasUrls || !drop.urls.length) return
            let path = drop.urls[0].toString()
            if (/\.(mkv|mp4|mov|avi|webm|wav|mp3|flac|m4a|ogg)$/i.test(path)) backend.openMediaPath(path)
            else backend.openPath(path)
        }
    }
    OnlineConflictDialog { id: onlineConflictDialog; objectName: "onlineConflictDialog"; colors: window.colors }
    OnlineGlossaryDialog { id: onlineGlossaryDialog; objectName: "onlineGlossaryDialog"; colors: window.colors }
    OnlineWorkflowDialog { id: onlineWorkflowDialog; objectName: "onlineWorkflowDialog"; colors: window.colors }
    ReviewCompose { id: reviewCompose; objectName: "reviewComposeDialog"; transientParent: reviewsDialog.visible ? reviewsDialog : window; colors: window.colors }
    ReviewsDialog { id: reviewsDialog; objectName: "reviewsDialog"; colors: window.colors; onComposeRequested: kind => reviewCompose.create(kind); onEditRequested: entry => reviewCompose.edit(entry) }
    CharacterDialog { id: characterDialog; objectName: "characterDialog"; colors: window.colors }
    PortraitCropDialog { id: portraitCropDialog; objectName: "portraitCropDialog"; transientParent: characterDialog.visible ? characterDialog : window; colors: window.colors }
    Connections {
        target: backend
        function onReviewsRequested() { reviewsDialog.open() }
        function onCardsRequested(cardId) {
            if (backend.onlineSession.active && backend.onlineSession.glossarySession.supported) {
                let session = backend.onlineSession.glossarySession
                if (!session.draft.data && cardId) session.begin(cardId, "character")
                onlineGlossaryDialog.open()
                onlineGlossaryDialog.loadDraft()
            } else { characterDialog.open(); characterDialog.reload() }
        }
        function onCropRequested() { portraitCropDialog.open() }
        function onDocumentReplaced() { onlineConflictDialog.close(); onlineGlossaryDialog.close(); characterDialog.modified = false; characterDialog.close(); portraitCropDialog.close(); reviewsDialog.close(); reviewCompose.close(); onlineWorkflowDialog.close(); actorDialog.close() }
    }

    SettingsDialog { id: settingsDialog; objectName: "settingsDialog"; colors: window.colors }

    NativeDialog {
        colors: window.colors
        id: spellingDialog
        objectName: "spellingDialog"
        title: "Орфография"
        modal: true
        preferredWidth: 760
        preferredHeight: 520
        standardButtons: Dialog.Close
        ColumnLayout {
            anchors.fill: parent
            RowLayout {
                ComboBox { id: spellingLanguage; model: ["Русский", "English"]; Layout.preferredWidth: 150 }
                Button { text: "Проверить документ"; enabled: !backend.spellingBusy; onClicked: backend.checkSpelling(spellingLanguage.currentIndex ? "en" : "ru") }
                BusyIndicator { running: backend.spellingBusy; Layout.preferredWidth: 30; Layout.preferredHeight: 30 }
            }
            Label { text: "Возможные опечатки: " + backend.spellingResults.length; color: window.colors.muted }
            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: backend.spellingResults
                ScrollBar.vertical: ScrollBar { }
                delegate: RowLayout {
                    required property var modelData
                    width: ListView.view.width
                    height: 44
                    Label { text: modelData.number.toString(); Layout.preferredWidth: 40; color: window.colors.muted }
                    Label { text: modelData.word; Layout.fillWidth: true; elide: Text.ElideRight; font.bold: true }
                    ComboBox { id: correction; model: modelData.suggestions; Layout.preferredWidth: 140 }
                    Button { text: "Исправить"; enabled: correction.count > 0; onClicked: backend.correctSpelling(modelData.index, modelData.word, correction.currentText) }
                    ControlButton { symbol: "arrow-up-right"; onClicked: { backend.locateSpelling(modelData.index, modelData.word); spellingDialog.close() } hint: "Перейти к слову" }
                    ControlButton { symbol: "plus"; onClicked: backend.ignoreSpelling(modelData.word); hint: "Добавить в словарь" }
                }
            }
            Label { text: "Проверка выполняется локально. Имена персонажей исключены из словаря ошибок."; color: window.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 11 }
        }
    }

    NativeDialog {
        colors: window.colors
        id: findDialog
        objectName: "findDialog"
        property bool replaceMode: false
        title: replaceMode ? "Найти и заменить" : "Найти"
        modal: true
        preferredWidth: 560
        standardButtons: Dialog.Close
        ColumnLayout {
            anchors.fill: parent
            spacing: 12
            DialogTextField { id: findInput; Layout.fillWidth: true; placeholderText: "Найти"; onAccepted: backend.setSearch(text, caseSensitive.checked, regex.checked) }
            DialogTextField { id: replacementInput; visible: findDialog.replaceMode; Layout.fillWidth: true; placeholderText: "Заменить на" }
            RowLayout { CheckBox { id: caseSensitive; text: "Учитывать регистр" } CheckBox { id: regex; text: "Регулярное выражение" } }
            CheckBox { id: selectedOnly; visible: findDialog.replaceMode; text: "Только в выбранных репликах" }
            RowLayout {
                Button { text: "Найти"; onClicked: backend.setSearch(findInput.text, caseSensitive.checked, regex.checked) }
                Button { text: "Следующая"; onClicked: { backend.setSearch(findInput.text, caseSensitive.checked, regex.checked); backend.navigate(1) } }
                Button { visible: findDialog.replaceMode; text: "Заменить все"; onClicked: backend.replace(findInput.text, replacementInput.text, regex.checked, caseSensitive.checked, selectedOnly.checked) }
                Button { text: "Сбросить"; onClicked: { backend.setSearch("", false, false); findDialog.close() } }
            }
        }
    }
    NativeDialog {
        colors: window.colors
        id: shiftDialog
        objectName: "shiftDialog"
        title: "Сдвиг времени"
        preferredWidth: 480
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: backend.shift(Number(shiftAmount.text), ["both", "start", "end"][shiftEdges.currentIndex], shiftAll.checked)
        ColumnLayout {
            anchors.fill: parent
            Label { text: "Сдвиг в миллисекундах · отрицательный — раньше"; wrapMode: Text.Wrap; Layout.fillWidth: true }
            DialogTextField { id: shiftAmount; text: "0"; validator: IntValidator { } }
            ComboBox { id: shiftEdges; model: ["Начало и конец", "Только начало", "Только конец"] }
            CheckBox { id: shiftAll; text: "Все реплики документа" }
            Label { text: "Некорректные интервалы отклоняются целиком."; font.pixelSize: 11; color: window.colors.muted }
        }
    }
    NativeDialog {
        colors: window.colors
        id: leadDialog
        objectName: "leadDialog"
        title: "Отступы тайминга"
        preferredWidth: 430
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: backend.batch("lead", leadIn.value + "," + leadOut.value, leadAll.checked)
        ColumnLayout { anchors.fill: parent; Label { text: "Вход, мс" } DialogSpinBox { id: leadIn; from: 0; to: 5000; value: 100; editable: true } Label { text: "Выход, мс" } DialogSpinBox { id: leadOut; from: 0; to: 5000; value: 200; editable: true } CheckBox { id: leadAll; text: "Все реплики документа" } }
    }
    AssTagsDialog {
        id: assTagsDialog
        colors: window.colors
    }
    AssignCharacterDialog {
        id: actorDialog
        objectName: "assignCharacterDialog"
        colors: window.colors
    }
    Popup {
        id: notification
        popupType: Popup.Item
        parent: Overlay.overlay
        // Keep toasts in the workspace, outside the native navigation layer.
        x: (parent.width + (window.sidebarVisible ? sidebarPane.width : 0) - width) / 2
        y: parent.height - height - 50
        width: Math.min(window.width - 50, 580)
        closePolicy: Popup.NoAutoClose
        property string message: ""
        background: Rectangle { color: window.colors.header; radius: 8; border.color: window.colors.border }
        contentItem: Label { text: notification.message; color: window.colors.text; wrapMode: Text.Wrap; font.pixelSize: 12 }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: backend.motion ? 120 : 0 } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: backend.motion ? 120 : 0 } }
        Timer { id: notificationTimer; interval: 3800; onTriggered: notification.close() }
    }
    Connections { target: backend; function onToast(message) { notification.message = message; notification.open(); notificationTimer.restart() } }
}
