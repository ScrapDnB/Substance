import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    required property var colors
    required property string section
    required property string title
    required property string description
    required property var tools
    property string activeKey: ""
    property var activeTool: null
    readonly property bool hasTool: activeTool !== null && activeTool.embeddedActive && activeTool.embeddedHost === toolHost
    readonly property real uiScale: backend.appearance.general.uiScale / 100
    signal toolRequested(string key)

    function embed(tool, key) {
        if (activeTool && activeTool !== tool && activeTool.embeddedHost === toolHost) activeTool.detachEmbedding()
        // A shared tool can move between Preparation and Post without copying
        // controls, previews or pending edits into a second instance.
        if (tool.visible) tool.close()
        tool.embeddedHost = toolHost
        activeTool = tool
        activeKey = key
        viewport.contentItem.contentX = 0
        viewport.contentItem.contentY = 0
    }
    RowLayout {
        anchors.fill: parent
        spacing: 0
        Pane {
            objectName: page.section + "ToolColumn"
            Layout.preferredWidth: Math.round(244 * page.uiScale)
            Layout.fillHeight: true
            padding: 10
            background: Rectangle { color: page.colors.panel }
            ColumnLayout {
                anchors.fill: parent
                spacing: 8
                Label { text: page.title; font.weight: Font.DemiBold; color: page.colors.text; Layout.fillWidth: true; wrapMode: Text.Wrap }
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: availableWidth
                    clip: true
                    ColumnLayout {
                        width: parent.width
                        spacing: 3
                        Repeater {
                            model: page.tools
                            delegate: ItemDelegate {
                                id: entry
                                required property var modelData
                                objectName: page.section + "Tool_" + modelData.key
                                Layout.fillWidth: true
                                highlighted: page.hasTool && page.activeKey === modelData.key
                                enabled: !backend.busy && (!modelData.document || backend.count > 0)
                                onClicked: page.toolRequested(modelData.key)
                                Accessible.name: modelData.title
                                contentItem: ColumnLayout {
                                    spacing: 3
                                    Label { text: entry.modelData.title; font.weight: entry.highlighted ? Font.DemiBold : Font.Normal; color: entry.highlighted ? page.colors.selectedText : page.colors.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    Label { visible: !!entry.modelData.detail; text: entry.modelData.detail || ""; font.pixelSize: Math.round(11 * page.uiScale); color: entry.highlighted ? Qt.alpha(page.colors.selectedText, 0.85) : page.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                        }
                    }
                }
                Button { text: "К таймингу"; Layout.fillWidth: true; onClicked: backend.setMode("timing") }
                Button { text: "К переводу"; Layout.fillWidth: true; onClicked: backend.setMode("translation") }
            }
        }
        Rectangle { Layout.fillHeight: true; implicitWidth: 1; color: page.colors.separator }
        ScrollView {
            id: viewport
            objectName: page.section + "ToolViewport"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: page.hasTool ? Math.max(availableWidth, page.activeTool.minimumWidth) : availableWidth
            contentHeight: page.hasTool ? Math.max(availableHeight, page.activeTool.minimumHeight) : availableHeight
            Item {
                id: toolHost
                objectName: page.section + "ToolHost"
                width: viewport.contentWidth
                height: viewport.contentHeight
            }
            ColumnLayout {
                visible: !page.hasTool
                x: 28
                y: 28
                width: Math.max(0, viewport.availableWidth - 56)
                spacing: 16
                Label { text: page.title; font.pixelSize: Math.round(28 * page.uiScale); font.weight: Font.DemiBold; color: page.colors.text; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Label { text: page.description; color: page.colors.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Label { text: "Выберите инструмент в колонке слева."; color: page.colors.text; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Rectangle { color: page.colors.separator; Layout.fillWidth: true; implicitHeight: 1 }
                Label { text: backend.title + " · Реплик: " + backend.count; color: page.colors.text; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText }
                Label { text: backend.media.hasMedia ? "Медиа: " + backend.media.name : "Видео или аудио ещё не подключено"; color: page.colors.muted; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText }
            }
        }
    }
}
