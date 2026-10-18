import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    readonly property var controller: backend.portraitTools
    readonly property var selectedPortrait: results.currentItem ? results.currentItem.portrait : ({})
    readonly property bool hasPortrait: !!selectedPortrait.url
    title: "Портреты персонажей из видео"
    preferredWidth: 1280
    preferredHeight: 900
    minimumWidth: Math.min(760, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(650, Screen.desktopAvailableHeight - 80)
    modal: false
    standardButtons: Dialog.NoButton

    function explanation(row) {
        if (row.applied)
            return "Этот портрет уже добавлен в глоссарий.";
        if (row.pending)
            return "Портрет ожидает отправки. Проверьте его состояние в общем глоссарии.";
        if (row.newCharacter)
            return "Новый персонаж будет создан вместе с этим портретом после нажатия «Добавить в глоссарий».";
        if (!row.cardId)
            return "Выберите имя из глоссария. После этого портрет будет отмечен для добавления.";
        if (row.reason === "Имя выбрано вручную.")
            return "Имя выбрано вручную. Проверьте портрет перед добавлением в глоссарий.";
        if ((row.reason || "").indexOf("Несколько") === 0)
            return "Под этим именем найдены разные лица. Сравните варианты и выберите правильный.";
        if ((row.reason || "").indexOf("разных персонажей") >= 0)
            return "По внешности и по репликам получились разные имена. Выберите правильное имя вручную.";
        if ((row.reason || "").indexOf("Совпадение с") === 0)
            return "Лицо похоже на портрет, который уже есть у этого персонажа.";
        if (row.confident)
            return "Это лицо появляется во время нескольких реплик данного персонажа. Проверьте, что имя выбрано верно.";
        return "Программа не уверена в имени. Сравните лицо с видео или выберите другого персонажа.";
    }

    Connections {
        target: dialog.controller
        function onSelectionRequested(sourceIndex) {
            let mapped = dialog.controller.visibleIndex(sourceIndex);
            if (mapped >= 0)
                results.currentIndex = mapped;
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 14
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Label {
                    text: "Портреты персонажей"
                    font.pixelSize: 24
                    font.weight: Font.DemiBold
                }
                Label {
                    Layout.fillWidth: true
                    text: "Найдите лица в видео, проверьте имена и добавьте подходящие портреты в глоссарий."
                    color: dialog.colors.muted
                    wrapMode: Text.Wrap
                }
            }
            Button {
                text: "О моделях…"
                onClicked: modelInfo.open()
            }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: setup.implicitHeight + 28
            color: dialog.colors.surface
            border.color: dialog.colors.separator
            radius: 12
            ColumnLayout {
                id: setup
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10
                Label {
                    text: "1. Найдите лица в видео"
                    font.weight: Font.DemiBold
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Label {
                        text: "Тип видео"
                    }
                    ComboBox {
                        objectName: "portraitVideoType"
                        Layout.preferredWidth: dialog.width >= 1000 ? 230 : 195
                        model: ["Аниме / анимация", "Живые актёры"]
                        currentIndex: dialog.controller.mode === "live" ? 1 : 0
                        enabled: !dialog.controller.busy
                        onActivated: dialog.controller.setMode(currentIndex === 1 ? "live" : "anime")
                    }
                    Label {
                        text: "Режим"
                    }
                    ComboBox {
                        objectName: "portraitSpeed"
                        Layout.preferredWidth: 120
                        model: ["Быстро", "Обычный"]
                        currentIndex: dialog.controller.speed === "fast" ? 0 : 1
                        enabled: !dialog.controller.busy
                        onActivated: dialog.controller.setSpeed(currentIndex === 0 ? "fast" : "normal")
                    }
                    Label {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        visible: dialog.width >= 1100
                        text: backend.media.name || "Видео ещё не загружено"
                        elide: Text.ElideMiddle
                        color: dialog.colors.muted
                    }
                    Item {
                        Layout.fillWidth: true
                        visible: dialog.width < 1100
                    }
                    Button {
                        objectName: "analyzePortraitsButton"
                        text: dialog.controller.summary.found ? "Повторить поиск" : "Найти лица в видео"
                        enabled: dialog.controller.canAnalyze
                        visible: !dialog.controller.busy || dialog.controller.adding
                        onClicked: dialog.controller.analyze()
                    }
                    Button {
                        text: "Остановить поиск"
                        visible: dialog.controller.busy && !dialog.controller.adding
                        onClicked: dialog.controller.cancel()
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: !backend.media.hasVideo ? "Сначала загрузите видео в проект." : "Видео обрабатывается на вашем компьютере. Для первого запуска нужен интернет, чтобы скачать модели."
                    color: !backend.media.hasVideo ? dialog.colors.warning : dialog.colors.muted
                    wrapMode: Text.Wrap
                }
                Label {
                    Layout.fillWidth: true
                    visible: dialog.controller.speed === "fast"
                    text: "Быстрый поиск проверяет меньше кадров: редкие появления и мелкие лица могут быть пропущены."
                    color: dialog.colors.muted
                    wrapMode: Text.Wrap
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 22
            visible: !dialog.controller.saveVisible
            Label {
                objectName: "portraitAnalysisStatus"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: dialog.controller.stale ? "Документ или видео изменились. Повторите поиск, чтобы добавить портреты." : dialog.controller.status || "После поиска здесь появятся найденные портреты."
                color: dialog.controller.stale ? dialog.colors.warning : dialog.colors.muted
                elide: Text.ElideRight
            }
            ProgressBar {
                Layout.preferredWidth: 160
                visible: dialog.controller.busy && !dialog.controller.adding
                value: dialog.controller.progress
                indeterminate: value === 0
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 180
            spacing: 14
            Rectangle {
                Layout.preferredWidth: (dialog.width - 54) * .43
                Layout.minimumWidth: 270
                Layout.fillHeight: true
                color: dialog.colors.surface
                radius: 12
                border.color: dialog.colors.separator
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            text: "2. Выберите портреты"
                            font.weight: Font.DemiBold
                            Layout.fillWidth: true
                        }
                        Label {
                            text: "Найдено: " + dialog.controller.summary.total
                            color: dialog.colors.muted
                        }
                    }
                    Label {
                        text: "Нажмите на лицо, чтобы проверить имя справа."
                        color: dialog.colors.muted
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                    }
                    CheckBox {
                        objectName: "portraitShowUnnamed"
                        text: "Показывать без имени (" + dialog.controller.summary.unnamed + ")"
                        checked: dialog.controller.showUnnamed
                        onClicked: {
                            let source = dialog.hasPortrait ? dialog.selectedPortrait.sourceIndex : -1;
                            dialog.controller.setShowUnnamed(checked);
                            let mapped = dialog.controller.visibleIndex(source);
                            results.currentIndex = mapped >= 0 ? mapped : results.count ? 0 : -1;
                        }
                    }
                    ListView {
                        id: results
                        objectName: "portraitResults"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 6
                        model: dialog.controller.resultsModel
                        currentIndex: -1
                        Component.onCompleted: if (count && currentIndex < 0)
                            currentIndex = 0
                        onCountChanged: if (currentIndex < 0 || currentIndex >= count)
                            currentIndex = count ? 0 : -1
                        ScrollBar.vertical: ScrollBar {}
                        delegate: Rectangle {
                            id: portraitRow
                            required property var portrait
                            required property int index
                            objectName: "portraitRow" + index
                            width: results.width
                            height: 106
                            radius: 9
                            color: results.currentIndex === index ? Qt.alpha(dialog.colors.accent, .09) : dialog.colors.panel
                            border.width: results.currentIndex === index ? 2 : 1
                            border.color: results.currentIndex === index ? Qt.alpha(dialog.colors.accent, .65) : "transparent"
                            MouseArea {
                                anchors.fill: parent
                                onClicked: results.currentIndex = portraitRow.index
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 10
                                CheckBox {
                                    objectName: "portraitSelect" + portraitRow.index
                                    checked: portraitRow.portrait.checked
                                    enabled: !dialog.controller.busy && !portraitRow.portrait.applied && !portraitRow.portrait.pending && !!portraitRow.portrait.cardId
                                    Accessible.name: "Добавить портрет: " + portraitRow.portrait.cardName
                                    onClicked: dialog.controller.check(portraitRow.portrait.sourceIndex, checked)
                                }
                                Rectangle {
                                    Layout.preferredWidth: 70
                                    Layout.preferredHeight: 84
                                    color: dialog.colors.workspace
                                    radius: 6
                                    Image {
                                        anchors.fill: parent
                                        anchors.margins: 3
                                        source: portraitRow.portrait.url
                                        fillMode: Image.PreserveAspectFit
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    spacing: 5
                                    Label {
                                        text: portraitRow.portrait.cardId ? portraitRow.portrait.cardName : "Неизвестный персонаж"
                                        font.weight: Font.DemiBold
                                        Layout.fillWidth: true
                                        elide: Text.ElideRight
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        elide: Text.ElideRight
                                        text: portraitRow.portrait.applied ? "Добавлен в глоссарий" : portraitRow.portrait.pending ? "Ожидает отправки" : portraitRow.portrait.newCharacter ? "Новый персонаж · будет создан" : !portraitRow.portrait.cardId ? "Укажите имя справа" : portraitRow.portrait.confident ? "Имя предложено" : "Проверьте совпадение"
                                        color: portraitRow.portrait.applied ? dialog.colors.success : portraitRow.portrait.confident ? dialog.colors.muted : dialog.colors.warning
                                        font.pixelSize: 12
                                    }
                                    Label {
                                        text: "На видео: " + portraitRow.portrait.time
                                        color: dialog.colors.muted
                                        font.pixelSize: 11
                                    }
                                }
                            }
                        }
                        Label {
                            anchors.centerIn: parent
                            width: parent.width - 30
                            visible: results.count === 0
                            text: dialog.controller.busy ? "Ищем лица в видео…" : dialog.controller.summary.unnamed && !dialog.controller.showUnnamed ? "Имена не определены.\nВключите «Показывать без имени», чтобы выбрать их вручную." : "Нажмите «Найти лица в видео».\nЗдесь появятся варианты портретов."
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            color: dialog.colors.muted
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            text: "С галочкой: " + dialog.controller.summary.selected
                            Layout.fillWidth: true
                            color: dialog.colors.muted
                        }
                        Button {
                            text: "Снять галочки"
                            enabled: !dialog.controller.busy && dialog.controller.summary.selected > 0
                            onClicked: dialog.controller.clearSelection()
                        }
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 260
                color: dialog.colors.surface
                radius: 12
                border.color: dialog.colors.separator
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 10
                    visible: dialog.hasPortrait
                    Label {
                        text: "Кому принадлежит это лицо?"
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                    }
                    CharacterSearchField {
                        objectName: "portraitCharacter"
                        Layout.fillWidth: true
                        choices: dialog.controller.characters
                        selectedId: dialog.selectedPortrait.cardId || ""
                        contextKey: dialog.selectedPortrait.url || ""
                        canCreate: dialog.controller.canCreateCharacter
                        enabled: !dialog.controller.busy && !dialog.selectedPortrait.applied && !dialog.selectedPortrait.pending
                        onChosen: characterId => dialog.controller.assign(dialog.selectedPortrait.sourceIndex, characterId)
                        onCreateRequested: name => dialog.controller.createCharacter(dialog.selectedPortrait.sourceIndex, name)
                    }
                    ScrollView {
                        id: detailScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ColumnLayout {
                            width: detailScroll.availableWidth
                            spacing: 12
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: Math.max(140, Math.min(360, detailScroll.height - 110))
                                color: dialog.colors.workspace
                                radius: 10
                                Image {
                                    objectName: "portraitLargePreview"
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    source: dialog.selectedPortrait.detailUrl || ""
                                    sourceSize.width: 720
                                    sourceSize.height: 720
                                    fillMode: Image.PreserveAspectFit
                                }
                                Label {
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                    anchors.margins: 8
                                    padding: 5
                                    text: "Кадр " + (dialog.selectedPortrait.variant || 1) + " из " + (dialog.selectedPortrait.variants || 1)
                                    color: dialog.colors.text
                                    background: Rectangle {
                                        color: Qt.alpha(dialog.colors.surface, .9)
                                        radius: 4
                                    }
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Button {
                                    text: "Другой кадр"
                                    enabled: !dialog.controller.busy && !dialog.selectedPortrait.pending && dialog.selectedPortrait.variants > 1
                                    onClicked: dialog.controller.nextVariant(dialog.selectedPortrait.sourceIndex)
                                }
                                Item {
                                    Layout.fillWidth: true
                                }
                                Button {
                                    text: "Показать кадр в видео"
                                    enabled: !dialog.controller.stale
                                    onClicked: dialog.controller.seek(dialog.selectedPortrait.sourceIndex)
                                }
                            }
                            Label {
                                Layout.fillWidth: true
                                text: dialog.explanation(dialog.selectedPortrait)
                                wrapMode: Text.Wrap
                                color: dialog.colors.muted
                            }
                        }
                    }
                    CheckBox {
                        objectName: "portraitDetailSelect"
                        text: "Добавить этот портрет в глоссарий"
                        checked: !!dialog.selectedPortrait.checked
                        enabled: !dialog.controller.busy && !dialog.selectedPortrait.applied && !dialog.selectedPortrait.pending && !!dialog.selectedPortrait.cardId
                        onClicked: dialog.controller.check(dialog.selectedPortrait.sourceIndex, checked)
                    }
                }
                Label {
                    anchors.centerIn: parent
                    width: parent.width - 40
                    visible: !dialog.hasPortrait
                    text: "Здесь можно рассмотреть портрет\nи выбрать имя персонажа."
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    color: dialog.colors.muted
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: saveOptions.implicitHeight + 24
            color: dialog.colors.surface
            border.color: dialog.colors.separator
            radius: 12
            ColumnLayout {
                id: saveOptions
                anchors.fill: parent
                anchors.margins: 12
                spacing: 10
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        text: "3. Добавьте выбранные портреты"
                        font.weight: Font.DemiBold
                        Layout.fillWidth: true
                    }
                    Label {
                        text: "Выбрано: " + dialog.controller.summary.selected
                        color: dialog.colors.muted
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        text: "Если портрет уже есть"
                        color: dialog.colors.muted
                    }
                    ComboBox {
                        id: existingPortrait
                        objectName: "portraitExistingAction"
                        Layout.preferredWidth: 250
                        model: ["Добавить новый в галерею", "Сделать новый основным"]
                        enabled: !dialog.controller.busy
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                }
            }
        }
        ColumnLayout {
            objectName: "portraitSaveProgressPanel"
            Layout.fillWidth: true
            visible: dialog.controller.saveVisible
            spacing: 6
            ProgressBar {
                objectName: "portraitSaveProgress"
                Layout.fillWidth: true
                value: dialog.controller.saveProgress
                indeterminate: dialog.controller.adding && value === 0
            }
            RowLayout {
                Layout.fillWidth: true
                Label {
                    objectName: "portraitSaveStatus"
                    Layout.fillWidth: true
                    text: dialog.controller.saveStatus
                    wrapMode: Text.Wrap
                    color: dialog.colors.text
                }
                Button {
                    text: "Остановить добавление"
                    visible: dialog.controller.adding
                    onClicked: dialog.controller.cancel()
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Label {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: backend.onlineSession.active ? "Портреты отправятся в общий проект." : "Добавление можно отменить одним действием."
                wrapMode: Text.Wrap
                color: dialog.colors.muted
                font.pixelSize: 12
            }
            Button {
                text: "Общий глоссарий…"
                visible: backend.onlineSession.active
                onClicked: backend.openCharacters("")
            }
            Button {
                text: "Закрыть"
                onClicked: dialog.close()
            }
            Button {
                objectName: "applyPortraitsButton"
                text: dialog.controller.adding ? "Добавляем…" : "Добавить в глоссарий (" + dialog.controller.summary.selected + ")"
                highlighted: true
                enabled: dialog.controller.canApply
                onClicked: dialog.controller.apply(existingPortrait.currentIndex === 1)
            }
        }
    }
    NativeDialog {
        id: modelInfo
        title: "Модели распознавания"
        colors: dialog.colors
        transientParent: dialog
        preferredWidth: 660
        preferredHeight: 320
        standardButtons: Dialog.Close
        ColumnLayout {
            anchors.fill: parent
            spacing: 14
            Label {
                text: "Распознавание работает на вашем компьютере"
                font.weight: Font.DemiBold
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                text: "Для выбранного типа видео модели займут около " + dialog.controller.modelSize + ". Они скачиваются при первом поиске. После загрузки интернет для распознавания не нужен."
                wrapMode: Text.Wrap
                color: dialog.colors.muted
            }
            Label {
                text: "Папка с моделями"
                font.weight: Font.DemiBold
            }
            DialogTextField {
                objectName: "portraitModelsDirectory"
                Layout.fillWidth: true
                text: dialog.controller.modelDirectory
                readOnly: true
                selectByMouse: true
            }
            Label {
                Layout.fillWidth: true
                text: "Substance и DubbingManager могут использовать эту общую папку. Для работы Substance устанавливать DubbingManager не требуется."
                wrapMode: Text.Wrap
                color: dialog.colors.muted
            }
            Item {
                Layout.fillHeight: true
            }
        }
    }
}
