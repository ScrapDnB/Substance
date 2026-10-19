import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "frameIndexDialog"
    title: "Точные времена кадров"
    preferredWidth: 640
    preferredHeight: 420
    modal: false
    readonly property var controller: backend.frameIndex
    ColumnLayout {
        anchors.fill: parent
        spacing: 16
        Label { text: "Тайминг по реальным кадрам"; font.pixelSize: 24; font.weight: Font.DemiBold }
        Label { Layout.fillWidth: true; wrapMode: Text.Wrap; text: "Прочитайте времена кадров открытого видео. После этого кнопки «Предыдущий / следующий кадр» и округление реплик будут использовать реальные кадры, включая видео с переменной частотой." }
        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: backend.media.name; elide: Text.ElideMiddle; font.weight: Font.DemiBold }
        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.controller.count ? "В индексе: " + dialog.controller.count + " кадров · " + (dialog.controller.variableRate ? "Переменная частота" : "Равномерная сетка кадров") : "До чтения используется сетка " + backend.fps.toFixed(3) + " кадр/с."; wrapMode: Text.Wrap; color: dialog.colors.muted }
        ProgressBar { Layout.fillWidth: true; visible: dialog.controller.busy; value: dialog.controller.progress; indeterminate: value === 0 }
        Label { Layout.fillWidth: true; Layout.minimumWidth: 0; text: dialog.controller.status; wrapMode: Text.Wrap }
        Item { Layout.fillHeight: true }
        RowLayout {
            Layout.fillWidth: true
            Button { text: "Подключить видео…"; enabled: !dialog.controller.busy; onClicked: backend.openMedia() }
            Item { Layout.fillWidth: true }
            Button { text: "Закрыть"; onClicked: dialog.dismiss() }
            Button { objectName: "buildFrameIndex"; text: dialog.controller.busy ? "Остановить" : dialog.controller.count ? "Прочитать заново" : "Прочитать кадры"; highlighted: true; enabled: backend.media.hasVideo || dialog.controller.busy; onClicked: dialog.controller.busy ? dialog.controller.cancel() : dialog.controller.build() }
        }
    }
}
