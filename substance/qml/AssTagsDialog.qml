import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    objectName: "assTagsDialog"
    title: "Удаление ASS-тегов"
    preferredWidth: 560
    preferredHeight: 530
    property var tags: []
    property var selected: []
    onOpened: { tags = backend.assTags; selected = [] }
    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        Label {
            Layout.fillWidth: true
            text: "Выберите типы тегов для удаления из итогового текста всех реплик, включая ASS-комментарии. Исходный оригинал сохраняется."
            wrapMode: Text.Wrap
        }
        RowLayout {
            Button { text: "Выбрать все"; enabled: dialog.tags.length > 0; onClicked: dialog.selected = dialog.tags.map(t => t.name) }
            Button { text: "Снять выбор"; onClicked: dialog.selected = [] }
        }
        Label { visible: !dialog.tags.length; text: "ASS-теги в итоговом тексте не найдены."; color: dialog.colors.muted }
        ListView {
            objectName: "assTagsList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: dialog.tags
            ScrollBar.vertical: ScrollBar { }
            delegate: CheckBox {
                required property var modelData
                width: ListView.view.width
                text: modelData.label + "   ·   вхождений: " + modelData.count + "   ·   реплик: " + modelData.lines
                checked: dialog.selected.indexOf(modelData.name) >= 0
                onClicked: {
                    let next = dialog.selected.filter(n => n !== modelData.name)
                    if (checked) next.push(modelData.name)
                    dialog.selected = next
                }
            }
        }
        Label { text: "Операцию можно отменить через «Правка → Отменить»."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            Button { text: "Отмена"; onClicked: dialog.reject() }
            Button {
                objectName: "removeAssTagsButton"
                text: "Удалить выбранные (" + dialog.selected.length + ")"
                enabled: dialog.selected.length > 0 && !backend.busy
                onClicked: { if (backend.removeAssTags(dialog.selected)) dialog.accept() }
            }
        }
    }
}
