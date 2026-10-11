import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import Substance 1.0

Pane {
    id: pane
    required property var colors
    padding: 0
    background: Rectangle { color: pane.colors.surface }
    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 100
            color: backend.media.hasMedia ? "black" : pane.colors.surface
            VideoOutput {
                id: video
                objectName: "videoOutput"
                anchors.fill: parent
                fillMode: VideoOutput.PreserveAspectFit
                Component.onCompleted: backend.media.setVideoSink(videoSink)
                AssOverlay {
                    id: overlay
                    x: video.contentRect.x
                    y: video.contentRect.y
                    width: video.contentRect.width
                    height: video.contentRect.height
                    script: backend.previewScript
                    timestamp: backend.media.position
                    videoWidth: backend.media.videoWidth
                    videoHeight: backend.media.videoHeight
                }
                Label {
                    visible: overlay && !overlay.available && backend.media.hasMedia
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 28
                    width: parent.width * 0.9
                    text: backend.fallbackText
                    color: "white"
                    font.pixelSize: 22
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    style: Text.Outline
                    styleColor: "black"
                    textFormat: Text.PlainText
                }
            }
            Button {
                anchors.top: parent.top; anchors.right: parent.right; anchors.margins: 8
                text: "Портрет"; visible: backend.media.hasVideo
                onClicked: backend.capturePortrait(backend.current.characterId || "")
            }
            Column {
                anchors.centerIn: parent
                spacing: 12
                visible: !backend.media.hasMedia
                Label { anchors.horizontalCenter: parent.horizontalCenter; text: "▷"; font.pixelSize: 48; color: pane.colors.muted }
                Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Видео и аудио"; color: pane.colors.text; font.pixelSize: 16 }
                Button { anchors.horizontalCenter: parent.horizontalCenter; text: "Открыть медиа…"; onClicked: backend.openMedia() }
                Label { anchors.horizontalCenter: parent.horizontalCenter; text: "Можно работать и без медиа"; color: pane.colors.muted; font.pixelSize: 11 }
            }
            Label { visible: overlay && !overlay.available; anchors.top: parent.top; anchors.left: parent.left; anchors.margins: 8; text: "Простой предпросмотр · libass не найден"; color: "#d0d8e4"; font.pixelSize: 10 }
        }
        CompactSlider {
            objectName: "positionSlider"
            Layout.fillWidth: true
            Layout.leftMargin: 12
            Layout.rightMargin: 12
            enabled: backend.media.hasMedia
            from: 0; to: Math.max(1, backend.media.duration)
            value: backend.media.position
            onMoved: backend.media.seek(Math.round(value))
            Accessible.name: "Позиция воспроизведения"
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 8
            Layout.rightMargin: 8
            Layout.bottomMargin: 6
            spacing: 6
            ControlButton { symbol: "frame-back"; enabled: backend.media.hasMedia; onClicked: backend.stepFrame(-1); hint: "Предыдущий кадр" }
            ControlButton { objectName: "playButton"; symbol: backend.media.playing ? "pause" : "play"; enabled: backend.media.hasMedia; onClicked: backend.media.toggle(); hint: backend.media.playing ? "Пауза" : "Воспроизведение" }
            ControlButton { symbol: "frame-forward"; enabled: backend.media.hasMedia; onClicked: backend.stepFrame(1); hint: "Следующий кадр" }
            Label { text: pane.time(backend.media.position) + " / " + pane.time(backend.media.duration); color: pane.colors.muted; font.pixelSize: 10; Layout.fillWidth: true; Layout.minimumWidth: 0; elide: Text.ElideRight }
            ComboBox { model: ["0.5×", "0.75×", "1×", "1.25×", "1.5×", "2×"]; currentIndex: 2; implicitWidth: 76; onActivated: backend.media.setRate([0.5, 0.75, 1, 1.25, 1.5, 2][currentIndex]); Accessible.name: "Скорость воспроизведения" }
            CompactSlider { objectName: "volumeSlider"; visible: pane.width > 540; Layout.preferredWidth: 84; value: backend.media.volume; onMoved: backend.media.setVolume(value); Accessible.name: "Громкость" }
        }
        ComboBox { visible: backend.media.audioTracks.length > 1; Layout.fillWidth: true; Layout.margins: 8; model: backend.media.audioTracks; currentIndex: backend.media.activeAudio; onActivated: backend.media.setAudioTrack(currentIndex); Accessible.name: "Аудиодорожка" }
    }
    function time(value) {
        let ms = Math.max(0, value)
        let s = Math.floor(ms / 1000)
        return Math.floor(s / 60).toString().padStart(2, "0") + ":" + (s % 60).toString().padStart(2, "0") + "." + (ms % 1000).toString().padStart(3, "0")
    }
}
