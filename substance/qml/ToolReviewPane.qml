import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Substance 1.0

RowLayout {
    id: review
    required property var colors
    required property var controller
    property bool timing: false
    property string emptyTitle: "Здесь появится результат"
    property string emptyDescription: "Запустите проверку, выберите предложение слева и сравните результат справа."
    readonly property var preview: controller.preview
    property string viewportKey: ""
    spacing: 14
    ToolCard {
        colors: review.colors
        Layout.preferredWidth: Math.max(260, review.width * .36)
        Layout.fillHeight: true
        ColumnLayout {
            anchors.fill: parent
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Label { text: "2. Выберите изменения"; font.weight: Font.DemiBold; Layout.fillWidth: true }
                Label { text: review.controller.rows.length; color: review.colors.muted }
            }
            Label {
                Layout.fillWidth: true
                text: "Галочками отмечено то, что будет применено."
                color: review.colors.muted
                wrapMode: Text.Wrap
            }
            RowLayout {
                visible: review.controller.rows.length > 0
                Button { text: "Выбрать все"; enabled: !review.controller.busy; onClicked: review.controller.checkAll(true) }
                Button { text: "Снять"; enabled: !review.controller.busy; onClicked: review.controller.checkAll(false) }
            }
            ListView {
                id: resultList
                objectName: review.timing ? "alignmentResultList" : "toolProposalList"
                Layout.fillWidth: true
                Layout.fillHeight: true
                // Attached scroll bars overlay a Flickable; leave their own gutter.
                contentWidth: Math.max(0, width - resultsScrollBar.width - 6)
                flickableDirection: Flickable.VerticalFlick
                clip: true
                spacing: 6
                model: review.controller.rows
                currentIndex: review.controller.previewIndex
                activeFocusOnTab: true
                Keys.onUpPressed: review.controller.previewRow(Math.max(0, currentIndex - 1))
                Keys.onDownPressed: review.controller.previewRow(Math.min(count - 1, currentIndex + 1))
                ScrollBar.vertical: ScrollBar { id: resultsScrollBar; objectName: "toolResultsScrollBar" }
                delegate: Rectangle {
                    id: proposal
                    required property var modelData
                    required property int index
                    width: resultList.contentWidth
                    height: rowContent.implicitHeight + 20
                    radius: 9
                    color: resultList.currentIndex === index ? Qt.alpha(review.colors.accent, .09) : review.colors.panel
                    border.color: resultList.currentIndex === index ? review.colors.accent : review.colors.separator
                    TapHandler { onTapped: { resultList.forceActiveFocus(); review.controller.previewRow(proposal.index) } }
                    RowLayout {
                        id: rowContent
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 6
                        CheckBox {
                            checked: proposal.modelData.checked
                            enabled: proposal.modelData.applicable && !review.controller.busy
                            onClicked: { review.controller.previewRow(proposal.index); review.controller.check(proposal.index, checked) }
                            Accessible.name: "Применить изменение реплики " + proposal.modelData.number
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            spacing: 4
                            Label { text: "Реплика " + proposal.modelData.number; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                            Label { text: proposal.modelData.text; textFormat: Text.PlainText; elide: Text.ElideRight; Layout.fillWidth: true; color: review.colors.muted }
                            Label {
                                Layout.fillWidth: true
                                text: proposal.modelData.review ? "Прослушайте перед применением" : proposal.modelData.applicable ? "Готово к применению" : "Проверьте вручную"
                                color: proposal.modelData.review || !proposal.modelData.applicable ? review.colors.warning : review.colors.muted
                                wrapMode: Text.Wrap
                                font.pixelSize: 11
                            }
                        }
                    }
                }
                Label {
                    anchors.centerIn: parent
                    width: parent.width - 20
                    visible: resultList.count === 0
                    text: review.controller.busy ? "Анализируем реплики…" : review.controller.analysisReady ? "Изменения не требуются" : "Предложения появятся после анализа"
                    color: review.colors.muted
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }
    ToolCard {
        colors: review.colors
        Layout.fillWidth: true
        Layout.fillHeight: true
        ColumnLayout {
            anchors.fill: parent
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                Label { text: "3. Проверьте результат"; font.weight: Font.DemiBold; Layout.fillWidth: true }
                Button { text: "К реплике"; visible: !!review.preview.valid; onClicked: review.controller.locate(review.controller.previewIndex) }
            }
            ScrollView {
                id: previewScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: previewScroll.availableWidth
                    spacing: 12
                    Label {
                        Layout.fillWidth: true
                        text: review.preview.valid ? review.preview.reason : review.controller.analysisReady ? "Проверка завершена" : review.emptyTitle
                        font.pixelSize: review.preview.valid ? 14 : 20
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                        textFormat: Text.PlainText
                    }
                    Label {
                        visible: !review.preview.valid
                        Layout.fillWidth: true
                        text: review.controller.analysisReady ? "По выбранным настройкам исправления не нужны. Можно изменить настройки и повторить анализ." : review.emptyDescription
                        wrapMode: Text.Wrap
                        color: review.colors.muted
                    }
                    Label { text: "Сейчас"; font.weight: Font.DemiBold; visible: !!review.preview.valid }
                    SubtitlePreview { Layout.fillWidth: true; colors: review.colors; cues: review.preview.beforeCues || [] }
                    Waveform {
                        id: beforeWave
                        objectName: "originalTimingPreview"
                        visible: review.timing && !!review.preview.valid
                        Layout.fillWidth: true; Layout.preferredHeight: 64
                        media: backend.media; paletteColors: review.colors
                        start: review.preview.start; end: review.preview.end
                        onSeekRequested: position => backend.media.seek(position)
                        onViewChanged: afterWave.setViewport(viewStart, span)
                    }
                    Label { text: "После применения"; font.weight: Font.DemiBold; visible: !!review.preview.valid }
                    SubtitlePreview { Layout.fillWidth: true; colors: review.colors; cues: review.preview.afterCues || []; proposed: true }
                    Label {
                        Layout.fillWidth: true
                        visible: !!review.preview.valid && !review.preview.applicable
                        text: "Для этого замечания нет однозначного исправления. Перейдите к реплике и проверьте её вручную."
                        wrapMode: Text.Wrap
                        color: review.colors.warning
                    }
                    Waveform {
                        id: afterWave
                        objectName: "proposedTimingPreview"
                        visible: review.timing && !!review.preview.valid
                        Layout.fillWidth: true; Layout.preferredHeight: 64
                        media: backend.media; paletteColors: review.colors
                        start: review.preview.afterStart; end: review.preview.afterEnd
                        onSeekRequested: position => backend.media.seek(position)
                    }
                    Label {
                        visible: review.timing && !!review.preview.valid
                        Layout.fillWidth: true
                        text: "Сдвиг начала: " + review.shift(review.preview.afterStart - review.preview.start) + " · конца: " + review.shift(review.preview.afterEnd - review.preview.end)
                        wrapMode: Text.Wrap
                        color: review.colors.muted
                    }
                }
            }
            Flow {
                Layout.fillWidth: true
                spacing: 6
                visible: !!review.preview.valid
                Button { text: "▶ Сейчас"; enabled: backend.media.hasMedia; onClicked: review.controller.play(review.controller.previewIndex, false) }
                Button { text: "▶ После"; enabled: backend.media.hasMedia && !!review.preview.applicable; onClicked: review.controller.play(review.controller.previewIndex, true) }
                CheckBox {
                    objectName: review.timing ? "alignmentAcceptCurrent" : "toolsAcceptCurrent"
                    text: "Применить"
                    checked: !!review.preview.checked
                    enabled: !!review.preview.applicable && !review.controller.busy
                    onClicked: review.controller.check(review.controller.previewIndex, checked)
                }
            }
        }
    }
    function shift(ms) { return ms === 0 ? "без сдвига" : (ms > 0 ? "+" : "−") + (Math.abs(ms) / 1000).toLocaleString(Qt.locale(), 'f', 2) + " с" }
    Connections {
        target: review.controller
        function onChanged() {
            let key = review.controller.previewIndex + ":" + review.preview.start + ":" + review.preview.end + ":" + review.preview.afterStart + ":" + review.preview.afterEnd
            if (review.timing && review.preview.valid && key !== review.viewportKey) {
                review.viewportKey = key
                beforeWave.setViewport(review.preview.view, review.preview.span)
            }
        }
    }
}
