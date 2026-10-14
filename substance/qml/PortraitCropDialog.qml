import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    property real cropX: 0
    property real cropY: 0
    property real cropW: 1
    property real cropH: 1
    property real lockedRatio: 0
    title: "Портрет персонажа — обрезка"
    preferredWidth: 980
    preferredHeight: 760
    modal: true
    standardButtons: Dialog.NoButton
    function clamp(value, min, max) { return Math.min(max, Math.max(min, value)) }
    function resetCrop() {
        let r = backend.captureInfo.crop || [0, 0, 1, 1]
        cropX = r[0]; cropY = r[1]; cropW = r[2]; cropH = r[3]
        lockedRatio = 0; proportions.currentIndex = 0
        recipient.currentIndex = Math.max(0, backend.characterCards.findIndex(c => c.id === backend.captureInfo.cardId) + 1)
        newName.text = ""; primary.checked = backend.captureInfo.primary === undefined ? true : backend.captureInfo.primary
    }
    function setRatio(value) {
        lockedRatio = value
        proportions.currentIndex = value === 1 ? 1 : value === .75 ? 2 : 0
        if (!value) return
        let ratioN = value * backend.captureInfo.height / backend.captureInfo.width
        let w = Math.min(cropW, cropH * ratioN)
        let h = w / ratioN
        cropX += (cropW - w) / 2; cropY += (cropH - h) / 2
        cropW = w; cropH = h
    }
    function resizeCrop(corner, px, py, initial) {
        let left = initial[0], top = initial[1], right = left + initial[2], bottom = top + initial[3]
        let west = corner === 0 || corner === 2
        let north = corner === 0 || corner === 1
        let anchorX = west ? right : left, anchorY = north ? bottom : top
        let w = Math.max(0.02, west ? anchorX - px : px - anchorX)
        let h = Math.max(0.02, north ? anchorY - py : py - anchorY)
        let maxW = west ? anchorX : 1 - anchorX, maxH = north ? anchorY : 1 - anchorY
        if (lockedRatio) {
            let rn = lockedRatio * backend.captureInfo.height / backend.captureInfo.width
            w = Math.min(w, h * rn, maxW, maxH * rn); h = w / rn
        } else { w = Math.min(w, maxW); h = Math.min(h, maxH) }
        cropX = west ? anchorX - w : anchorX; cropY = north ? anchorY - h : anchorY
        cropW = w; cropH = h
    }
    onOpened: resetCrop()
    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Перемещайте рамку и тяните за её углы."; Layout.fillWidth: true; color: dialog.colors.muted }
            ComboBox { id: proportions; model: ["Свободно", "Квадрат 1:1", "Портрет 3:4"]; onActivated: dialog.setRatio([0, 1, .75][currentIndex]) }
            Button { text: "Весь кадр"; onClicked: { dialog.cropX = 0; dialog.cropY = 0; dialog.cropW = 1; dialog.cropH = 1; dialog.lockedRatio = 0; proportions.currentIndex = 0 } }
        }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            Item {
                id: available
                Layout.fillWidth: true; Layout.fillHeight: true
                Item {
                    id: imageBox
                    anchors.centerIn: parent
                    width: Math.min(available.width, available.height * backend.captureInfo.width / Math.max(1, backend.captureInfo.height))
                    height: width * backend.captureInfo.height / Math.max(1, backend.captureInfo.width)
                    Image { anchors.fill: parent; source: backend.captureInfo.url; cache: false; fillMode: Image.Stretch }
                    Rectangle { x: 0; y: 0; width: imageBox.width; height: selection.y; color: "#88000000" }
                    Rectangle { x: 0; y: selection.y; width: selection.x; height: selection.height; color: "#88000000" }
                    Rectangle { x: selection.x + selection.width; y: selection.y; width: imageBox.width - x; height: selection.height; color: "#88000000" }
                    Rectangle { x: 0; y: selection.y + selection.height; width: imageBox.width; height: imageBox.height - y; color: "#88000000" }
                    Rectangle {
                        id: selection
                        objectName: "portraitCropRect"
                        x: dialog.cropX * imageBox.width; y: dialog.cropY * imageBox.height
                        width: dialog.cropW * imageBox.width; height: dialog.cropH * imageBox.height
                        color: "transparent"; border.color: "white"; border.width: 2
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.SizeAllCursor
                            property var initial
                            property point press
                            onPressed: mouse => { initial = [dialog.cropX, dialog.cropY]; press = mapToItem(imageBox, mouse.x, mouse.y) }
                            onPositionChanged: mouse => {
                                if (!pressed) return
                                let p = mapToItem(imageBox, mouse.x, mouse.y)
                                dialog.cropX = dialog.clamp(initial[0] + (p.x-press.x)/imageBox.width, 0, 1-dialog.cropW)
                                dialog.cropY = dialog.clamp(initial[1] + (p.y-press.y)/imageBox.height, 0, 1-dialog.cropH)
                            }
                        }
                        Repeater {
                            model: 4
                            delegate: Rectangle {
                                required property int index
                                objectName: "portraitCorner" + index
                                x: (index === 0 || index === 2 ? 0 : selection.width) - 7
                                y: (index < 2 ? 0 : selection.height) - 7
                                width: 14; height: 14; color: "white"; border.color: "#333333"; radius: 2
                                MouseArea {
                                    anchors.fill: parent; anchors.margins: -5
                                    cursorShape: index === 0 || index === 3 ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor
                                    property var initial
                                    onPressed: { initial = [dialog.cropX, dialog.cropY, dialog.cropW, dialog.cropH] }
                                    onPositionChanged: mouse => {
                                        if (!pressed) return
                                        let p = mapToItem(imageBox, mouse.x, mouse.y)
                                        dialog.resizeCrop(index, p.x/imageBox.width, p.y/imageBox.height, initial)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            ColumnLayout {
                Layout.preferredWidth: 160
                Label { text: "Предпросмотр"; color: dialog.colors.muted }
                Item {
                    id: preview
                    Layout.preferredWidth: 160
                    Layout.preferredHeight: Math.min(240, 160 * dialog.cropH * backend.captureInfo.height / Math.max(1, dialog.cropW * backend.captureInfo.width))
                    clip: true
                    Image {
                        source: backend.captureInfo.url; cache: false
                        x: -dialog.cropX * width; y: -dialog.cropY * height
                        width: preview.width / Math.max(.001, dialog.cropW)
                        height: width * backend.captureInfo.height / Math.max(1, backend.captureInfo.width)
                    }
                }
                Label { text: Math.round(dialog.cropW * backend.captureInfo.width) + " × " + Math.round(dialog.cropH * backend.captureInfo.height); color: dialog.colors.muted }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Персонаж" }
            ComboBox { id: recipient; objectName: "portraitRecipient"; Layout.fillWidth: true; model: ["Создать нового…"].concat(backend.characterCards.map(c => c.name)) }
            DialogTextField { id: newName; objectName: "portraitNewName"; visible: recipient.currentIndex === 0; placeholderText: "Имя нового персонажа"; Layout.preferredWidth: 220 }
        }
        RowLayout {
            Layout.fillWidth: true
            CheckBox { id: primary; text: "Сделать основным портретом" }
            Item { Layout.fillWidth: true }
            Button { text: "Отмена"; onClicked: dialog.close() }
            Button {
                objectName: "savePortraitCrop"
                text: "Сохранить портрет"; highlighted: true
                enabled: dialog.cropW * backend.captureInfo.width >= 8 && dialog.cropH * backend.captureInfo.height >= 8 && (recipient.currentIndex > 0 || newName.text.trim().length > 0)
                onClicked: {
                    let cardId = recipient.currentIndex > 0 ? backend.characterCards[recipient.currentIndex-1].id : ""
                    if (backend.savePortrait(cardId, newName.text, dialog.cropX, dialog.cropY, dialog.cropW, dialog.cropH, primary.checked)) dialog.close()
                }
            }
        }
    }
}
