import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: pane
    required property var colors
    readonly property var assistance: backend.languageAssistance
    readonly property var result: assistance.result
    readonly property bool localOnly: assistance.config.localOnly
    objectName: "languagePane"
    padding: Math.round(12 * backend.appearance.general.uiScale / 100)
    background: Rectangle { color: pane.colors.panel }
    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            Label { text: pane.localOnly ? "Словарь" : "Словарь и перевод"; font.bold: true; color: pane.colors.text; Layout.fillWidth: true; wrapMode: Text.Wrap }
            Button { objectName: "languageSettingsButton"; text: "Настройки…"; onClicked: pane.assistance.openSettings() }
        }
        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: scroll.availableWidth
                spacing: 10
                Label {
                    visible: !pane.assistance.query
                    text: pane.localOnly ? "Выделите слово в оригинале или переводе." : "Выделите слово или фразу в оригинале или переводе."
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.muted
                }
                Label {
                    objectName: "languageQuery"
                    visible: !!pane.assistance.query
                    text: pane.assistance.query
                    textFormat: Text.PlainText
                    font.bold: true; color: pane.colors.text
                    Layout.fillWidth: true; wrapMode: Text.Wrap
                }
                Label {
                    objectName: "languageProvider"
                    text: (pane.result.detected ? pane.result.detected + " → " : "") + pane.assistance.config.target + " · " + pane.assistance.providerTitle
                    visible: !pane.localOnly && !!pane.assistance.query
                    color: pane.colors.muted; font.pixelSize: 11
                    Layout.fillWidth: true; wrapMode: Text.Wrap
                }
                BusyIndicator { running: pane.assistance.busy; visible: running; implicitWidth: 24; implicitHeight: 24 }
                Label {
                    objectName: "languageTranslation"
                    visible: !pane.localOnly && !!pane.result.translation
                    text: pane.result.translation || ""
                    textFormat: Text.PlainText
                    color: pane.colors.text; Layout.fillWidth: true; wrapMode: Text.Wrap
                }
                Button {
                    objectName: "copyLanguageTranslation"
                    text: "Копировать перевод"; visible: !pane.localOnly && !!pane.result.translation
                    onClicked: pane.assistance.copyTranslation()
                }
                Label {
                    visible: !!pane.result.error
                    text: pane.result.error || ""
                    textFormat: Text.PlainText
                    color: pane.colors.warning; Layout.fillWidth: true; wrapMode: Text.Wrap
                }
                Button {
                    objectName: "languageLookupButton"
                    text: pane.result.error ? "Повторить" : pane.localOnly ? "Найти" : "Найти / перевести"
                    visible: !!pane.assistance.query
                    enabled: !pane.assistance.busy
                    onClicked: pane.assistance.lookup()
                }
                Label {
                    objectName: "languageLocalPhraseHint"
                    visible: pane.localOnly && pane.result.kind === "phrase"
                    text: "Включён режим локальных словарей. Для поиска значений выделите одно слово."
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.muted
                }
                Label {
                    visible: pane.result.kind === "word" && (!pane.result.entries || !pane.result.entries.length)
                    text: pane.result.dictionaryMissing ? "Для значений и примеров установите словарь в настройках." : "В установленных словарях слово не найдено. Можно подключить другую редакцию Викисловаря."
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.muted
                }
                Repeater {
                    model: pane.result.entries || []
                    delegate: ColumnLayout {
                        id: entry
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 6
                        Rectangle { Layout.fillWidth: true; height: 1; color: pane.colors.separator }
                        Label {
                            text: entry.modelData.word + " · " + entry.modelData.pos + " · " + entry.modelData.languageName
                            textFormat: Text.PlainText
                            font.bold: true; color: pane.colors.text
                            Layout.fillWidth: true; wrapMode: Text.Wrap
                        }
                        Repeater {
                            model: entry.modelData.senses.slice(0, 6)
                            delegate: ColumnLayout {
                                id: sense
                                required property var modelData
                                required property int index
                                Layout.fillWidth: true
                                spacing: 4
                                Label {
                                    text: (sense.index + 1) + ". " + (sense.modelData.translatedDefinition || sense.modelData.definition)
                                    textFormat: Text.PlainText
                                    color: pane.colors.text; Layout.fillWidth: true; wrapMode: Text.Wrap
                                }
                                Label {
                                    visible: !!sense.modelData.translatedDefinition
                                    text: "Машинный перевод пояснения · оригинал: " + sense.modelData.definition
                                    textFormat: Text.PlainText
                                    color: pane.colors.muted; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap
                                }
                                Label {
                                    readonly property string translations: sense.modelData.translations.filter(t => t.language === pane.assistance.config.target).map(t => t.text).join(" · ")
                                    visible: !!translations
                                    text: translations; textFormat: Text.PlainText
                                    color: pane.colors.accent; Layout.fillWidth: true; wrapMode: Text.Wrap
                                }
                                Repeater {
                                    model: sense.modelData.examples
                                    Label {
                                        required property string modelData
                                        text: "“" + modelData + "”"; textFormat: Text.PlainText
                                        color: pane.colors.muted; font.italic: true
                                        Layout.fillWidth: true; wrapMode: Text.Wrap
                                    }
                                }
                            }
                        }
                        Label {
                            text: '<a href="' + entry.modelData.url + '">Викисловарь</a> · Kaikki · CC BY-SA / GFDL'
                            textFormat: Text.RichText
                            onLinkActivated: link => Qt.openUrlExternally(link)
                            color: pane.colors.muted; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap
                        }
                    }
                }
            }
        }
    }
}
