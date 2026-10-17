import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Substance 1.0

Pane {
    id: pane
    required property var colors
    readonly property real uiScale: backend.appearance.general.uiScale / 100
    readonly property bool compactControls: width < 1000 * uiScale
    padding: 0
    background: Rectangle { color: pane.colors.surface }
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        RowLayout {
            id: audioHeader
            Layout.fillWidth: true
            Layout.leftMargin: 12
            Layout.rightMargin: 12
            Layout.topMargin: 4
            Layout.bottomMargin: 4
            spacing: 6
            Label { text: pane.compactControls && backend.media.busy ? "Аудио · " + Math.round(backend.media.progress * 100) + "%" : "Аудио"; font.bold: true; color: pane.colors.text }
            Item { Layout.fillWidth: true }
            CheckBox {
                id: snap; text: "Привязка"; checked: true
                NativeToolTip { text: "Ключевые кадры и границы соседних реплик" }
            }
            SegmentedSelector {
                objectName: "audioDisplaySelector"
                labels: ["Волна", "Спектр"]
                selectedIndex: wave.spectral ? 1 : 0
                onActivated: index => wave.spectral = index === 1
                Accessible.name: "Отображение аудио"
            }
        }
        Waveform {
            id: wave
            objectName: "audioWaveform"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: pane.compactControls ? 40 : 60
            media: backend.media
            start: backend.current.start
            end: backend.current.end
            neighbors: backend.neighbors
            dark: pane.colors.dark
            paletteColors: pane.colors
            timecodeFont: Qt.font({family: backend.appearance.timecodeFamily, bold: backend.appearance.timecodeBold, pixelSize: backend.appearance.general.timecodeSize})
            waveGain: backend.appearance.audio.waveGain / 100
            spectralContrast: backend.appearance.audio.spectralContrast / 100
            snap: snap.checked
            onSeekRequested: position => backend.media.seek(position)
            onRangeRequested: (start, end) => backend.setRange(start, end)
            Accessible.name: "Аудиотайминг. Перетащите границы реплики. Shift и перетаскивание задаёт интервал."
        }
        GridLayout {
            id: audioControls
            objectName: "audioControls"
            columns: pane.compactControls ? 1 : 2
            Layout.fillWidth: true
            Layout.leftMargin: 8
            Layout.rightMargin: 8
            Layout.topMargin: 4
            Layout.bottomMargin: 4
            columnSpacing: 12
            rowSpacing: 0
            RowLayout {
                // On narrow panels playback fits beside the display selector,
                // leaving the entire footer for the audio adjustment controls.
                parent: pane.compactControls ? audioHeader : audioControls
                Layout.fillWidth: !pane.compactControls
                Layout.column: 0
                Layout.row: 0
                spacing: 6
                ControlButton { symbol: "play"; text: "Реплика"; enabled: backend.media.hasMedia && backend.current.exists; onClicked: backend.playCurrent(false); hint: "Воспроизвести текущую реплику" }
                ControlButton { symbol: "repeat"; enabled: backend.media.hasMedia && backend.current.exists; onClicked: backend.playCurrent(true); hint: "Повторять текущую реплику" }
                Label {
                    visible: !pane.compactControls
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    elide: Text.ElideRight
                    text: backend.media.busy ? "Анализ аудио " + Math.round(backend.media.progress * 100) + "%" : "Shift — выделение · Правая кнопка — прокрутка"
                    color: pane.colors.muted
                    font.pixelSize: Math.round(10 * pane.uiScale)
                }
                ProgressBar { visible: backend.media.busy && !pane.compactControls; value: backend.media.progress; Layout.preferredWidth: 60 }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.column: pane.compactControls ? 0 : 1
                Layout.row: 0
                spacing: 6
                Label {
                    text: (pane.width < 800 * pane.uiScale ? "Звук" : "Громкость") + " · " + Math.round(backend.media.volume * 100) + "%"
                    color: pane.colors.muted
                    font.pixelSize: Math.round(11 * pane.uiScale)
                    Layout.minimumWidth: implicitWidth
                }
                CompactSlider {
                    objectName: "audioVolumeSlider"
                    Layout.preferredWidth: 80
                    Layout.minimumWidth: 40
                    Layout.fillWidth: true
                    from: 0; to: 100; stepSize: 1
                    value: Math.round(backend.media.volume * 100)
                    onMoved: backend.media.setVolume(Math.round(value) / 100)
                    Accessible.name: "Громкость звука"
                    NativeToolTip { text: "Громкость воспроизведения · " + Math.round(backend.media.volume * 100) + "%" }
                }
                Label {
                    text: (wave.spectral ? "Контраст" : pane.width < 800 * pane.uiScale ? "Волна" : "Высота волны") + " · " + (wave.spectral ? backend.appearance.audio.spectralContrast : backend.appearance.audio.waveGain) + "%"
                    color: pane.colors.muted
                    font.pixelSize: Math.round(11 * pane.uiScale)
                    Layout.minimumWidth: implicitWidth
                }
                CompactSlider {
                    objectName: "waveGainSlider"
                    visible: !wave.spectral
                    Layout.preferredWidth: 90
                    Layout.minimumWidth: 40
                    Layout.fillWidth: true
                    from: -2; to: 3; stepSize: 0.25
                    value: Math.log(backend.appearance.audio.waveGain / 100) / Math.LN2
                    onMoved: backend.appearance.setValue("audio", "waveGain", Math.round(Math.pow(2, value) * 100))
                    Accessible.name: "Вертикальный масштаб волны"
                    NativeToolTip { text: "Высота волны · 25–800%. Исходный масштаб — 100%. Громкость не меняется." }
                }
                CompactSlider {
                    objectName: "spectralContrastSlider"
                    visible: wave.spectral
                    Layout.preferredWidth: 90
                    Layout.minimumWidth: 40
                    Layout.fillWidth: true
                    from: 25; to: 300; stepSize: 5
                    value: backend.appearance.audio.spectralContrast
                    onMoved: backend.appearance.setValue("audio", "spectralContrast", Math.round(value))
                    Accessible.name: "Контрастность спектра"
                    NativeToolTip { text: "Контрастность спектра · 25–300%. Исходный контраст — 100%." }
                }
                ControlButton { symbol: "minus"; onClicked: wave.zoom(1.25); hint: "Уменьшить горизонтальный масштаб аудио" }
                ControlButton { symbol: "center"; onClicked: wave.center(); hint: "Показать текущую реплику" }
                ControlButton { symbol: "plus"; onClicked: wave.zoom(0.8); hint: "Увеличить горизонтальный масштаб аудио" }
            }
        }
    }
    Connections { target: backend; function onCenterWaveform() { wave.center() } }
}
