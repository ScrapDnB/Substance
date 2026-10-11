import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    required property var colors
    title: "Настройки Substance"
    width: 690
    height: 570
    modal: true
    standardButtons: Dialog.Close
    anchors.centerIn: Overlay.overlay
    ColumnLayout {
        anchors.fill: parent
        TabBar {
            id: tabs
            Layout.fillWidth: true
            TabButton { text: "Интерфейс" }
            TabButton { text: "Документ" }
            TabButton { text: "Горячие клавиши" }
        }
        StackLayout {
            currentIndex: tabs.currentIndex
            Layout.fillWidth: true
            Layout.fillHeight: true
            ColumnLayout {
                spacing: 14
                RowLayout {
                    Label { text: "Тема"; Layout.preferredWidth: 160 }
                    ComboBox { model: ["Системная", "Светлая", "Тёмная"]; currentIndex: ["system", "light", "dark"].indexOf(backend.theme); onActivated: backend.preference("theme", ["system", "light", "dark"][currentIndex]) }
                }
                CheckBox { text: "Плавные переходы"; checked: backend.motion; onClicked: backend.preference("motion", checked ? "true" : "false") }
                Label { text: "Ввод текста и тайминг применяются сразу. Переходы не задерживают действия."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted; font.pixelSize: 12 }
                RowLayout {
                    Label { text: "Скорость чтения, зн/с"; Layout.preferredWidth: 160 }
                    SpinBox { from: 1; to: 100; value: backend.cpsLimit; editable: true; onValueModified: backend.preference("cpsLimit", value.toString()) }
                }
                RowLayout {
                    Label { text: "Знаков в строке"; Layout.preferredWidth: 160 }
                    SpinBox { from: 10; to: 200; value: backend.lineLimit; editable: true; onValueModified: backend.preference("lineLimit", value.toString()) }
                }
                RowLayout {
                    Label { text: "Кодировка импорта"; Layout.preferredWidth: 160 }
                    ComboBox { model: ["Авто · UTF-8 / Windows-1251", "UTF-8", "Windows-1251", "Shift JIS", "Windows-1252"]; onActivated: backend.preference("importEncoding", ["auto", "utf-8", "cp1251", "shift_jis", "cp1252"][currentIndex]) }
                }
                Item { Layout.fillHeight: true }
            }
            ColumnLayout {
                spacing: 12
                RowLayout {
                    Label { text: "Частота кадров"; Layout.preferredWidth: 160 }
                    TextField { id: fps; text: backend.fps.toString(); validator: DoubleValidator { bottom: 1; top: 120; locale: "en_US" } }
                }
                RowLayout {
                    Label { text: "Кодировка ASS"; Layout.preferredWidth: 160 }
                    ComboBox { id: encoding; model: ["UTF-8", "Windows-1251", "UTF-16"]; currentIndex: Math.max(0, ["utf-8", "cp1251", "utf-16"].indexOf(backend.encoding)) }
                }
                Button { text: "Применить к документу"; onClicked: backend.documentSettings(Number(fps.text), ["utf-8", "cp1251", "utf-16"][encoding.currentIndex]) }
                Label { text: "Точное время хранится в миллисекундах. ASS экспортируется с округлением до сотых секунды. Исходные стили и теги сохраняются."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted }
                Label { text: "Файл .ass.substance рядом с ASS сохраняет оригинал, перевод, статусы и связи исходных строк. Для переноса всего проекта можно сохранить .substance."; wrapMode: Text.Wrap; Layout.fillWidth: true; color: dialog.colors.muted }
                Item { Layout.fillHeight: true }
            }
            ColumnLayout {
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    ScrollBar.vertical: ScrollBar { }
                    model: [
                        {key:"new", name:"Новый документ"}, {key:"open", name:"Открыть"}, {key:"save", name:"Сохранить"}, {key:"saveAs", name:"Сохранить как"}, {key:"export", name:"Экспорт"},
                        {key:"undo", name:"Отмена"}, {key:"redo", name:"Повтор"}, {key:"find", name:"Поиск"}, {key:"replace", name:"Замена"}, {key:"apply", name:"Применить / готово и дальше"},
                        {key:"newLine", name:"Новая реплика"}, {key:"duplicate", name:"Дублировать"}, {key:"split", name:"Разделить"}, {key:"merge", name:"Объединить"},
                        {key:"previous", name:"Предыдущая реплика"}, {key:"next", name:"Следующая реплика"}, {key:"play", name:"Воспроизведение"}, {key:"playLine", name:"Воспроизвести реплику"},
                        {key:"setStart", name:"Начало по текущему кадру"}, {key:"setEnd", name:"Конец по текущему кадру"}, {key:"frameBack", name:"Предыдущий кадр"}, {key:"frameForward", name:"Следующий кадр"},
                        {key:"shift", name:"Сдвиг времени"}, {key:"copyLines", name:"Копировать реплики"}, {key:"pasteLines", name:"Вставить реплики"}, {key:"deleteLines", name:"Удалить реплики"}
                    ]
                    delegate: RowLayout {
                        required property var modelData
                        width: ListView.view.width
                        height: 36
                        Label { text: modelData.name; Layout.fillWidth: true }
                        Label { text: { let revision = backend.shortcuts; return backend.shortcutLabel(modelData.key) } color: dialog.colors.muted; Layout.preferredWidth: 125 }
                        Button { text: "Изменить…"; onClicked: backend.editShortcutDialog(modelData.key) }
                    }
                }
                Button { text: "Вернуть стандартные сочетания"; onClicked: backend.resetShortcuts() }
            }
        }
    }
}
