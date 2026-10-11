import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Substance 1.0

Pane {
    id: pane
    required property var colors
    padding: 0
    background: Rectangle { color: pane.colors.surface }
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 12
            Layout.rightMargin: 12
            Layout.topMargin: 4
            Layout.bottomMargin: 4
            spacing: 6
            Label { text: "Аудио"; font.bold: true; color: pane.colors.text }
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
            Layout.minimumHeight: 60
            media: backend.media
            start: backend.current.start
            end: backend.current.end
            neighbors: backend.neighbors
            dark: pane.colors.dark
            paletteColors: pane.colors
            snap: snap.checked
            onSeekRequested: position => backend.media.seek(position)
            onRangeRequested: (start, end) => backend.setRange(start, end)
            Accessible.name: "Аудиотайминг. Перетащите границы реплики. Shift и перетаскивание задаёт интервал."
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 8
            Layout.rightMargin: 8
            Layout.topMargin: 4
            Layout.bottomMargin: 4
            spacing: 6
            ControlButton { symbol: "play"; text: "Реплика"; enabled: backend.media.hasMedia && backend.current.exists; onClicked: backend.playCurrent(false); hint: "Воспроизвести текущую реплику" }
            ControlButton { symbol: "repeat"; enabled: backend.media.hasMedia && backend.current.exists; onClicked: backend.playCurrent(true); hint: "Повторять текущую реплику" }
            Label { visible: pane.width > 700 && !backend.media.busy; text: "Границы — мышью · Shift — выделение · Правая кнопка — прокрутка"; color: pane.colors.muted; font.pixelSize: 10; Layout.fillWidth: true }
            Label { visible: backend.media.busy; text: "Анализ аудио " + Math.round(backend.media.progress * 100) + "%"; color: pane.colors.muted; font.pixelSize: 11; Layout.fillWidth: true }
            ProgressBar { visible: backend.media.busy; value: backend.media.progress; Layout.preferredWidth: 90 }
            Item { Layout.fillWidth: true }
            ControlButton { symbol: "minus"; onClicked: wave.zoom(1.25); hint: "Уменьшить масштаб аудио" }
            ControlButton { symbol: "center"; onClicked: wave.center(); hint: "Показать текущую реплику" }
            ControlButton { symbol: "plus"; onClicked: wave.zoom(0.8); hint: "Увеличить масштаб аудио" }
        }
    }
    Connections { target: backend; function onCenterWaveform() { wave.center() } }
}
