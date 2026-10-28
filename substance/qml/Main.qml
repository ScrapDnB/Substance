import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Substance 1.0

ApplicationWindow {
    id: window
    signal closeAccepted()
    objectName: "substanceWindow"
    width: 1440
    height: 940
    minimumWidth: 980
    minimumHeight: 650
    property var macOSIntegration: null
    property bool startupChromeReady: true
    readonly property bool toolSection: backend.section === "preparation" || backend.section === "post"
    readonly property bool nativeToolbar: macOSIntegration !== null && macOSIntegration.nativeToolbarActive
    readonly property bool modalOpen: libreServerWizard.visible || hardsubDialog.visible || transcriptionDialog.visible || settingsDialog.visible || documentSettingsDialog.visible || spellingDialog.visible || findDialog.visible
                                     || assTagsDialog.visible || leadDialog.visible || actorDialog.visible
                                     || onlineConflictDialog.visible || onlineGlossaryDialog.visible || onlineWorkflowDialog.visible || reviewsDialog.visible || reviewCompose.visible || characterDialog.visible || portraitCropDialog.visible
                                     || shiftDialog.visible || autoPortraitsDialog.visible || editorToolsDialog.visible || alignmentDialog.visible
                                     || transferDialog.visible || timingProcessDialog.visible || scriptTimingDialog.visible || semanticTimingDialog.visible || batchDialog.visible || bitmapSubtitleDialog.visible || frameIndexDialog.visible
    visible: startupChromeReady
    title: (backend.dirty ? "● " : "") + backend.title + " — Substance"
    readonly property real uiScale: backend.appearance.general.uiScale / 100
    font.pixelSize: Math.round(13 * uiScale)
    SystemPalette { id: systemPalette }
    readonly property var nativeColors: macOSIntegration !== null ? macOSIntegration.platformPalette : ({})
    property bool dark: backend.theme === "dark" || (backend.theme === "system" && systemPalette.window.hslLightness < 0.5)
    readonly property bool sidebarVisible: appearance.sidebarVisible
    function toggleSidebar() { backend.appearance.setValue("general", "sidebarVisible", !sidebarVisible) }
    property int editCursor: 0
    readonly property bool timingShortcutsEnabled: backend.current.exists && !backend.busy && !modalOpen && !toolSection
    readonly property var appearance: backend.appearance.general
    readonly property var editorColors: window.dark ? backend.appearance.darkColors : backend.appearance.lightColors
    function selectionText(value) {
        let c = Qt.color(value)
        function linear(v) { return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
        return 0.2126 * linear(c.r) + 0.7152 * linear(c.g) + 0.0722 * linear(c.b) > 0.179 ? "#17191d" : "#ffffff"
    }
    property var colors: ({
        dark: window.dark,
        text: nativeColors.text || systemPalette.text,
        muted: nativeColors.muted || Qt.alpha(systemPalette.windowText, 0.6),
        surface: nativeColors.surface || systemPalette.base,
        workspace: window.dark ? Qt.darker(nativeColors.surface || systemPalette.base, 1.18) : Qt.darker(nativeColors.surface || systemPalette.base, 1.06),
        panel: window.dark ? Qt.lighter(nativeColors.surface || systemPalette.base, 1.16) : Qt.darker(nativeColors.surface || systemPalette.base, 1.015),
        panelHeader: window.dark ? Qt.lighter(nativeColors.surface || systemPalette.base, 1.3) : Qt.darker(nativeColors.surface || systemPalette.base, 1.045),
        separator: Qt.alpha(nativeColors.text || systemPalette.text, window.dark ? 0.18 : 0.15),
        label: Qt.alpha(nativeColors.text || systemPalette.text, 0.78),
        alternate: nativeColors.alternate || systemPalette.alternateBase,
        sidebar: nativeColors.sidebar || systemPalette.window,
        header: nativeColors.header || systemPalette.button,
        button: nativeColors.button || systemPalette.button,
        border: nativeColors.border || systemPalette.mid,
        selection: appearance.selectionColor || nativeColors.selection || systemPalette.highlight,
        selectedText: appearance.selectionColor ? selectionText(appearance.selectionColor) : nativeColors.selectedText || systemPalette.highlightedText,
        accent: appearance.accentColor || nativeColors.accent || systemPalette.highlight,
        accentText: appearance.accentColor ? selectionText(appearance.accentColor) : nativeColors.selectedText || systemPalette.highlightedText,
        wave: appearance.waveColor || nativeColors.text || systemPalette.text,
        editorBackground: editorColors.editorBackground || nativeColors.surface || systemPalette.base,
        editorText: editorColors.editorText || nativeColors.text || systemPalette.text,
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
    palette.highlightedText: appearance.accentColor ? selectionText(appearance.accentColor) : nativeColors.selectedText || systemPalette.highlightedText
    color: colors.surface


    function mountTool(tool, key) {
        if (window.toolSection) {
            let page = backend.section === "preparation" ? preparationPage : postPage
            page.embed(tool, key)
        } else tool.detachEmbedding()
    }
    function presentTool(tool, key) { mountTool(tool, key); tool.open() }
    function openWorkflowTool(key) {
        if (backend.busy || !backend.flush()) return
        switch (key) {
        case "files": case "delivery":
            fileWorkflowTool.delivery = key === "delivery"
            presentTool(fileWorkflowTool, key); break
        case "transcription": presentTool(transcriptionDialog, key); break
        case "hardsub": backend.openHardsub(); break
        case "bitmap": backend.bitmapSubtitles.open(); break
        case "forced": backend.openScriptTiming(); break
        case "semantic": backend.openSemanticTiming(); break
        case "scenes": backend.openScenes(); break
        case "frames": backend.frameIndex.open(); break
        case "compare": backend.fileTransfer.open("compare"); break
        case "characters": backend.openCharacters(""); break
        case "portraits": backend.openAutoPortraits(); break
        case "settings": presentTool(settingsDialog, key); break
        case "checks": backend.openChecks(); break
        case "spelling": presentTool(spellingDialog, key); break
        case "balance": backend.openReflow(); break
        case "retime": backend.openTimingProcessor(); break
        case "align": backend.openAlignment(); break
        case "points": backend.openPointSync(); break
        case "shift": backend.openShift(); break
        case "tags": presentTool(assTagsDialog, key); break
        case "batch": backend.batchFiles.open(); break
        }
    }
    WorkflowFilesTool { id: fileWorkflowTool; colors: window.colors }

    function closeAuxiliaryWindows() {
        documentSettingsDialog.dismiss()
        fileWorkflowTool.dismiss()
        libreServerWizard.dismiss()
        autoPortraitsDialog.dismiss()
        hardsubDialog.dismiss()
        editorToolsDialog.dismiss()
        alignmentDialog.dismiss()
        transferDialog.dismiss()
        timingProcessDialog.dismiss()
        scriptTimingDialog.dismiss()
        semanticTimingDialog.dismiss()
        batchDialog.dismiss()
        bitmapSubtitleDialog.dismiss()
        frameIndexDialog.dismiss()
        transcriptionDialog.dismiss()
        assTagsDialog.dismiss()
        notification.close()
        onlineConflictDialog.dismiss()
        onlineGlossaryDialog.dismiss()
        onlineWorkflowDialog.dismiss()
        reviewCompose.dismiss()
        portraitCropDialog.dismiss()
        actorDialog.dismiss()
        reviewsDialog.dismiss()
        characterDialog.dismiss()
        settingsDialog.dismiss()
        spellingDialog.dismiss()
        findDialog.dismiss()
        shiftDialog.dismiss()
        leadDialog.dismiss()
    }
    onClosing: close => {
        close.accepted = backend.requestClose()
        if (close.accepted) {
            closeAuxiliaryWindows()
            closeAccepted()
        }
    }
    Connections {
        target: backend.onlineSession
        function onCloseReady() { window.close() }
    }
    Connections {
        target: window.macOSIntegration
        function onSidebarRequested() { window.toggleSidebar() }
        function onSettingsRequested() { window.presentTool(settingsDialog, "settings") }
    }

    Action { id: newAction; text: "Новый документ"; shortcut: backend.shortcuts.new; enabled: !backend.busy; onTriggered: backend.newDocument() }
    Action { id: openAction; text: "Открыть…"; shortcut: backend.shortcuts.open; enabled: !backend.busy; onTriggered: backend.openDialog() }
    Action { id: saveAction; text: "Сохранить"; shortcut: backend.shortcuts.save; onTriggered: backend.save() }
    Action { id: saveAsAction; text: "Сохранить как…"; shortcut: backend.shortcuts.saveAs; onTriggered: backend.saveAs() }
    Action { id: exportAction; text: "Экспорт…"; shortcut: backend.shortcuts.export; onTriggered: backend.exportDialog(false) }
    Action { id: undoAction; text: "Отменить"; shortcut: backend.shortcuts.undo; enabled: backend.canUndo || backend.dirty; onTriggered: backend.undo() }
    Action { id: redoAction; text: "Повторить"; shortcut: backend.shortcuts.redo; enabled: backend.canRedo; onTriggered: backend.redo() }
    readonly property var clipboardTarget: {
        let item = activeFocusItem
        if (item && typeof item.copy === "function" && typeof item.paste === "function") return item
        return !window.toolSection && backend.current.exists ? cueEditor.textEditor : null
    }
    function editClipboard(command) {
        let target = clipboardTarget
        if (!target || (command !== "copy" && target.readOnly)) return
        target.forceActiveFocus()
        target[command]()
    }
    Action { id: cutTextAction; objectName: "cutTextAction"; text: "Вырезать"; shortcut: StandardKey.Cut; enabled: !window.modalOpen && window.clipboardTarget !== null && !window.clipboardTarget.readOnly && window.clipboardTarget.selectedText.length > 0; onTriggered: window.editClipboard("cut") }
    Action { id: copyTextAction; objectName: "copyTextAction"; text: "Копировать"; shortcut: StandardKey.Copy; enabled: !window.modalOpen && window.clipboardTarget !== null && window.clipboardTarget.selectedText.length > 0; onTriggered: window.editClipboard("copy") }
    Action { id: pasteTextAction; objectName: "pasteTextAction"; text: "Вставить"; shortcut: StandardKey.Paste; enabled: !window.modalOpen && window.clipboardTarget !== null && !window.clipboardTarget.readOnly && window.clipboardTarget.canPaste; onTriggered: window.editClipboard("paste") }
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
    Action { id: shiftAction; text: "Сдвиг времени…"; shortcut: backend.shortcuts.shift; enabled: backend.count > 0 && !backend.busy; onTriggered: backend.openShift() }
    Action { id: pointSyncAction; text: "Точечная синхронизация…"; enabled: backend.count > 0 && !backend.busy; onTriggered: backend.openPointSync() }
    Action { id: assignCharacterAction; text: "Назначить персонажа…"; shortcut: backend.shortcuts.assignCharacter; enabled: backend.current.exists && !backend.busy && !window.modalOpen; onTriggered: { if (backend.flush()) actorDialog.open() } }
    Action { id: quitAction; text: "Выйти из Substance"; shortcut: StandardKey.Quit; onTriggered: window.close() }
    Shortcut { sequence: "Space"; enabled: backend.media.hasMedia && !window.textInputFocused() && !window.modalOpen; onActivated: backend.media.toggle() }

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
            MenuItem { objectName: "documentSettingsMenuItem"; text: "Настройки документа…"; enabled: !backend.busy; onTriggered: { if (backend.flush()) documentSettingsDialog.open() } }
            MenuItem { action: exportAction }
            MenuItem { text: "Экспорт исходного текста…"; onTriggered: backend.exportDialog(true) }
            MenuSeparator { }
            MenuItem { objectName: "compareFilesMenuItem"; text: "Сравнить с другим файлом…"; enabled: !backend.busy; onTriggered: backend.fileTransfer.open("compare") }
            MenuItem { objectName: "batchFilesMenuItem"; text: "Обработать несколько файлов…"; onTriggered: backend.batchFiles.open() }
            MenuSeparator { }
            MenuItem { action: Action { text: "Закрыть окно"; shortcut: StandardKey.Close; enabled: !window.modalOpen; onTriggered: window.close() } }
            MenuItem { action: quitAction; visible: !backend.isMac }
        }
        Menu {
            id: editMenu
            objectName: "editMenu"
            title: "Правка"
            MenuItem { action: undoAction }
            MenuItem { action: redoAction }
            MenuSeparator { }
            MenuItem { action: cutTextAction }
            MenuItem { action: copyTextAction }
            MenuItem { action: pasteTextAction }
            MenuSeparator { }
            MenuItem { action: findAction }
            MenuItem { action: replaceAction }
            MenuItem {
                objectName: "preserveAssFormattingMenuItem"
                text: "Сохранять оформление"
                checkable: true
                checked: backend.preserveAssFormatting
                onTriggered: backend.setPreserveAssFormatting(checked)
            }
            MenuItem { text: "Удалить ASS-теги…"; enabled: backend.count > 0 && !backend.busy; onTriggered: { if (backend.flush()) window.presentTool(assTagsDialog, "tags") } }
            MenuSeparator { }
            MenuItem { action: copyAction }
            MenuItem { action: pasteAction }
            MenuItem { objectName: "pasteFieldsMenuItem"; text: "Вставить выбранные данные…"; enabled: backend.selectionCount > 0 && !backend.busy; onTriggered: backend.fileTransfer.open("paste") }
            MenuItem { text: "Выделить все реплики"; onTriggered: backend.selectAll() }
            MenuSeparator { }
            MenuItem { action: Action { text: "Настройки…"; shortcut: "Ctrl+,"; onTriggered: window.presentTool(settingsDialog, "settings") } }
        }
        Menu {
            title: "Вид"
            MenuItem { text: "Боковая панель"; checkable: true; checked: window.sidebarVisible; onTriggered: window.toggleSidebar() }
            MenuItem { text: "Подготовка"; checkable: true; checked: backend.section === "preparation"; onTriggered: backend.setSection("preparation") }
            MenuItem { text: "Режим тайминга"; checkable: true; checked: backend.section === "timing"; onTriggered: backend.setMode("timing") }
            MenuItem { text: "Режим перевода"; checkable: true; checked: backend.section === "translation"; onTriggered: backend.setMode("translation") }
            MenuItem { text: "Пост"; checkable: true; checked: backend.section === "post"; onTriggered: backend.setSection("post") }
            MenuItem {
                objectName: "useAssStylesMenuItem"
                text: "Учитывать стили ASS"
                checkable: true
                checked: backend.useAssStyles
                onTriggered: backend.setUseAssStyles(checked)
            }
            MenuSeparator { }
            MenuItem { text: "Системная тема"; onTriggered: backend.preference("theme", "system") }
            MenuItem { text: "Светлая тема"; onTriggered: backend.preference("theme", "light") }
            MenuItem { text: "Тёмная тема"; onTriggered: backend.preference("theme", "dark") }
        }
        Menu {
            id: cuesMenu
            title: "Реплики"
            MenuItem { action: addAction }
            MenuItem { action: applyAction }
            MenuItem { action: duplicateAction }
            MenuItem { action: splitAction }
            MenuItem { action: mergeAction }
            MenuItem { text: "Переносы и разбиение…"; enabled: backend.count > 0 && !backend.busy; onTriggered: backend.openReflow() }
            MenuItem { action: deleteAction }
            MenuSeparator { }
            MenuItem { action: previousAction }
            MenuItem { action: nextAction }
            MenuSeparator { }
            MenuItem { action: assignCharacterAction }
            MenuItem { text: "Сортировать по началу"; onTriggered: backend.batch("sort", "", true) }
        }
        Menu {
            id: timingMenu
            title: "Тайминг"
            MenuItem { action: setStartAction }
            MenuItem { action: setEndAction }
            MenuItem { action: shiftAction }
            MenuItem { objectName: "pointSyncMenuItem"; action: pointSyncAction }
            MenuItem { text: "Округлить выбранные к кадрам"; onTriggered: backend.batch("frames", "", false) }
            MenuSeparator { }
            MenuItem { objectName: "timingProcessMenuItem"; text: "Обработать интервалы…"; enabled: backend.count > 0 && !backend.busy; onTriggered: backend.openTimingProcessor() }
            MenuItem { text: "Уточнить по речи…"; enabled: backend.count > 0 && !backend.busy; onTriggered: backend.openAlignment() }
            MenuItem { objectName: "scriptTimingMenuItem"; text: "Тайминг готового сценария…"; enabled: !backend.busy; onTriggered: backend.openScriptTiming() }
            MenuItem { objectName: "semanticTimingMenuItem"; text: "Сопоставить по смыслу и разбить…"; enabled: !backend.busy && !backend.onlineSession.active; onTriggered: backend.openSemanticTiming() }
        }
        Menu {
            id: qualityMenu
            objectName: "qualityMenu"
            title: "Проверка"
            MenuItem { objectName: "checksMenuItem"; text: "Проверить и исправить…"; enabled: backend.count > 0 && !backend.busy; onTriggered: backend.openChecks() }
            MenuItem { text: "Проверить орфографию…"; enabled: backend.count > 0; onTriggered: window.presentTool(spellingDialog, "spelling") }
            MenuItem { text: "Сохранить отчёт проверки…"; enabled: backend.count > 0; onTriggered: backend.qualityProfiles.exportReport() }
        }
        Menu {
            id: mediaMenu
            objectName: "mediaMenu"
            title: "Медиа"
            MenuItem { text: "Открыть видео или аудио…"; onTriggered: backend.openMedia() }
            MenuItem { text: "Импорт текстовой дорожки из видео…"; onTriggered: backend.importEmbedded() }
            MenuItem { objectName: "bitmapSubtitlesMenuItem"; text: "Распознать PGS / VobSub…"; onTriggered: backend.bitmapSubtitles.open() }
            MenuItem { objectName: "hardsubMenuItem"; text: "Найти и распознать хардсаб…"; onTriggered: backend.openHardsub() }
            MenuItem { objectName: "transcriptionMenuItem"; text: "Создать субтитры из аудио…"; enabled: !backend.busy; onTriggered: window.presentTool(transcriptionDialog, "transcription") }
            MenuSeparator { }
            MenuItem { text: "Найти смены планов…"; onTriggered: backend.openScenes() }
            MenuItem { objectName: "frameIndexMenuItem"; text: "Точные времена кадров…"; onTriggered: backend.frameIndex.open() }
            MenuSeparator { }
            MenuItem { action: playAction }
            MenuItem { action: playLineAction }
            MenuItem { action: frameBackAction }
            MenuItem { action: frameForwardAction }
        }
        Menu {
            id: toolsMenu
            objectName: "toolsMenu"
            title: "Проект"
            MenuItem { text: "Персонажи проекта…"; onTriggered: backend.openCharacters("") }
            MenuItem { text: "Автопортреты из видео…"; onTriggered: backend.openAutoPortraits() }
            MenuItem { text: "Заметки и предложения…"; enabled: !backend.onlineSession.active; onTriggered: backend.openReviews() }
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
        implicitHeight: visible ? (window.width < 1600 * window.uiScale ? 92 : 50) : 0
        background: Rectangle { color: window.colors.surface }
        GridLayout {
            columns: window.width < 1600 * window.uiScale ? 1 : 2
            rowSpacing: 2
            anchors.fill: parent
            anchors.leftMargin: window.width < 1100 * window.uiScale ? 8 : 10
            anchors.rightMargin: window.width < 1100 * window.uiScale ? 8 : 14
            columnSpacing: 10
            RowLayout {
                Layout.fillWidth: true
                spacing: window.width < 1100 * window.uiScale ? 4 : 10
                ControlButton { symbol: "sidebar"; onClicked: window.toggleSidebar(); hint: "Показать или скрыть боковую панель" }
                Label { visible: window.width > 1200 * window.uiScale; text: backend.title; font.bold: true; font.pixelSize: Math.round(14 * window.uiScale); color: window.colors.text; elide: Text.ElideRight; Layout.maximumWidth: 240 }
                Label { visible: window.width > 1100 * window.uiScale; text: backend.onlineSession.active ? (backend.dirty ? "Изменено" : backend.onlineSession.pending ? "На компьютере" : "На сервере") : backend.dirty ? "Изменено" : "✓ Сохранено"; color: backend.dirty ? window.colors.muted : window.colors.success; font.pixelSize: Math.round(11 * window.uiScale) }
                Item { Layout.fillWidth: true }
                ControlButton {
                    objectName: "toolbarRecents"
                    text: window.width < 1100 * window.uiScale ? "◷ ▾" : "Недавние проекты ▾"
                    hint: "Открыть недавний проект или файл субтитров"
                    enabled: !backend.busy
                    onClicked: recentProjectsMenu.popup()
                    Menu {
                        id: recentProjectsMenu
                        MenuItem { text: "Пока нет недавних проектов"; enabled: false; visible: backend.recentFiles.length === 0 }
                        Instantiator {
                            model: backend.recentFiles
                            delegate: MenuItem { required property string modelData; text: modelData; onTriggered: backend.openPath(modelData) }
                            onObjectAdded: (index, object) => recentProjectsMenu.insertItem(index + 1, object)
                            onObjectRemoved: (index, object) => recentProjectsMenu.removeItem(object)
                        }
                    }
                }
                SegmentedSelector {
                    id: modeTabs
                    objectName: "workspaceSectionTabs"
                    Layout.preferredWidth: 360 * window.uiScale
                    Layout.minimumWidth: 360 * window.uiScale
                    labels: backend.sectionLabels
                    selectedIndex: backend.sectionKeys.indexOf(backend.section)
                    onActivated: index => backend.setSection(backend.sectionKeys[index])
                    Accessible.name: "Раздел работы"
                }
                Item { Layout.fillWidth: true }
            }
            Control {
                Layout.alignment: Qt.AlignRight
                padding: 3
                implicitHeight: 36
                background: Item { }
                contentItem: RowLayout {
                    spacing: 5
                    ControlButton { objectName: "toolbarMedia"; symbol: "video"; hint: "Открыть видео или аудио…"; onClicked: backend.openMedia() }
                    ControlButton { objectName: "toolbarTranscribe"; symbol: "transcribe"; hint: "Распознать речь…"; onClicked: window.presentTool(transcriptionDialog, "transcription") }
                    ControlButton { objectName: "toolbarPortraits"; symbol: "portraits"; hint: "Автопортреты из видео…"; enabled: !backend.busy; onClicked: backend.openAutoPortraits() }
                    ControlButton { objectName: "toolbarScenes"; symbol: "scenes"; hint: "Найти смены планов…"; onClicked: backend.openScenes() }
                    ControlButton { objectName: "toolbarChecks"; symbol: "checks"; hint: "Проверить и исправить…"; enabled: backend.count > 0; onClicked: backend.openChecks() }
                    ControlButton { objectName: "toolbarReflow"; symbol: "reflow"; hint: "Переносы и разбиение…"; enabled: backend.count > 0; onClicked: backend.openReflow() }
                    ControlButton { objectName: "toolbarAlignment"; symbol: "align"; hint: "Уточнить тайминг по речи…"; enabled: backend.count > 0; onClicked: backend.openAlignment() }
                    ControlButton { objectName: "toolbarPointSync"; symbol: "point-sync"; hint: "Точечная синхронизация…"; enabled: backend.count > 0 && !backend.busy; onClicked: backend.openPointSync() }
                    ControlButton { objectName: "toolbarShift"; symbol: "time-shift"; hint: "Сдвиг времени с предпросмотром…"; enabled: backend.count > 0 && !backend.busy; onClicked: backend.openShift() }
                    ControlButton { objectName: "toolbarExport"; text: window.width < 1100 * window.uiScale ? "" : "Экспорт…"; symbol: text.length ? "" : "export"; hint: "Экспорт…"; onClicked: backend.exportDialog(false) }
                    ControlButton { objectName: "toolbarSettings"; symbol: "settings"; onClicked: window.presentTool(settingsDialog, "settings"); hint: "Настройки" }
                }
            }
        }
    }

    SplitView {
        id: documentSplit
        anchors.fill: parent
        orientation: Qt.Horizontal
        handle: Rectangle { implicitWidth: 1; implicitHeight: 1; color: window.colors.border }
        onResizingChanged: if (!resizing && sidebarPane.visible) backend.appearance.setValue("general", "sidebarWidth", Math.round(sidebarPane.width))
        Connections {
            target: backend.appearance
            function onChanged() { sidebarPane.SplitView.preferredWidth = Math.max(sidebarPane.SplitView.minimumWidth, window.appearance.sidebarWidth) }
        }
        Pane {
            id: sidebarPane
            objectName: "sidebarPane"
            visible: window.sidebarVisible && !window.toolSection
            SplitView.preferredWidth: Math.max(SplitView.minimumWidth, appearance.sidebarWidth)
            SplitView.minimumWidth: Math.round(260 * window.uiScale)
            SplitView.maximumWidth: Math.max(340, SplitView.minimumWidth)
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
                // Dialogs are separate windows: retain the glass behind them,
                // but block AppKit actions along with the Qt document controls.
                blocked: window.modalOpen
            }
            ColumnLayout {
                objectName: "fallbackSidebar"
                visible: !glassSidebar.active
                anchors.fill: parent
                spacing: 4
                Label { text: "ДОКУМЕНТ"; color: window.colors.muted; font.pixelSize: Math.round(10 * window.uiScale); font.bold: true; Layout.margins: 8 }
                Repeater {
                    objectName: "sidebarFilters"
                    model: [ {key:"all", title:"Все реплики", symbol:"≡"}, {key:"warnings", title:"Замечания", symbol:"⚠"}, {key:"notes", title:"С заметками", symbol:"✎"}, {key:"proposals", title:"Предложения правок", symbol:"↔"}, {key:"characters", title:"Персонажи", symbol:"♙"} ].filter(item => item.key !== "warnings" || backend.checksEnabled)
                    delegate: ItemDelegate {
                        id: filterItem
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: Math.round(32 * window.uiScale)
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
                            Label { text: modelData.title; color: filterItem.highlighted ? window.colors.selectedText : window.colors.text; Layout.fillWidth: true; Layout.minimumWidth: 0; font.pixelSize: Math.round(12 * window.uiScale); elide: Text.ElideRight }
                            Label { text: backend.counts[modelData.key]; color: filterItem.highlighted ? window.colors.selectedText : window.colors.muted; Layout.minimumWidth: implicitWidth; font.pixelSize: Math.round(11 * window.uiScale) }
                        }
                    }
                }
                Label { text: "ПЕРСОНАЖ"; color: window.colors.muted; font.pixelSize: Math.round(10 * window.uiScale); font.bold: true; Layout.topMargin: 18; Layout.leftMargin: 8 }
                ComboBox { Layout.fillWidth: true; model: ["Все персонажи"].concat(backend.characters); onActivated: backend.setCharacterFilter(currentIndex ? currentText : "") }
                Rectangle { Layout.fillWidth: true; Layout.topMargin: 14; Layout.bottomMargin: 10; height: 1; color: window.colors.border }
                Label { text: "МЕДИА"; color: window.colors.muted; font.pixelSize: Math.round(10 * window.uiScale); font.bold: true; Layout.leftMargin: 8 }
                Label { text: backend.media.name; color: window.colors.text; font.pixelSize: Math.round(12 * window.uiScale); wrapMode: Text.WrapAnywhere; Layout.fillWidth: true; Layout.margins: 8 }
                Label { text: backend.media.keyframeCount ? backend.media.keyframeCount + " ключевых кадров" : "Ключевые кадры не загружены"; color: window.colors.muted; font.pixelSize: Math.round(10 * window.uiScale); wrapMode: Text.Wrap; Layout.fillWidth: true; Layout.leftMargin: 8 }
                Button { text: "Подключить…"; flat: true; onClicked: backend.openMedia() }
                Item { Layout.fillHeight: true }
                Label { text: "Substance " + backend.version; color: window.colors.muted; font.pixelSize: Math.round(10 * window.uiScale); Layout.leftMargin: 8; Layout.bottomMargin: 6 }
            }
        }
        Item {
            SplitView.fillWidth: true
            ColumnLayout {
                visible: !window.toolSection && backend.count === 0 && !backend.busy
                anchors.centerIn: parent
                width: Math.min(500, parent.width - 80)
                spacing: 18
                Label { text: "Substance"; font.pixelSize: Math.round(34 * window.uiScale); font.weight: Font.DemiBold; color: window.colors.text; Layout.alignment: Qt.AlignHCenter }
                Label { text: "Текст, перевод и точный тайминг"; font.pixelSize: Math.round(16 * window.uiScale); color: window.colors.muted; Layout.alignment: Qt.AlignHCenter }
                Label { text: "Создайте ASS с нуля или откройте готовые субтитры. Видео и аудио можно подключить в любой момент."; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; color: window.colors.muted; Layout.fillWidth: true }
                RowLayout { Layout.alignment: Qt.AlignHCenter; Button { objectName: "createFirstLine"; text: "Создать субтитры"; highlighted: true; onClicked: backend.addLine() } Button { text: "Открыть файл…"; onClicked: backend.openDialog() } }
                Button { objectName: "transcribeEmptyDocument"; text: "Распознать речь из видео или аудио…"; Layout.alignment: Qt.AlignHCenter; onClicked: window.presentTool(transcriptionDialog, "transcription") }
                Button { objectName: "hardsubEmptyDocument"; text: "Распознать хардсаб из видео…"; Layout.alignment: Qt.AlignHCenter; onClicked: backend.openHardsub() }
                Button { text: "Открыть пример"; flat: true; Layout.alignment: Qt.AlignHCenter; onClicked: backend.openExample() }
                Label { text: "ASS · SRT · VTT · TXT · .substance\nИли перетащите файл в окно"; color: window.colors.muted; horizontalAlignment: Text.AlignHCenter; font.pixelSize: Math.round(11 * window.uiScale); Layout.alignment: Qt.AlignHCenter }
            }
            BusyIndicator { running: backend.busy && !window.toolSection; anchors.centerIn: parent }
            WorkflowWorkspace {
                id: preparationPage
                objectName: "preparationWorkspace"
                anchors.fill: parent
                visible: backend.section === "preparation"
                section: "preparation"
                title: "Подготовка"
                description: "Откройте исходники, получите текст и подготовьте медиа и проект к таймингу и переводу."
                colors: window.colors
                tools: [
                    {key: "files", title: "Исходники и медиа", detail: "Файлы, текстовые дорожки, проект"},
                    {key: "transcription", title: "Распознать речь", detail: "Субтитры из видео или аудио"},
                    {key: "hardsub", title: "Распознать хардсаб", detail: "Текст, вшитый в изображение"},
                    {key: "bitmap", title: "PGS / VobSub", detail: "Распознать графическую дорожку"},
                    {key: "forced", title: "Тайминг сценария", detail: "Привязать готовый текст к речи"},
                    {key: "semantic", title: "Сопоставить по смыслу", detail: "Другой язык и разбиение длинных строк"},
                    {key: "scenes", title: "Смены планов", detail: "Найти и проверить склейки"},
                    {key: "frames", title: "Точные времена кадров", detail: "Индекс кадров, включая VFR"},
                    {key: "compare", title: "Сравнить файлы", detail: "Перенести текст, время и оформление", document: true},
                    {key: "characters", title: "Персонажи", detail: "Имена, варианты и карточки"},
                    {key: "portraits", title: "Автопортреты", detail: "Подобрать портреты из видео"},
                    {key: "settings", title: "Настройки", detail: "Новые документы, языки и импорт"}
                ]
                onToolRequested: key => window.openWorkflowTool(key)
            }
            WorkflowWorkspace {
                id: postPage
                objectName: "postWorkspace"
                anchors.fill: parent
                visible: backend.section === "post"
                section: "post"
                title: "Пост"
                description: "Проверьте итоговый текст и тайминг, внесите исправления и сохраните субтитры для выпуска."
                colors: window.colors
                tools: [
                    {key: "checks", title: "Проверить и исправить", detail: "Читаемость, текст, профили проверки", document: true},
                    {key: "spelling", title: "Орфография", detail: "Ошибки и варианты исправления", document: true},
                    {key: "balance", title: "Переносы и разбиение", detail: "Длина строк и соседние реплики", document: true},
                    {key: "retime", title: "Обработать интервалы", detail: "Отступы, промежутки и кадры", document: true},
                    {key: "align", title: "Уточнить по речи", detail: "Проверить границы реплик", document: true},
                    {key: "points", title: "Точечная синхронизация", detail: "Исправить расхождение по опорным точкам", document: true},
                    {key: "shift", title: "Сдвиг времени", detail: "Сравнить и применить сдвиг", document: true},
                    {key: "compare", title: "Сравнить версии", detail: "Проверить изменения перед выпуском", document: true},
                    {key: "tags", title: "Очистка ASS-тегов", detail: "Выборочно убрать оформление", document: true},
                    {key: "delivery", title: "Выпуск и отчёт", detail: "Экспорт субтитров и сохранение проекта", document: true},
                    {key: "batch", title: "Пакетная обработка", detail: "Несколько файлов и отчёты"}
                ]
                onToolRequested: key => window.openWorkflowTool(key)
            }

            SplitView {
                id: mainWorkspace
                visible: !window.toolSection && backend.count > 0
                enabled: !backend.busy
                anchors.fill: parent
                orientation: Qt.Vertical
                handle: WorkspaceSplitHandle { colors: window.colors }
                Item {
                    id: workspace
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 350
                }
                Item {
                    id: translationAudio
                    visible: backend.mode === "translation" && backend.appearance.translation.audioVisible
                    SplitView.preferredHeight: backend.appearance.translation.audioHeight
                    SplitView.minimumHeight: 145
                    SplitView.maximumHeight: 350
                }
                onResizingChanged: if (!resizing && backend.mode === "translation" && translationAudio.visible) backend.appearance.resizeLayout("translation", {audioHeight: translationAudio.height})
                Connections {
                    target: backend.appearance
                    function onChanged() { translationAudio.SplitView.preferredHeight = backend.appearance.translation.audioHeight }
                }
            }
        }
    }

    SplitView {
        id: timingSplit
        objectName: "timingWorkspace"
        parent: workspace
        anchors.fill: parent
        visible: backend.mode === "timing"
        onVisibleChanged: if (visible) Qt.callLater(applyLayout)
        readonly property var config: backend.appearance.timing
        property bool ready: false
        orientation: Qt.Vertical
        handle: WorkspaceSplitHandle { colors: window.colors }
        function applyLayout() {
            if (!ready || !visible || resizing || topSplit.resizing) return
            if (itemAt(1) !== (config.audioPosition === "middle" ? timingAudio : timingTable)) moveItem(2, 1)
            if (topSplit.itemAt(0) !== (config.videoSide === "left" ? timingVideo : timingEditor)) topSplit.moveItem(1, 0)
            topSplit.SplitView.preferredHeight = height * config.topPercent / 100
            timingVideo.SplitView.preferredWidth = width * config.videoPercent / 100
            timingAudio.SplitView.preferredHeight = config.audioHeight
        }
        onWidthChanged: Qt.callLater(applyLayout)
        onHeightChanged: Qt.callLater(applyLayout)
        Component.onCompleted: { ready = true; Qt.callLater(applyLayout) }
        Connections { target: backend.appearance; function onChanged() { timingSplit.applyLayout() } }
        onResizingChanged: if (!resizing && ready) backend.appearance.resizeLayout("timing", {topPercent: topSplit.height / Math.max(1, height) * 100, audioHeight: timingAudio.height})
        SplitView {
            id: topSplit
            objectName: "timingTopSplit"
            SplitView.minimumHeight: Math.round(320 * window.uiScale)
            orientation: Qt.Horizontal
            handle: WorkspaceSplitHandle { colors: window.colors; horizontal: true }
            onResizingChanged: if (!resizing && timingSplit.ready && timingSplit.config.videoVisible) backend.appearance.resizeLayout("timing", {videoPercent: timingVideo.width / Math.max(1, width) * 100})
            Item { id: timingVideo; visible: timingSplit.config.videoVisible; SplitView.minimumWidth: 230 }
            Item { id: timingEditor; SplitView.fillWidth: true; SplitView.minimumWidth: 390 }
        }
        Item { id: timingAudio; visible: timingSplit.config.audioVisible; SplitView.minimumHeight: 145; SplitView.maximumHeight: 350 }
        Item { id: timingTable; SplitView.fillHeight: true; SplitView.minimumHeight: 100 }
    }
    SplitView {
        id: translationSplit
        objectName: "translationWorkspace"
        parent: workspace
        anchors.fill: parent
        visible: backend.mode === "translation"
        onVisibleChanged: if (visible) Qt.callLater(applyLayout)
        readonly property var config: backend.appearance.translation
        property bool ready: false
        orientation: Qt.Horizontal
        handle: WorkspaceSplitHandle { colors: window.colors; horizontal: true }
        function applyLayout() {
            if (!ready || !visible || resizing || textSplit.resizing || contextColumn.resizing) return
            if (itemAt(0) !== (config.videoSide === "left" ? contextColumn : textSplit)) moveItem(1, 0)
            if (textSplit.itemAt(0) !== (config.tableFirst ? translationTable : translationEditor)) textSplit.moveItem(1, 0)
            contextColumn.SplitView.preferredWidth = width * config.videoPercent / 100
            translationEditor.SplitView.preferredHeight = config.editorHeight
            languagePane.SplitView.preferredHeight = config.contextHeight
        }
        Component.onCompleted: { ready = true; Qt.callLater(applyLayout) }
        onWidthChanged: Qt.callLater(applyLayout)
        Connections { target: backend.appearance; function onChanged() { translationSplit.applyLayout() } }
        onResizingChanged: if (!resizing && ready && (config.videoVisible || config.contextVisible)) backend.appearance.resizeLayout("translation", {videoPercent: contextColumn.width / Math.max(1, width) * 100})
        SplitView {
            id: textSplit
            SplitView.fillWidth: true
            SplitView.minimumWidth: 460
            orientation: Qt.Vertical
            handle: WorkspaceSplitHandle { colors: window.colors }
            onResizingChanged: if (!resizing && translationSplit.ready) backend.appearance.resizeLayout("translation", {editorHeight: translationEditor.height})
            Item {
                id: translationTable
                SplitView.fillHeight: true
                SplitView.minimumHeight: 100
                clip: true
            }
            Item {
                id: translationEditor
                // The table keeps its header and current row. In short windows
                // the editor scrolls its fields while its actions remain fixed.
                SplitView.minimumHeight: Math.min(315, Math.max(0, textSplit.height - 105))
            }
        }
        SplitView {
            id: contextColumn
            visible: translationSplit.config.videoVisible || translationSplit.config.contextVisible
            SplitView.minimumWidth: 230
            orientation: Qt.Vertical
            handle: WorkspaceSplitHandle { colors: window.colors }
            onResizingChanged: if (!resizing && translationSplit.ready && translationSplit.config.videoVisible && translationSplit.config.contextVisible) backend.appearance.resizeLayout("translation", {contextHeight: languagePane.height})
            Item { id: translationVideo; visible: translationSplit.config.videoVisible; SplitView.fillHeight: true; SplitView.minimumHeight: 150 }
            LanguagePane {
                id: languagePane
                visible: backend.appearance.translation.contextVisible
                colors: window.colors
                SplitView.minimumHeight: 140
                SplitView.fillHeight: !translationSplit.config.videoVisible
            }
        }
    }

    // Keep the editing surfaces alive; only their lightweight layout slots change.
    VideoPane {
        parent: backend.mode === "timing" ? timingVideo : translationVideo
        objectName: backend.mode === "timing" ? "timingVideo" : "translationVideo"
        anchors.fill: parent
        visible: backend.mode === "timing" ? timingSplit.config.videoVisible : translationSplit.config.videoVisible
        colors: window.colors
    }
    CueEditor {
        id: cueEditor
        parent: backend.mode === "timing" ? timingEditor : translationEditor
        objectName: backend.mode === "timing" ? "timingEditor" : "translationEditor"
        anchors.fill: parent
        colors: window.colors
        onEditorCursorChanged: position => window.editCursor = position
        onComposeRequested: kind => reviewCompose.create(kind)
    }
    SubtitleTable {
        parent: backend.mode === "timing" ? timingTable : translationTable
        anchors.fill: parent
        colors: window.colors
    }
    AudioPane {
        parent: backend.mode === "timing" ? timingAudio : translationAudio
        objectName: backend.mode === "timing" ? "timingAudio" : "translationAudio"
        anchors.fill: parent
        visible: backend.mode === "timing" ? timingSplit.config.audioVisible : translationSplit.config.audioVisible
        colors: window.colors
    }

    footer: Rectangle {
        objectName: "documentStatusBar"
        height: 30 + (backend.onlineSession.active ? 36 : 0) + (speechStatus.visible ? 44 : 0)
        color: window.colors.header
        Rectangle { width: parent.width; height: 1; color: window.colors.border }
        RowLayout {
            id: speechStatus
            objectName: "transcriptionProgressRow"
            visible: backend.transcription.statusVisible
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 30
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            height: 44
            spacing: 10
            Label { text: backend.transcription.status + (backend.transcription.running ? " · Реплик: " + backend.transcription.addedCount : ""); Layout.fillWidth: true; elide: Text.ElideRight; color: backend.transcription.error ? window.colors.warning : window.colors.text }
            ProgressBar { Layout.preferredWidth: 130; visible: backend.transcription.busy; value: backend.transcription.progress; indeterminate: backend.transcription.busy && backend.transcription.progress === 0 }
            Button { objectName: "speechStopButton"; text: "Остановить"; visible: backend.transcription.busy; enabled: !backend.transcription.stopping; onClicked: backend.transcription.stop() }
            Button { objectName: "speechDiscardButton"; text: "Отменить распознавание"; visible: backend.transcription.canDiscard; onClicked: backend.transcription.discard() }
            Button { text: "Параметры…"; onClicked: window.presentTool(transcriptionDialog, "transcription") }
            Button { text: "Скрыть"; visible: !backend.transcription.busy; onClicked: backend.transcription.dismiss() }
        }
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
            Label { text: backend.onlineSession.status; Layout.fillWidth: true; elide: Text.ElideRight; color: window.colors.text; font.pixelSize: Math.round(11 * window.uiScale) }
            Button { objectName: "onlineCompareButton"; text: "Сравнить версии…"; visible: backend.onlineSession.conflictSession.available; enabled: !backend.onlineSession.busy; onClicked: onlineConflictDialog.open() }
            Button { objectName: "onlineGlossaryButton"; text: "Глоссарий…"; visible: backend.onlineSession.glossarySession.supported; onClicked: window.presentTool(onlineGlossaryDialog, "characters") }
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
            Label { text: backend.current.exists ? backend.current.number + " из " + backend.count : backend.count + " реплик"; color: window.colors.muted; font.pixelSize: Math.round(11 * window.uiScale) }
            Label { text: "ASS · " + backend.encoding.toUpperCase() + " · " + Number(backend.fps).toFixed(3) + " fps"; color: window.colors.muted; font.pixelSize: Math.round(11 * window.uiScale) }
            Label { text: backend.selectionCount > 1 ? "Выбрано " + backend.selectionCount : backend.message; Layout.fillWidth: true; color: window.colors.muted; font.pixelSize: Math.round(11 * window.uiScale); elide: Text.ElideRight }
            Label { text: backend.shortcutLabel("apply") + " — применить"; color: window.colors.muted; font.pixelSize: Math.round(10 * window.uiScale) }
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
    OnlineGlossaryDialog { id: onlineGlossaryDialog; objectName: "onlineGlossaryDialog"; transientParent: portraitCropDialog.visible ? portraitCropDialog : window; colors: window.colors }
    OnlineWorkflowDialog { id: onlineWorkflowDialog; objectName: "onlineWorkflowDialog"; colors: window.colors }
    ReviewCompose { id: reviewCompose; objectName: "reviewComposeDialog"; transientParent: reviewsDialog.visible ? reviewsDialog : window; colors: window.colors }
    ReviewsDialog { id: reviewsDialog; objectName: "reviewsDialog"; colors: window.colors; onComposeRequested: kind => reviewCompose.create(kind); onEditRequested: entry => reviewCompose.edit(entry) }
    CharacterDialog { id: characterDialog; objectName: "characterDialog"; colors: window.colors }
    AutoPortraitsDialog { id: autoPortraitsDialog; objectName: "autoPortraitsDialog"; colors: window.colors }
    Connections {
        target: backend.portraitTools
        function onRequested() { window.presentTool(autoPortraitsDialog, "portraits") }
    }
    PortraitCropDialog { id: portraitCropDialog; objectName: "portraitCropDialog"; transientParent: characterDialog.visible ? characterDialog : window; colors: window.colors; onGlossaryRequested: window.presentTool(onlineGlossaryDialog, "characters") }
    Connections {
        target: backend
        function onTranscriptionRequested() { window.presentTool(transcriptionDialog, "transcription") }
        function onReviewsRequested() { window.presentTool(reviewsDialog, "reviews") }
        function onCardsRequested(cardId) {
            if (backend.onlineSession.active && backend.onlineSession.glossarySession.supported) {
                let session = backend.onlineSession.glossarySession
                if (!session.draft.data && cardId) session.begin(cardId, "character")
                window.presentTool(onlineGlossaryDialog, "characters")
                onlineGlossaryDialog.loadDraft()
            } else { window.presentTool(characterDialog, "characters"); characterDialog.reload() }
        }
        function onCropRequested() { portraitCropDialog.open() }
        function onDocumentReplaced() { documentSettingsDialog.dismiss(); shiftDialog.dismiss(); alignmentDialog.dismiss(); onlineConflictDialog.dismiss(); onlineGlossaryDialog.dismiss(); characterDialog.modified = false; characterDialog.dismiss(); portraitCropDialog.dismiss(); reviewsDialog.dismiss(); reviewCompose.dismiss(); onlineWorkflowDialog.dismiss(); actorDialog.dismiss() }
    }

    EditorToolsDialog { id: editorToolsDialog; colors: window.colors }
    AlignmentDialog { id: alignmentDialog; colors: window.colors }
    TransferDialog { id: transferDialog; colors: window.colors }
    TimingProcessDialog { id: timingProcessDialog; colors: window.colors }
    ScriptTimingDialog { id: scriptTimingDialog; colors: window.colors }
    SemanticTimingDialog { id: semanticTimingDialog; colors: window.colors }
    BatchDialog { id: batchDialog; colors: window.colors }
    BitmapSubtitleDialog { id: bitmapSubtitleDialog; colors: window.colors }
    FrameIndexDialog { id: frameIndexDialog; colors: window.colors }
    Connections { target: backend.fileTransfer; function onRequested() { window.mountTool(transferDialog, "compare"); transferDialog.prepare() } }
    Connections { target: backend.batchFiles; function onRequested() { window.presentTool(batchDialog, "batch") } }
    Connections { target: backend.bitmapSubtitles; function onRequested() { window.presentTool(bitmapSubtitleDialog, "bitmap") } }
    Connections { target: backend.frameIndex; function onRequested() { window.presentTool(frameIndexDialog, "frames") } }
    Connections {
        target: backend.editorTools
        function onRequested(kind) {
            // Close the previous view before starting another analysis with the
            // shared proposal controller. closed() only cancels pending work.
            if (kind !== "align") alignmentDialog.dismiss()
            if (kind !== "retime") timingProcessDialog.dismiss()
            if (kind !== "forced") scriptTimingDialog.dismiss()
            if (kind !== "semantic") semanticTimingDialog.dismiss()
            if (["align", "retime", "forced", "semantic"].indexOf(kind) >= 0) editorToolsDialog.dismiss()
            if (kind === "align") window.presentTool(alignmentDialog, "align")
            else if (kind === "retime") window.presentTool(timingProcessDialog, "retime")
            else if (kind === "forced") { if (scriptTimingDialog.visible) window.presentTool(scriptTimingDialog, "forced"); else { window.mountTool(scriptTimingDialog, "forced"); scriptTimingDialog.prepare() } }
            else if (kind === "semantic") { if (semanticTimingDialog.visible) window.presentTool(semanticTimingDialog, "semantic"); else { window.mountTool(semanticTimingDialog, "semantic"); semanticTimingDialog.prepare() } }
            else { window.mountTool(editorToolsDialog, kind); editorToolsDialog.prepare(kind) }
        }
    }
    HardsubDialog { id: hardsubDialog; colors: window.colors }
    Connections { target: backend.hardsubTools; function onRequested() { window.presentTool(hardsubDialog, "hardsub") } }
    TranscriptionDialog { id: transcriptionDialog; colors: window.colors }
    DocumentSettingsDialog { id: documentSettingsDialog; colors: window.colors }
    SettingsDialog { id: settingsDialog; objectName: "settingsDialog"; colors: window.colors }
    LibreServerWizard { id: libreServerWizard; colors: window.colors }
    Connections { target: backend.languageAssistance; function onSettingsRequested() { settingsDialog.openLanguageSettings() } }

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
                    ControlButton { symbol: "arrow-up-right"; onClicked: { backend.locateSpelling(modelData.index, modelData.word); spellingDialog.dismiss() } hint: "Перейти к слову" }
                    ControlButton { symbol: "plus"; onClicked: backend.ignoreSpelling(modelData.word); hint: "Добавить в словарь" }
                }
            }
            Label { text: "Проверка выполняется локально. Имена персонажей исключены из словаря ошибок."; color: window.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: Math.round(11 * window.uiScale) }
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
            RowLayout {
                CheckBox { id: caseSensitive; text: "Учитывать регистр" }
                CheckBox { id: regex; text: "Регулярное выражение" }
                Label {
                    id: regexHelp
                    objectName: "regexHelp"
                    text: "?"
                    Layout.preferredWidth: Math.round(22 * window.uiScale)
                    Layout.preferredHeight: Layout.preferredWidth
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: window.colors.muted
                    Accessible.name: "Помощь: регулярные выражения"
                    Accessible.description: regexHelpTip.text
                    background: Rectangle {
                        color: "transparent"
                        radius: width / 2
                        border.color: window.colors.muted
                    }
                    NativeToolTip {
                        id: regexHelpTip
                        objectName: "regexHelpTip"
                        text: "Поиск по шаблону. Без этой галочки текст ищется буквально.\n\n"
                            + "Примеры для поля «Найти»:\n"
                            + "\\d+ — любое число: 12, 345\n"
                            + " {2,} — два и более пробела подряд (перед { — один пробел)\n"
                            + "кот|кошка — «кот» или «кошка»\n"
                            + "^Привет — «Привет» в начале реплики\n"
                            + "\\. — обычная точка; \\? — вопросительный знак\n\n"
                            + "Чтобы убрать лишние пробелы, найдите  {2,} и замените одним пробелом."
                    }
                }
            }
            CheckBox { id: selectedOnly; visible: findDialog.replaceMode; text: "Только в выбранных репликах" }
            RowLayout {
                Button { text: "Найти"; onClicked: backend.setSearch(findInput.text, caseSensitive.checked, regex.checked) }
                Button { text: "Следующая"; onClicked: { backend.setSearch(findInput.text, caseSensitive.checked, regex.checked); backend.navigate(1) } }
                Button { visible: findDialog.replaceMode; text: "Заменить все"; onClicked: backend.replace(findInput.text, replacementInput.text, regex.checked, caseSensitive.checked, selectedOnly.checked) }
                Button { text: "Сбросить"; onClicked: { backend.setSearch("", false, false); findDialog.dismiss() } }
            }
        }
    }
    TimingDialog { id: shiftDialog; colors: window.colors }
    Connections { target: backend.timingTools; function onRequested() { window.mountTool(shiftDialog, backend.timingTools.kind === "points" ? "points" : "shift"); shiftDialog.prepare(); window.presentTool(shiftDialog, backend.timingTools.kind === "points" ? "points" : "shift") } }
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
        contentItem: Label { text: notification.message; color: window.colors.text; wrapMode: Text.Wrap; font.pixelSize: Math.round(12 * window.uiScale) }
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: backend.motion ? 120 : 0 } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: backend.motion ? 120 : 0 } }
        Timer { id: notificationTimer; interval: 3800; onTriggered: notification.close() }
    }
    Connections { target: backend; function onToast(message) { notification.message = message; notification.open(); notificationTimer.restart() } }
}
