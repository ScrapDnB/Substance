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
        detailScroll.contentItem.contentY = 0
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
        shiftWave.setViewport(start, Math.max(2500, end - start))
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
    function focusCueList() {
        search.text = ""
        cues.forceActiveFocus()
        cues.selectCurrent()
    }
    function commitPoint() {
        if (timing.setPoint(targetTime.text)) {
            followPlayer.checked = false
            targetDirty = false
        }
    }
    function showResult() {
        detailScroll.contentItem.contentY = Math.max(0, Math.min(resultCard.y,
            detailScroll.contentItem.contentHeight - detailScroll.availableHeight))
    }
    function shiftText(ms) {
        return (ms > 0 ? "+" : ms < 0 ? "−" : "") + (Math.abs(ms || 0) / 1000).toLocaleString(Qt.locale(), 'f', 3) + " с"
    }
    onPreviewIndexChanged: { if (ready) { loadTarget(); detailScroll.contentItem.contentY = 0 } }
    onOpened: { updateViewport(); Qt.callLater(cues.selectCurrent) }
    onClosed: { ready = false; timing.cancel() }
    Connections {
        target: backend.media
        function onPositionChanged() {
            if (dialog.presented && dialog.pointMode && followPlayer.checked && !targetTime.activeFocus)
                dialog.editTarget(dialog.timing.formatTime(backend.media.position))
        }
    }
    footer: DialogButtonBox {
        leftPadding: 20; rightPadding: 20; bottomPadding: 16; topPadding: 10
        Button {
            objectName: "timingReviewButton"
            text: "Проверить результат ↓"
            visible: dialog.pointMode
            enabled: dialog.timing.points.length > 0 && !dialog.targetDirty
            DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
            onClicked: dialog.showResult()
        }
        Button { text: "Отмена"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole; onClicked: dialog.reject() }
        Button {
            objectName: "applyTimingButton"
            text: "Применить изменения (" + dialog.timing.changedCount + ")"
            enabled: dialog.timing.canApply && !(dialog.pointMode && dialog.targetDirty)
            highlighted: true
            DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            onClicked: { if (dialog.timing.apply()) dialog.dismiss() }
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
            objectName: "timingIntroduction"
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            color: dialog.colors.muted
            text: dialog.pointMode
                ? "Свяжите начало реплики с правильным временем в видео или аудио. По этим опорным точкам Substance пересчитает время остальных реплик."
                : "Задайте направление и величину сдвига. Список и шкала сразу покажут новое время; изменения сохранятся после применения."
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Какие реплики изменить" }
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
                    AppSlider {
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
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12
            ToolCard {
                colors: dialog.colors
                Layout.preferredWidth: dialog.width < 950 ? 280 : 350
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 8
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        text: dialog.pointMode ? "1. Выберите реплику" : "Реплики для проверки"
                        font.weight: Font.DemiBold
                        font.pixelSize: 16
                    }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        color: dialog.colors.muted
                        visible: dialog.pointMode
                        text: "Нажмите на фразу, начало которой легко найти на слух. ● — уже добавленная точка."
                    }
                    DialogTextField {
                        id: search
                        objectName: "timingSearch"
                        Layout.fillWidth: true
                        placeholderText: "Найти текст или № реплики"
                        Accessible.name: "Поиск реплики в предпросмотре"
                    }
                    ListView {
                        id: cues
                        objectName: "timingPreviewList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 4
                        ScrollBar.vertical: ScrollBar { }
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
                            height: 78
                            highlighted: dialog.previewIndex === modelData.index
                            onClicked: { dialog.timing.selectPreview(modelData.index); if (dialog.pointMode) detailScroll.contentItem.contentY = 0 }
                            Accessible.name: "Реплика " + modelData.number + ", " + modelData.text + ", " + modelData.before + ", станет " + modelData.after
                            contentItem: ColumnLayout {
                                spacing: 3
                                Label { text: (modelData.point ? "● " : "") + "№ " + modelData.number + "  " + modelData.text; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true; font.weight: Font.DemiBold }
                                Label { text: "Сейчас: " + modelData.before; color: dialog.colors.muted; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                                Label { text: "После: " + (modelData.error || modelData.after); color: modelData.error ? dialog.colors.warning : dialog.colors.text; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                            }
                        }
                        Label { anchors.centerIn: parent; visible: !cues.count; text: "Реплики не найдены"; color: dialog.colors.muted }
                    }
                }
            }
            ScrollView {
                id: detailScroll
                objectName: "timingDetailScroll"
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                ScrollBar.vertical.policy: ScrollBar.AsNeeded
                ScrollBar.vertical.active: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ColumnLayout {
                    width: detailScroll.availableWidth
                    spacing: 12
                    ToolCard {
                        colors: dialog.colors
                        visible: dialog.pointMode
                        Layout.fillWidth: true
                        implicitHeight: pointSetup.implicitHeight + topPadding + bottomPadding
                        ColumnLayout {
                            id: pointSetup
                            anchors.fill: parent
                            spacing: 8
                            Label { text: "2. Укажите правильное начало"; font.pixelSize: 16; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: "Реплика № " + (dialog.preview.number || "—") + ": " + (dialog.preview.text || ""); textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true; maximumLineCount: 3; elide: Text.ElideRight }
                            Label { objectName: "pointOriginalTime"; text: "Начало в субтитрах: " + dialog.timing.formatTime(dialog.preview.beforeStart || 0); color: dialog.colors.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            Label {
                                text: backend.media.hasMedia
                                    ? "Найдите в плеере момент, когда начинается эта фраза, и поставьте на паузу. Затем возьмите позицию плеера или введите время вручную."
                                    : "Откройте видео или аудио, чтобы найти начало фразы на слух, или введите известное время вручную."
                                color: dialog.colors.muted
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                            }
                            Button { visible: !backend.media.hasMedia; text: "Открыть видео или аудио…"; onClicked: backend.openMedia() }
                            Label { text: "Правильное начало в видео / аудио"; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            RowLayout {
                                Layout.fillWidth: true
                                DialogTextField {
                                    id: targetTime
                                    objectName: "pointTargetTime"
                                    Layout.preferredWidth: 150
                                    Layout.minimumWidth: 120
                                    placeholderText: "00:00:00.000"
                                    Accessible.name: "Правильное начало опорной реплики, часы минуты секунды миллисекунды"
                                    onTextEdited: { dialog.targetDirty = true; dialog.timing.validateTarget(text) }
                                    onAccepted: dialog.commitPoint()
                                }
                                Button { objectName: "pointFromPlayer"; text: "Взять позицию плеера"; enabled: backend.media.hasMedia; onClicked: dialog.editTarget(dialog.timing.formatTime(backend.media.position)) }
                            }
                            Label { text: "Формат: часы:минуты:секунды.миллисекунды · например, 00:01:23.500"; color: dialog.colors.muted; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 6
                                Button { text: "−100 мс"; onClicked: dialog.editTarget(dialog.timing.nudgeTarget(targetTime.text, -100)) }
                                Button { text: "+100 мс"; onClicked: dialog.editTarget(dialog.timing.nudgeTarget(targetTime.text, 100)) }
                                Button {
                                    objectName: "setSyncPoint"
                                    text: dialog.preview.point ? "Обновить точку" : "Добавить точку"
                                    enabled: !dialog.timing.stale && dialog.previewIndex >= 0
                                    highlighted: !dialog.preview.point || dialog.targetDirty
                                    onClicked: dialog.commitPoint()
                                }
                            }
                            Label {
                                objectName: "pointEntryStatus"
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                                color: dialog.targetDirty ? dialog.colors.warning : dialog.colors.muted
                                text: dialog.targetDirty ? "Новое время ещё не учтено. Нажмите «" + (dialog.preview.point ? "Обновить точку" : "Добавить точку") + "»."
                                    : dialog.preview.point ? "✓ Точка добавлена в расчёт. Можно проверить результат ниже или выбрать другую реплику слева."
                                    : "Нажмите «Добавить точку», чтобы включить это время в расчёт."
                            }
                            Waveform {
                                id: wave
                                objectName: "timingWaveform"
                                visible: backend.media.hasMedia
                                Layout.fillWidth: true
                                Layout.preferredHeight: 90
                                media: backend.media
                                paletteColors: dialog.colors
                                start: Math.max(0, dialog.preview.start || 0)
                                end: Math.max(0, dialog.preview.end || 0)
                                onSeekRequested: position => backend.media.seek(position)
                            }
                            Flow {
                                visible: backend.media.hasMedia
                                Layout.fillWidth: true
                                spacing: 6
                                Button { text: "К началу реплики"; onClicked: backend.media.seek(dialog.preview.beforeStart || 0) }
                                Button { text: "−1 с"; onClicked: backend.media.seek(Math.max(0, backend.media.position - 1000)) }
                                Button { text: backend.media.playing ? "Пауза" : "▶ Воспроизвести"; onClicked: backend.media.toggle() }
                                Button { text: "К введённому времени"; enabled: !dialog.timing.error; onClicked: dialog.timing.seekTarget(targetTime.text) }
                                Button { text: "+1 с"; onClicked: backend.media.seek(backend.media.position + 1000) }
                            }
                            Label { visible: backend.media.hasMedia; text: "Позиция плеера: " + dialog.timing.formatTime(backend.media.position); color: dialog.colors.muted }
                            CheckBox {
                                id: followPlayer
                                visible: backend.media.hasMedia
                                text: "Обновлять поле времени при движении плеера"
                                Layout.fillWidth: true
                                contentItem: Label { text: followPlayer.text; wrapMode: Text.Wrap; leftPadding: followPlayer.indicator.width + followPlayer.spacing; verticalAlignment: Text.AlignVCenter }
                                onClicked: { if (checked) dialog.editTarget(dialog.timing.formatTime(backend.media.position)) }
                            }
                        }
                    }
                    ToolCard {
                        id: resultCard
                        objectName: "timingResultCard"
                        colors: dialog.colors
                        Layout.fillWidth: true
                        implicitHeight: resultSetup.implicitHeight + topPadding + bottomPadding
                        ColumnLayout {
                            id: resultSetup
                            anchors.fill: parent
                            spacing: 8
                            Label { text: dialog.pointMode ? "3. Проверьте результат" : "Результат для реплики " + (dialog.preview.number || "—"); font.pixelSize: 16; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            Label { visible: dialog.pointMode; text: "Реплика № " + (dialog.preview.number || "—"); font.weight: Font.DemiBold }
                            Label {
                                objectName: "pointMappingExplanation"
                                visible: dialog.pointMode
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                                text: !dialog.timing.points.length
                                    ? "Пока нет точек — время не меняется. Для начала достаточно одной."
                                    : dialog.timing.points.length === 1
                                        ? "Одна точка: все реплики в выбранной области сдвинутся на " + dialog.shiftText(dialog.timing.points[0].shift) + ". Если к концу файла расхождение растёт, добавьте вторую точку ближе к концу."
                                        : "Точек: " + dialog.timing.points.length + ". Между ними время пересчитывается плавно, чтобы исправить нарастающее расхождение. До первой и после последней точки продолжается темп ближайшего участка."
                                color: dialog.colors.muted
                            }
                            Label { visible: !dialog.pointMode; text: dialog.preview.text || ""; textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true; maximumLineCount: 3; elide: Text.ElideRight }
                            Label { text: "Сейчас: " + (dialog.preview.before || "—"); wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted }
                            Label { objectName: "timingAfterResult"; text: "После применения: " + (dialog.preview.after || "—"); wrapMode: Text.Wrap; Layout.fillWidth: true; font.weight: Font.DemiBold }
                            TimingComparison { Layout.fillWidth: true; Layout.preferredHeight: 68; colors: dialog.colors; preview: dialog.preview }
                            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; color: dialog.colors.muted; text: "Сдвиг начала: " + dialog.shiftText(dialog.preview.shift) + " · конца: " + dialog.shiftText(dialog.preview.endShift) }
                            Waveform {
                                id: shiftWave
                                objectName: "shiftWaveform"
                                visible: !dialog.pointMode && backend.media.hasMedia
                                Layout.fillWidth: true
                                Layout.preferredHeight: 100
                                media: backend.media
                                paletteColors: dialog.colors
                                start: Math.max(0, dialog.preview.start || 0)
                                end: Math.max(0, dialog.preview.end || 0)
                                onSeekRequested: position => backend.media.seek(position)
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 6
                                Button { visible: !dialog.pointMode; text: "К началу реплики"; enabled: backend.media.hasMedia; onClicked: backend.media.seek(dialog.preview.beforeStart || 0) }
                                Button { objectName: "timingPlayBefore"; text: "▶ Прослушать сейчас"; enabled: backend.media.hasMedia && !dialog.timing.stale; onClicked: dialog.timing.play(dialog.previewIndex, false) }
                                Button { objectName: "timingPlayAfter"; text: "▶ Прослушать результат"; enabled: backend.media.hasMedia && !dialog.timing.error; onClicked: dialog.timing.play(dialog.previewIndex, true) }
                            }
                            Button { visible: !dialog.pointMode && !backend.media.hasMedia; text: "Открыть видео или аудио…"; onClicked: backend.openMedia() }
                            Label { text: "Изменятся реплики: " + dialog.timing.changedCount + " из " + dialog.timing.affectedCount; font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                    ToolCard {
                        colors: dialog.colors
                        visible: dialog.pointMode
                        Layout.fillWidth: true
                        implicitHeight: savedPoints.implicitHeight + topPadding + bottomPadding
                        ColumnLayout {
                            id: savedPoints
                            anchors.fill: parent
                            spacing: 8
                            RowLayout {
                                Layout.fillWidth: true
                                Label { text: "Добавленные точки (" + dialog.timing.points.length + ")"; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
                                Button { text: "Удалить все"; enabled: dialog.timing.points.length > 0; onClicked: { dialog.timing.clearPoints(); dialog.loadTarget() } }
                            }
                            Label { visible: !dialog.timing.points.length; text: "Здесь появятся пары «начало в субтитрах → правильное начало»."; color: dialog.colors.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            ListView {
                                id: pointList
                                objectName: "syncPointsList"
                                Layout.fillWidth: true
                                Layout.preferredHeight: Math.min(180, contentHeight)
                                clip: true
                                spacing: 4
                                model: dialog.timing.points
                                activeFocusOnTab: true
                                ScrollBar.vertical: ScrollBar { }
                                Keys.onDeletePressed: { if (currentItem) { dialog.timing.removePoint(currentItem.modelData.index); dialog.loadTarget() } }
                                Keys.onPressed: event => {
                                    if (event.key === Qt.Key_Backspace && currentItem) {
                                        dialog.timing.removePoint(currentItem.modelData.index)
                                        dialog.loadTarget()
                                        event.accepted = true
                                    }
                                }
                                delegate: RowLayout {
                                    required property var modelData
                                    required property int index
                                    width: pointList.width - 16
                                    height: 54
                                    ItemDelegate {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        highlighted: dialog.previewIndex === modelData.index
                                        contentItem: ColumnLayout {
                                            Label { text: "№ " + modelData.number + " · " + dialog.shiftText(modelData.shift); font.weight: Font.DemiBold }
                                            Label { text: modelData.source + " → " + modelData.target; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                                        }
                                        onClicked: { pointList.currentIndex = index; dialog.timing.selectPreview(modelData.index); dialog.loadTarget(); detailScroll.contentItem.contentY = 0 }
                                    }
                                    Button { text: "×"; Layout.preferredWidth: 36; Accessible.name: "Удалить точку реплики " + modelData.number; onClicked: { dialog.timing.removePoint(modelData.index); dialog.loadTarget() } }
                                }
                            }
                            Button { visible: dialog.timing.points.length > 0; text: "Выбрать другую реплику…"; onClicked: dialog.focusCueList() }
                        }
                    }
                }
            }
        }
        Label {
            objectName: "timingStatus"
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            color: dialog.timing.error ? dialog.colors.warning : dialog.colors.muted
            text: dialog.timing.error || (dialog.pointMode && dialog.targetDirty ? "Время ещё не добавлено в расчёт. Нажмите «" + (dialog.preview.point ? "Обновить точку" : "Добавить точку") + "» в шаге 2."
                : dialog.pointMode && !dialog.timing.points.length ? "Добавьте первую точку в шаге 2. Одна точка задаёт общий сдвиг; несколько исправляют нарастающее расхождение."
                : "Предпросмотр: изменятся " + dialog.timing.changedCount + " из " + dialog.timing.affectedCount + " реплик. Примените изменения; отмена — одним действием.")
        }
    }
    Connections {
        target: dialog.timing
        function onChanged() {
            if (dialog.presented) { dialog.updateViewport(); Qt.callLater(cues.selectCurrent) }
        }
    }
}
