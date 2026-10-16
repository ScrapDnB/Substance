import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    available: backend.onlineSession.active
    title: "Сравнение версий серии"
    preferredWidth: 1120
    preferredHeight: 720
    readonly property var session: backend.onlineSession.conflictSession
    property var view: ({})
    property var choices: ({})
    property bool refreshing: false
    property bool onlyConflicts: true
    function loadComparison() { view = session.comparison; choices = ({}); onlyConflicts = (view.conflicts || []).length > 0; refreshing = false }
    onOpened: { loadComparison(); refreshing = true; session.refresh() }
    Connections {
        target: dialog.session
        function onChanged() { if (dialog.refreshing && !backend.onlineSession.busy) dialog.loadComparison() }
        function onResolved() { dialog.close() }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: "База: ревизия " + (dialog.view.base_revision || "—") + "   ·   Сервер: ревизия " + (dialog.view.server_revision || "—"); font.bold: true }
        Label { text: "Независимые изменения объединяются. Выберите значение каждого спорного поля. Согласование сохраняет новый черновик на компьютере; его отправка отдельно проверит права и серверную ревизию."; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Label { text: dialog.session.status; visible: text.length > 0; color: dialog.colors.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
        RowLayout {
            Button { text: "Обновить сравнение"; enabled: !backend.onlineSession.busy; onClicked: { dialog.refreshing = true; dialog.session.refresh() } }
            Button { objectName: "comparisonRetry"; text: "Повторить прежнюю отправку"; visible: !dialog.view.can_resolve; enabled: !backend.onlineSession.busy; onClicked: dialog.session.retry() }
            CheckBox { text: "Только конфликтующие поля"; checked: dialog.onlyConflicts; onClicked: dialog.onlyConflicts = checked }
        }
        ScrollView {
            id: scroll
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                width: scroll.availableWidth
                Repeater {
                    model: dialog.onlyConflicts ? (dialog.view.conflicts || []) : (dialog.view.changes || [])
                    delegate: ColumnLayout {
                        id: row
                        required property var modelData
                        readonly property bool conflict: (dialog.view.conflicts || []).some(r => r.key === row.modelData.key)
                        Layout.fillWidth: true
                        spacing: 8
                        Label { text: row.modelData.title + (row.conflict ? " · конфликт" : row.modelData.mineChanged && row.modelData.serverChanged ? " · совпадающие правки" : row.modelData.mineChanged ? " · мои правки" : " · серверные правки"); font.bold: true; color: row.conflict ? dialog.colors.warning : dialog.colors.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        RowLayout {
                            Layout.fillWidth: true
                            Repeater {
                                model: [{label:"Базовая версия", value:row.modelData.base}, {label:"Мой черновик", value:row.modelData.mine}, {label:"Серверная версия", value:row.modelData.server}]
                                delegate: ColumnLayout {
                                    id: version
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 300
                                    Label { text: version.modelData.label; color: dialog.colors.muted }
                                    ScrollView {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 130
                                        DialogTextArea {
                                            text: version.modelData.value
                                            textFormat: TextEdit.PlainText
                                            wrapMode: TextEdit.Wrap
                                            selectByMouse: true
                                            readOnly: true
                                        }
                                    }
                                }
                            }
                        }
                        ComboBox {
                            visible: row.conflict
                            objectName: row.conflict ? "comparisonChoice" : "comparisonNonConflict"
                            model: ["Выберите значение", "Оставить моё", "Взять серверное"]
                            currentIndex: dialog.choices[row.modelData.key] === "mine" ? 1 : dialog.choices[row.modelData.key] === "server" ? 2 : 0
                            onActivated: { let next = Object.assign({}, dialog.choices); next[row.modelData.key] = currentIndex === 1 ? "mine" : currentIndex === 2 ? "server" : ""; dialog.choices = next }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: dialog.colors.border }
                    }
                }
                Label { visible: !(dialog.onlyConflicts ? (dialog.view.conflicts || []) : (dialog.view.changes || [])).length; text: dialog.view.error ? "Для этой структуры доступен выбор целой версии." : "Спорных полей нет. Независимые правки можно согласовать."; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }
        }
        Label { text: "Перед согласованием прежний черновик сохраняется отдельной копией. Undo согласованного текста отменяет только внесённые в него мои правки."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            Button { text: "Закрыть"; onClicked: dialog.close() }
            Button { text: "Взять сервер целиком"; enabled: dialog.session.canResolve; onClicked: dialog.session.resolve(dialog.view.token, {}, "server") }
            Button { text: "Оставить мой целиком"; enabled: dialog.session.canResolve; onClicked: dialog.session.resolve(dialog.view.token, {}, "mine") }
            Button { objectName: "comparisonResolve"; text: "Согласовать выбранное"; highlighted: true; enabled: dialog.session.canResolve && !dialog.view.error && (dialog.view.conflicts || []).every(r => dialog.choices[r.key] === "mine" || dialog.choices[r.key] === "server"); onClicked: dialog.session.resolve(dialog.view.token, dialog.choices, "merge") }
        }
    }
}
