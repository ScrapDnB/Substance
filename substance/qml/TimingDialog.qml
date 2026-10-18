import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Substance 1.0

NativeDialog {
    id: dialog
    objectName: "shiftDialog"
    readonly property var timing: backend.timingTools
    readonly property bool pointMode: timing.kind === "points"
    readonly property var preview: timing.preview
    property bool ready: false
    property bool targetDirty: false
    property int directionIndex: 1
    property int previewIndex: preview.index === undefined ? -1 : preview.index
    title: pointMode ? "Точечная синхронизация" : "Сдвиг времени"
    modal: false
    preferredWidth: 1080
    preferredHeight: 880
    minimumWidth: Math.min(800, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(660, Screen.desktopAvailableHeight - 80)

    function prepare() {
        ready = false
        scope.currentIndex = 0
        directionIndex = 1
        amount.value = 0
        edges.currentIndex = 0
        search.text = ""
        followPlayer.checked = false
        loadTarget()
        ready = true
    }
    function updateShift() {
        if (ready) timing.setShift((directionIndex === 0 ? -1 : 1) * amount.value, ["both", "start", "end"][edges.currentIndex])
    }
    function shiftTo(value) {
        directionIndex = value < 0 ? 0 : 1
        amount.value = Math.min(amount.to, Math.abs(Math.round(value)))
        updateShift()
    }
    function updateViewport() {
        if (!preview.number) return
        let start = Math.max(0, Math.min(preview.beforeStart, preview.start) - 700)
        let end = Math.max(preview.beforeEnd, preview.end) + 700
        wave.setViewport(start, Math.max(2500, end - start))
    }
    function loadTarget() {
        let point = timing.points.find(p => p.index === previewIndex)
        targetTime.text = point ? point.target : timing.formatTime(preview.beforeStart || 0)
        targetDirty = false
    }
    function editTarget(value) {
        targetTime.text = value
        targetDirty = true
        timing.validateTarget(value)
    }
    function commitPoint() {
        if (timing.setPoint(targetTime.text)) {
            followPlayer.checked = false
            targetDirty = false
        }
    }
    function shiftText(ms) {
        return (ms > 0 ? "+" : ms < 0 ? "−" : "") + (Math.abs(ms || 0) / 1000).toLocaleString(Qt.locale(), 'f', 3) + " с"
    }
    onPreviewIndexChanged: { if (ready) loadTarget() }
    onOpened: { updateViewport(); Qt.callLater(cues.selectCurrent) }
    onClosed: { ready = false; timing.cancel() }
    Connections {
        target: backend.media
        function onPositionChanged() {
            if (dialog.visible && dialog.pointMode && followPlayer.checked && !targetTime.activeFocus)
                dialog.editTarget(dialog.timing.formatTime(backend.media.position))
        }
    }
    footer: DialogButtonBox {
        leftPadding: 20; rightPadding: 20; bottomPadding: 16; topPadding: 10
        Button { text: "Отмена"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole; onClicked: dialog.reject() }
        Button {
            objectName: "applyTimingButton"
            text: "Применить к репликам: " + dialog.timing.changedCount
            enabled: dialog.timing.canApply && !(dialog.pointMode && dialog.targetDirty)
            highlighted: true
            DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            onClicked: { if (dialog.timing.apply()) dialog.close() }
        }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Label { text: dialog.title; font.pixelSize: 24; font.weight: Font.DemiBold; Layout.fillWidth: true }
            Button {
                text: dialog.pointMode ? "Обычный сдвиг…" : "По опорным точкам…"
                onClicked: dialog.pointMode ? backend.openShift() : backend.openPointSync()
            }
        }
        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            color: dialog.colors.muted
            text: dialog.pointMode
                ? "1. Выберите реплику ниже.  2. Найдите её правильное начало в плеере или введите время.  3. Добавьте точку и проверьте результат."
                : "Задайте направление и величину сдвига. Список и шкала сразу покажут новое время; изменения сохранятся после применения."
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Изменить" }
            ComboBox {
                id: scope
                objectName: "timingScope"
                Layout.fillWidth: true
                model: ["Весь документ (" + backend.count + ")", "Выделенные при открытии (" + dialog.timing.selectedCount + ")", "От реплики " + dialog.timing.currentNumber + " до конца"]
                onActivated: index => { dialog.timing.setScope(["all", "selected", "following"][index]); dialog.loadTarget() }
                Accessible.name: "Какие реплики изменить"
            }
            ComboBox {
                id: edges
                objectName: "timingEdges"
                visible: !dialog.pointMode
                model: ["Начало и конец", "Только начало", "Только конец"]
                onActivated: dialog.updateShift()
                Accessible.name: "Границы для сдвига"
            }
        }
        ToolCard {
            colors: dialog.colors
            Layout.fillWidth: true
            visible: !dialog.pointMode
            implicitHeight: shiftSetup.implicitHeight + 24
            ColumnLayout {
                id: shiftSetup
                anchors.fill: parent
                spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    SegmentedSelector {
                        id: direction
                        objectName: "shiftDirection"
                        labels: ["← Раньше", "Позже →"]
                        selectedIndex: dialog.directionIndex
                        onActivated: index => { dialog.directionIndex = index; dialog.updateShift() }
                        Layout.preferredWidth: 220
                    }
                    SpinBox {
                        id: amount
                        objectName: "shiftAmount"
                        from: 0; to: 86400000; stepSize: 10
                        editable: true
                        Layout.preferredWidth: 180
                        onValueChanged: dialog.updateShift()
                        Accessible.name: "Величина сдвига в миллисекундах"
                    }
                    Label { text: "мс" }
                    Label { text: dialog.shiftText(dialog.timing.delta); font.pixelSize: 20; font.weight: Font.DemiBold; Layout.fillWidth: true; horizontalAlignment: Text.AlignRight }
                    Button { text: "Сбросить"; onClicked: amount.value = 0 }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "0 с"; color: dialog.colors.muted }
                    Slider {
                        objectName: "shiftSlider"
                        Layout.fillWidth: true
                        from: 0; to: 10000; stepSize: 10
                        value: Math.min(10000, amount.value)
                        onMoved: amount.value = value
                        Accessible.name: "Сдвиг от нуля до десяти секунд"
                    }
                    Label { text: "10 с"; color: dialog.colors.muted }
                    Repeater {
                        model: [100, 500, 1000, 5000]
                        Button { required property int modelData; text: modelData < 1000 ? modelData + " мс" : modelData / 1000 + " с"; onClicked: amount.value = modelData }
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 6
                    Button { text: "−1 кадр"; onClicked: dialog.shiftTo(dialog.timing.delta - Math.round(1000 / backend.fps)) }
                    Button { text: "+1 кадр"; onClicked: dialog.shiftTo(dialog.timing.delta + Math.round(1000 / backend.fps)) }
                    Button {
                        text: edges.currentIndex === 2 ? "Совместить конец с плеером" : "Совместить начало с плеером"
                        enabled: backend.media.hasMedia && !!dialog.preview.number
                        onClicked: dialog.shiftTo(backend.media.position - (edges.currentIndex === 2 ? dialog.preview.beforeEnd : dialog.preview.beforeStart))
                    }
                }
            }
        }
        ToolCard {
            colors: dialog.colors
            Layout.fillWidth: true
            visible: dialog.pointMode
            implicitHeight: pointSetup.implicitHeight + 24
            RowLayout {
                id: pointSetup
                anchors.fill: parent
                spacing: 16
                ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                spacing: 8
                Label {
                    Layout.fillWidth: true
                    text: "Правильное начало реплики " + (dialog.preview.number || "—")
                    font.weight: Font.DemiBold
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    DialogTextField {
                        id: targetTime
                        objectName: "pointTargetTime"
                        Layout.preferredWidth: 165
                        placeholderText: "00:00:00.000"
                        Accessible.name: "Правильное начало опорной реплики, часы минуты секунды миллисекунды"
                        onTextEdited: { dialog.targetDirty = true; dialog.timing.validateTarget(text) }
                        onAccepted: dialog.commitPoint()
                    }
                    Button { objectName: "pointFromPlayer"; text: "Из плеера"; enabled: backend.media.hasMedia; onClicked: dialog.editTarget(dialog.timing.formatTime(backend.media.position)) }
                    Item { Layout.fillWidth: true }
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 6
                    Button { text: "−100 мс"; onClicked: dialog.editTarget(dialog.timing.nudgeTarget(targetTime.text, -100)) }
                    Button { text: "+100 мс"; onClicked: dialog.editTarget(dialog.timing.nudgeTarget(targetTime.text, 100)) }
                    Button {
                        objectName: "setSyncPoint"
                        text: dialog.preview.point ? "Обновить точку" : "Добавить точку"
                        enabled: !dialog.timing.stale && dialog.previewIndex >= 0
                        highlighted: dialog.targetDirty
                        onClicked: dialog.commitPoint()
                    }
                }
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    color: dialog.colors.muted
                    text: dialog.timing.points.length < 2
                        ? "Одна точка задаёт общий сдвиг. Две и более исправляют расхождение скорости по участкам."
                        : "Между точками — плавный пересчёт. За крайними точками — скорость ближайшего участка."
                }
                }
                ColumnLayout {
                Layout.preferredWidth: dialog.width < 950 ? 310 : 430
                Layout.alignment: Qt.AlignTop
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Опорные точки: " + dialog.timing.points.length; font.weight: Font.DemiBold; Layout.fillWidth: true }
                    Button { text: "Удалить все"; enabled: dialog.timing.points.length > 0; onClicked: { dialog.timing.clearPoints(); dialog.loadTarget() } }
                }
                ListView {
                    id: pointList
                    objectName: "syncPointsList"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 104
                    clip: true
                    spacing: 2
                    model: dialog.timing.points
                    activeFocusOnTab: true
                    ScrollBar.vertical: ScrollBar { }
                    Keys.onDeletePressed: { if (currentItem) dialog.timing.removePoint(currentItem.modelData.index) }
                    Keys.onPressed: event => {
                        if (event.key === Qt.Key_Backspace && currentItem) {
                            dialog.timing.removePoint(currentItem.modelData.index)
                            event.accepted = true
                        }
                    }
                    delegate: RowLayout {
                        required property var modelData
                        required property int index
                        width: pointList.width - 16
                        height: 48
                        ItemDelegate {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            highlighted: dialog.previewIndex === modelData.index
                            contentItem: ColumnLayout {
                                Label { text: "№ " + modelData.number + " · " + dialog.shiftText(modelData.shift); font.weight: Font.DemiBold }
                                Label { text: modelData.source + " → " + modelData.target; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                            }
                            onClicked: { pointList.currentIndex = index; dialog.timing.selectPreview(modelData.index); dialog.loadTarget() }
                        }
                        Button { text: "×"; Layout.preferredWidth: 36; Accessible.name: "Удалить точку реплики " + modelData.number; onClicked: { dialog.timing.removePoint(modelData.index); dialog.loadTarget() } }
                    }
                    Label { anchors.centerIn: parent; width: parent.width - 10; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; visible: !pointList.count; text: "Точки появятся здесь после добавления"; color: dialog.colors.muted }
                }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Проверка · реплик: " + dialog.timing.affectedCount + " · изменятся: " + dialog.timing.changedCount; font.weight: Font.DemiBold; Layout.fillWidth: true }
            DialogTextField { id: search; objectName: "timingSearch"; Layout.preferredWidth: 240; placeholderText: "Найти текст или № реплики"; Accessible.name: "Поиск реплики в предпросмотре" }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12
            ScrollView {
                Layout.preferredWidth: dialog.width < 950 ? 290 : 370
                Layout.fillHeight: true
                clip: true
                ListView {
                    id: cues
                    objectName: "timingPreviewList"
                    clip: true
                    spacing: 4
                    model: dialog.timing.rows.filter(r => !search.text.trim() || r.text.toLocaleLowerCase().indexOf(search.text.trim().toLocaleLowerCase()) >= 0 || String(r.number) === search.text.trim())
                    function selectCurrent() {
                        currentIndex = model.findIndex(r => r.index === dialog.previewIndex)
                        if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
                    }
                    onModelChanged: Qt.callLater(selectCurrent)
                    activeFocusOnTab: true
                    Keys.onUpPressed: { let row = model[Math.max(0, currentIndex - 1)]; if (row) dialog.timing.selectPreview(row.index) }
                    Keys.onDownPressed: { let row = model[Math.min(count - 1, currentIndex + 1)]; if (row) dialog.timing.selectPreview(row.index) }
                    delegate: ItemDelegate {
                        required property var modelData
                        required property int index
                        width: cues.width
                        height: 70
                        highlighted: dialog.previewIndex === modelData.index
                        onClicked: dialog.timing.selectPreview(modelData.index)
                        Accessible.name: "Реплика " + modelData.number + ", " + modelData.text + ", " + modelData.before + ", станет " + modelData.after
                        contentItem: ColumnLayout {
                            spacing: 3
                            Label { text: (modelData.point ? "● " : "") + "№ " + modelData.number + "  " + modelData.text; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true; font.weight: Font.DemiBold }
                            Label { text: modelData.before; color: dialog.colors.muted; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                            Label { text: "→ " + (modelData.error || modelData.after); color: modelData.error ? dialog.colors.warning : dialog.colors.text; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                        }
                    }
                    Label { anchors.centerIn: parent; visible: !cues.count; text: "Реплики не найдены"; color: dialog.colors.muted }
                }
            }
            ScrollView {
                id: detailScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: detailScroll.availableWidth
                    spacing: 8
                    Label { text: "Реплика " + (dialog.preview.number || "—"); font.weight: Font.DemiBold }
                    Label { text: dialog.preview.text || ""; textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true; maximumLineCount: 3; elide: Text.ElideRight }
                    Label { text: "Сейчас: " + (dialog.preview.before || "—"); wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted }
                    Label { text: "После: " + (dialog.preview.after || "—"); wrapMode: Text.Wrap; Layout.fillWidth: true; font.weight: Font.DemiBold }
                    TimingComparison { Layout.fillWidth: true; Layout.preferredHeight: 68; colors: dialog.colors; preview: dialog.preview }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        color: dialog.colors.muted
                        text: "Сдвиг начала: " + dialog.shiftText(dialog.preview.shift) + " · конца: " + dialog.shiftText(dialog.preview.endShift)
                    }
                    Waveform {
                        id: wave
                        objectName: "timingWaveform"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 100
                        media: backend.media
                        paletteColors: dialog.colors
                        start: Math.max(0, dialog.preview.start || 0)
                        end: Math.max(0, dialog.preview.end || 0)
                        onSeekRequested: position => backend.media.seek(position)
                    }
                    RowLayout {
                        Button { text: "▶ Сейчас"; enabled: backend.media.hasMedia && !dialog.timing.stale; onClicked: dialog.timing.play(dialog.previewIndex, false) }
                        Button { text: "▶ После"; enabled: backend.media.hasMedia && !dialog.timing.error; onClicked: dialog.timing.play(dialog.previewIndex, true) }
                        Button { text: "К началу"; enabled: backend.media.hasMedia; onClicked: backend.media.seek(dialog.preview.beforeStart || 0) }
                    }
                    RowLayout {
                        visible: dialog.pointMode
                        Button { text: "−1 с"; enabled: backend.media.hasMedia; onClicked: backend.media.seek(Math.max(0, backend.media.position - 1000)) }
                        Button { text: backend.media.playing ? "Пауза" : "▶ Плеер"; enabled: backend.media.hasMedia; onClicked: backend.media.toggle() }
                        Button { text: "+1 с"; enabled: backend.media.hasMedia; onClicked: backend.media.seek(backend.media.position + 1000) }
                        Button { text: "К точке"; enabled: backend.media.hasMedia; onClicked: dialog.timing.seekTarget(targetTime.text) }
                    }
                    CheckBox { id: followPlayer; visible: dialog.pointMode; text: "Подставлять позицию плеера в поле времени"; enabled: backend.media.hasMedia; onClicked: { if (checked) dialog.editTarget(dialog.timing.formatTime(backend.media.position)) } }
                    Label { visible: backend.media.hasMedia; text: "Плеер: " + dialog.timing.formatTime(backend.media.position); color: dialog.colors.muted }
                    Button { visible: !backend.media.hasMedia; text: "Открыть видео или аудио…"; onClicked: backend.openMedia() }
                }
            }
        }
        Label {
            objectName: "timingStatus"
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            color: dialog.timing.error ? dialog.colors.warning : dialog.colors.muted
            text: dialog.timing.error || (dialog.pointMode && dialog.targetDirty ? "Время в поле изменено. Нажмите «Добавить точку» или «Обновить точку», чтобы включить его в расчёт."
                : "Предпросмотр. Применение обновит только выбранную область. Все изменения можно отменить одним действием.")
        }
    }
    Connections {
        target: dialog.timing
        function onChanged() {
            if (dialog.visible) { dialog.updateViewport(); Qt.callLater(cues.selectCurrent) }
        }
    }
}
