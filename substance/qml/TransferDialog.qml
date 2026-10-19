import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "transferDialog"
    readonly property var controller: backend.fileTransfer
    readonly property var preview: controller.preview
    modal: false
    preferredWidth: 1220
    preferredHeight: 880
    minimumWidth: Math.min(800, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(650, Screen.desktopAvailableHeight - 80)
    title: controller.kind === "paste" ? "Вставить выбранные данные" : "Сравнить с другим файлом"
    function prepare() {
        takeText.checked = true; takeTime.checked = controller.kind !== "paste"
        takeActor.checked = false; takeFormat.checked = false; structure.checked = false
        open()
    }
    onOpened: Qt.callLater(() => list.forceActiveFocus())
    Connections {
        target: dialog.controller
        function onPreviewChanged() { list.syncSelection() }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: dialog.title; font.pixelSize: 24; font.weight: Font.DemiBold }
        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.controller.kind === "paste" ? "Перенесите отдельные поля поверх выделенных реплик. Проверьте соответствие строк перед применением." : "Сравните текст, время и персонажей. Отметьте нужные изменения — они попадут в открытый документ после применения."; wrapMode: Text.Wrap; color: dialog.colors.muted }
        ToolCard {
            colors: dialog.colors
            Layout.fillWidth: true
            implicitHeight: setup.implicitHeight + 28
            ColumnLayout {
                id: setup
                anchors.fill: parent
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "1. Откуда взять данные"; font.weight: Font.DemiBold }
                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.controller.referenceName || "Файл ещё не выбран"; elide: Text.ElideMiddle }
                    Button { objectName: "transferChooseFile"; text: "Выбрать файл…"; onClicked: { dialog.controller.chooseReference(); list.forceActiveFocus() } }
                    Button { text: "Из буфера"; onClicked: { dialog.controller.loadClipboard(); list.forceActiveFocus() } }
                }
                Flow {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    Layout.preferredWidth: 1
                    spacing: 8
                    Label { text: "Что перенести:"; height: takeText.height; verticalAlignment: Text.AlignVCenter }
                    CheckBox { id: takeText; objectName: "transferText"; text: "Текст"; checked: true; onClicked: dialog.controller.setField("text", checked) }
                    CheckBox { id: takeTime; objectName: "transferTime"; text: "Время"; checked: true; onClicked: dialog.controller.setField("time", checked) }
                    CheckBox { id: takeActor; text: "Персонаж"; onClicked: dialog.controller.setField("character", checked) }
                    CheckBox { id: takeFormat; text: "Стиль, слой и отступы"; onClicked: dialog.controller.setField("format", checked) }
                    CheckBox { id: structure; visible: dialog.controller.kind === "compare"; text: "Добавленные и удалённые реплики"; onClicked: dialog.controller.setField("structure", checked) }
                }
                RowLayout {
                    Layout.fillWidth: true
                    CheckBox { id: differencesOnly; objectName: "transferDifferencesOnly"; text: "Только различия"; checked: dialog.controller.differencesOnly; onClicked: { dialog.controller.setField("differences", checked); list.forceActiveFocus() } }
                    Label { text: "Тип различий" }
                    ComboBox {
                        id: differenceKind
                        objectName: "transferDifferenceKind"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        model: dialog.controller.differenceFilters
                        textRole: "title"
                        valueRole: "id"
                        enabled: dialog.controller.differencesOnly
                        currentIndex: model.findIndex(option => option.id === dialog.controller.differenceFilter)
                        onActivated: { dialog.controller.setDifferenceFilter(currentValue); Qt.callLater(() => list.forceActiveFocus()) }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: !!dialog.controller.referenceName
                    Button { id: pairingToggle; visible: dialog.controller.kind === "compare"; text: "Исправить сопоставление…"; checkable: true }
                    Item { Layout.fillWidth: true }
                    Button { text: "Обновить сравнение"; enabled: !!dialog.controller.referenceName; onClicked: dialog.controller.refresh() }
                }
                RowLayout {
                    visible: pairingToggle.checked && dialog.controller.kind === "compare" && !!dialog.controller.referenceName
                    Layout.fillWidth: true
                    Label { text: "здесь №" }
                    DialogSpinBox { id: currentAnchor; Layout.preferredWidth: 90; from: 1; to: Math.max(1, backend.count); editable: true }
                    Label { text: "соответствует там №" }
                    DialogSpinBox { id: referenceAnchor; Layout.preferredWidth: 90; from: 1; to: 30000; editable: true }
                    Button { text: "Сопоставить"; onClicked: dialog.controller.pair(currentAnchor.value, referenceAnchor.value) }
                    Item { Layout.fillWidth: true }
                }
            }
        }
        Label { objectName: "transferStatus"; Layout.fillWidth: true; text: dialog.controller.status; wrapMode: Text.Wrap; color: dialog.controller.stale ? dialog.colors.warning : dialog.colors.muted }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12
            ToolCard {
                colors: dialog.colors
                Layout.preferredWidth: Math.max(260, dialog.width * .31)
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    RowLayout {
                        Layout.fillWidth: true
                        Label { Layout.fillWidth: true; text: "2. Выберите изменения"; font.weight: Font.DemiBold }
                        Label { text: list.count; color: dialog.colors.muted }
                    }
                    Label { Layout.fillWidth: true; text: "↑ / ↓ — переход · Пробел — отметить"; wrapMode: Text.Wrap; color: dialog.colors.muted; font.pixelSize: 11 }
                    RowLayout {
                        Button { text: "Выбрать все"; onClicked: dialog.controller.checkAll(true) }
                        Button { text: "Снять"; onClicked: dialog.controller.checkAll(false) }
                    }
                    ListView {
                        id: list
                        objectName: "transferList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        contentWidth: width - 16
                        clip: true
                        spacing: 4
                        activeFocusOnTab: true
                        keyNavigationEnabled: false
                        currentIndex: -1
                        function syncSelection() {
                            currentIndex = dialog.controller.previewIndex
                            if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
                        }
                        onModelChanged: Qt.callLater(syncSelection)
                        Keys.onUpPressed: event => { dialog.controller.navigate(-1); event.accepted = true }
                        Keys.onDownPressed: event => { dialog.controller.navigate(1); event.accepted = true }
                        Keys.onSpacePressed: event => { if (!event.isAutoRepeat) dialog.controller.toggleCurrent(); event.accepted = true }
                        model: dialog.controller.rows
                        ScrollBar.vertical: ScrollBar {}
                        delegate: ItemDelegate {
                            id: row
                            required property var modelData
                            Keys.forwardTo: [list]
                            width: list.contentWidth
                            height: entry.implicitHeight + 16
                            highlighted: ListView.isCurrentItem
                            onClicked: { list.forceActiveFocus(); dialog.controller.previewRow(modelData.key) }
                            RowLayout {
                                id: entry
                                anchors.fill: parent
                                anchors.margins: 8
                                CheckBox { checked: row.modelData.checked; Accessible.name: "Перенести изменение " + row.modelData.left; onClicked: { list.forceActiveFocus(); dialog.controller.previewRow(row.modelData.key); dialog.controller.check(row.modelData.key, checked) } }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    Label { text: "Здесь " + (row.modelData.left || "—") + " ↔ Там " + (row.modelData.right || "—"); font.weight: Font.DemiBold }
                                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: row.modelData.text; textFormat: Text.PlainText; elide: Text.ElideRight }
                                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: row.modelData.reason; wrapMode: Text.Wrap; color: dialog.colors.muted; font.pixelSize: 11 }
                                }
                            }
                        }
                        Label { anchors.centerIn: parent; width: parent.width - 20; visible: list.count === 0; text: !dialog.controller.referenceName ? "Выберите файл или скопируйте реплики в буфер." : dialog.controller.differenceFilter !== "all" ? "Различий выбранного типа нет. Выберите другой тип или покажите все." : "Различий нет. Можно показать все реплики."; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; color: dialog.colors.muted }
                    }
                }
            }
            ToolCard {
                colors: dialog.colors
                Layout.fillWidth: true
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    Label { text: "3. Проверьте результат"; font.weight: Font.DemiBold }
                    Label { text: "Изменённые слова подчёркнуты"; color: dialog.colors.muted; font.pixelSize: 11 }
                    ScrollView {
                        id: previewScroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        contentWidth: availableWidth
                        clip: true
                        ColumnLayout {
                            width: previewScroll.availableWidth
                            spacing: 10
                            Repeater {
                                model: [{title: "Сейчас в документе", cue: dialog.preview.left || {}, side: false}, {title: "В другом файле", cue: dialog.preview.right || {}, side: true}, {title: "После применения выбранных полей", cue: dialog.preview.after || {}, side: null}]
                                delegate: ColumnLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Label { text: modelData.title; font.weight: Font.DemiBold }
                                    Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: (modelData.cue.time || "") + (modelData.cue.character ? " · " + modelData.cue.character : ""); color: dialog.colors.muted; wrapMode: Text.Wrap }
                                    DialogTextArea { Layout.fillWidth: true; readOnly: true; text: modelData.cue.html || "Выберите пару реплик слева"; wrapMode: TextEdit.Wrap; textFormat: TextEdit.RichText; selectByMouse: true }
                                    Label { Layout.fillWidth: true; visible: !!modelData.cue.style; text: "Стиль: " + (modelData.cue.style || ""); color: dialog.colors.muted; font.pixelSize: 11 }
                                    Button { visible: modelData.side !== null && backend.media.hasMedia; text: "Прослушать этот интервал"; onClicked: dialog.controller.play(modelData.side) }
                                }
                            }
                        }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: "Отмечено всего: " + dialog.controller.chosenCount + " · Изменения можно отменить"; color: dialog.colors.muted }
            Button { text: "Закрыть"; onClicked: dialog.dismiss() }
            Button { objectName: "transferApply"; text: "Применить выбранное (" + dialog.controller.chosenCount + ")"; highlighted: true; enabled: dialog.controller.canApply; onClicked: dialog.controller.apply() }
        }
    }
}
