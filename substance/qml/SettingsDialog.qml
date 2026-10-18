import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    title: "Настройки Substance"
    preferredWidth: 1060
    preferredHeight: 780
    minimumWidth: Math.min(880, Screen.desktopAvailableWidth - 48)
    minimumHeight: Math.min(560, Screen.desktopAvailableHeight - 80)
    modal: false
    standardButtons: Dialog.Close
    readonly property bool dark: colors.dark
    readonly property var pages: [
        {title: "Оформление", subtitle: "Цвета и системная тема", icon: "◐", keywords: "тема светлая тёмная цвет акцент волна выделение фон"},
        {title: "Текст и размеры", subtitle: "Шрифты, строки и масштаб", icon: "Aa", keywords: "шрифт размер масштаб текст оригинал перевод таблица перенос высота плотность таймкод ноль цифры"},
        {title: "Тайминг", subtitle: "Расположение панелей", icon: "◷", keywords: "тайминг раскладка расположение видео аудио ширина высота"},
        {title: "Перевод", subtitle: "Расположение панелей", icon: "文", keywords: "перевод раскладка расположение видео аудио контекст оригинал редактор"},
        {title: "Проверки и импорт", subtitle: "Читаемость и кодировки", icon: "✓", keywords: "проверки чтение скорость строка длина импорт кодировка"},
        {title: "Документ", subtitle: "Параметры текущего файла", icon: "▤", keywords: "документ fps кадры ASS кодировка проект"},
        {title: "Горячие клавиши", subtitle: "Команды редактора", icon: "⌘", keywords: "горячие клавиши сочетания команды"},
        {title: "Словарь и перевод", subtitle: "Языки, сервисы и инструкции", icon: "文", keywords: "словарь перевод языки azure deepl libretranslate ключ api инструкция подключение"}
    ]
    function reloadDocument() {
        fps.text = backend.fps.toString()
        encoding.currentIndex = Math.max(0, ["utf-8", "cp1251", "utf-16"].indexOf(backend.encoding))
    }
    function openLanguageSettings() { navigation.page = 7; open() }
    onOpened: reloadDocument()
    Connections {
        target: backend
        function onDocumentReplaced() { if (dialog.visible) dialog.reloadDocument() }
    }
    RowLayout {
        anchors.fill: parent
        spacing: 24
        ColumnLayout {
            Layout.preferredWidth: 206
            Layout.fillHeight: true
            spacing: 12
            Label { text: "SUBSTANCE"; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2; color: dialog.colors.muted; Layout.leftMargin: 10 }
            DialogTextField {
                id: settingsSearch
                objectName: "settingsSearch"
                Layout.fillWidth: true
                placeholderText: "Найти настройку"
                Accessible.name: "Поиск по настройкам"
            }
            ListView {
                id: navigation
                objectName: "settingsNavigation"
                property int page: 0
                currentIndex: page
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 4
                model: dialog.pages
                keyNavigationEnabled: false
                Keys.onUpPressed: step(-1)
                Keys.onDownPressed: step(1)
                function matches(item) {
                    let query = settingsSearch.text.trim().toLocaleLowerCase()
                    return !query || (item.title + " " + item.keywords).toLocaleLowerCase().indexOf(query) >= 0
                }
                function step(delta) {
                    for (let i = page + delta; i >= 0 && i < dialog.pages.length; i += delta) {
                        if (matches(dialog.pages[i])) { page = i; return }
                    }
                }
                delegate: ItemDelegate {
                    required property var modelData
                    required property int index
                    objectName: "settingsPage" + index
                    width: navigation.width
                    height: visible ? 58 : 0
                    visible: navigation.matches(modelData)
                    highlighted: navigation.page === index
                    background: Rectangle {
                        radius: 9
                        color: parent.highlighted ? Qt.alpha(dialog.colors.accent, dialog.dark ? 0.25 : 0.12) : parent.hovered ? Qt.alpha(dialog.colors.text, 0.05) : "transparent"
                    }
                    contentItem: RowLayout {
                        spacing: 10
                        Rectangle {
                            implicitWidth: 29; implicitHeight: 29; radius: 8
                            color: Qt.alpha(dialog.colors.accent, 0.13)
                            Label { anchors.centerIn: parent; text: modelData.icon; color: dialog.colors.accent; font.pixelSize: 14; font.bold: true }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 3
                            Label { text: modelData.title; color: dialog.colors.text; font.weight: navigation.page === index ? Font.DemiBold : Font.Normal; font.pixelSize: 13 }
                            Label { text: modelData.subtitle; color: dialog.colors.muted; font.pixelSize: 10; elide: Text.ElideRight; Layout.fillWidth: true }
                        }
                    }
                    onClicked: { navigation.page = index; navigation.forceActiveFocus() }
                    Accessible.name: modelData.title
                    Accessible.role: Accessible.PageTab
                    Accessible.selected: highlighted
                }
                Label {
                    anchors.centerIn: parent
                    width: parent.width
                    text: "Ничего не найдено"
                    color: dialog.colors.muted
                    horizontalAlignment: Text.AlignHCenter
                    visible: dialog.pages.every(item => !navigation.matches(item))
                }
            }
            Label { text: "Интерфейс сохраняется\nна этом компьютере"; color: dialog.colors.muted; font.pixelSize: 11; lineHeight: 1.3; Layout.leftMargin: 10 }
        }
        Rectangle { Layout.fillHeight: true; width: 1; color: dialog.colors.border; opacity: 0.5 }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 14
            Label { text: dialog.pages[navigation.page].title; font.pixelSize: 25; font.weight: Font.DemiBold; color: dialog.colors.text }
            Label {
                text: ["Подберите палитру для комфортной работы.", "Настройте читаемость и плотность рабочего окна.", "Больше места для видео, звука и точных границ реплик.", "Расположите оригинал, перевод и словарь по своему вкусу.", "Общие значения для новых документов и параметры импорта.", "Изменения этого раздела относятся к открытому документу.", "Сочетания работают и в русской, и в английской раскладке.", "Настройте помощь при выделении текста и подключите нужный сервис."][navigation.page]
                color: dialog.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 12
            }
            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: navigation.page
                ScrollView {
                    id: appearanceScroll
                    clip: true; contentWidth: availableWidth
                    ColumnLayout {
                        width: appearanceScroll.availableWidth; spacing: 18
                        DialogSection {
                            title: "Внешний вид"; Layout.fillWidth: true
                            ColumnLayout {
                                anchors.fill: parent; spacing: 12
                                RowLayout {
                                    Label { text: "Тема программы"; Layout.fillWidth: true }
                                    ComboBox { Layout.preferredWidth: 210; model: ["Системная", "Светлая", "Тёмная"]; currentIndex: ["system", "light", "dark"].indexOf(backend.theme); onActivated: backend.preference("theme", ["system", "light", "dark"][currentIndex]) }
                                }
                                CheckBox { text: "Плавные переходы"; checked: backend.motion; onClicked: backend.preference("motion", checked ? "true" : "false") }
                            }
                        }
                        DialogSection {
                            title: "Цветовые акценты"; Layout.fillWidth: true
                            ColumnLayout {
                                anchors.fill: parent; spacing: 12
                                Flow {
                                    Layout.fillWidth: true; Layout.preferredHeight: childrenRect.height; spacing: 6
                                    Repeater {
                                        model: [{name: "system", title: "Система"}, {name: "blue", title: "Синий"}, {name: "mint", title: "Мята"}, {name: "amber", title: "Янтарь"}, {name: "violet", title: "Сирень"}]
                                        Button { required property var modelData; text: modelData.title; onClicked: backend.appearance.preset(modelData.name) }
                                    }
                                }
                                SettingsColor { title: "Акцент и активные элементы"; setting: "accentColor"; fallback: dialog.colors.accent; Layout.fillWidth: true }
                                SettingsColor { title: "Выделение реплик"; setting: "selectionColor"; fallback: dialog.colors.selection; Layout.fillWidth: true }
                                SettingsColor { title: "Аудиоволна"; setting: "waveColor"; fallback: dialog.colors.text; Layout.fillWidth: true }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 10
                                    Rectangle {
                                        Layout.fillWidth: true; implicitHeight: 36; radius: 7; color: dialog.colors.selection
                                        Label { anchors.centerIn: parent; text: "Выбранная реплика"; color: dialog.colors.selectedText; font.pixelSize: 12 }
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true; implicitHeight: 36; radius: 7; color: dialog.colors.surface
                                        Label { anchors.centerIn: parent; text: "∿∿∿∿∿∿∿∿∿"; color: dialog.colors.wave; font.pixelSize: 24 }
                                    }
                                }
                            }
                        }
                        DialogSection {
                            title: "Поля оригинала и перевода · " + (dialog.dark ? "тёмная тема" : "светлая тема"); Layout.fillWidth: true
                            ColumnLayout {
                                anchors.fill: parent; spacing: 12
                                SettingsColor { title: "Фон текстовых полей"; group: dialog.dark ? "darkColors" : "lightColors"; setting: "editorBackground"; fallback: dialog.colors.surface; Layout.fillWidth: true }
                                SettingsColor { title: "Цвет текста"; group: dialog.dark ? "darkColors" : "lightColors"; setting: "editorText"; fallback: dialog.colors.text; Layout.fillWidth: true }
                                Label { text: "У светлой и тёмной темы свои цвета полей. «Сбросить» возвращает системный цвет."; color: dialog.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 11 }
                                Rectangle {
                                    Layout.fillWidth: true; implicitHeight: 66; radius: 8; color: dialog.colors.editorBackground
                                    Label { anchors.fill: parent; anchors.margins: 12; text: "Текст хорошо читается на выбранном фоне.\nОригинал и перевод — в вашем стиле."; font.pixelSize: 14; color: dialog.colors.editorText; wrapMode: Text.Wrap }
                                }
                            }
                        }
                    }
                }
                ScrollView {
                    id: textScroll
                    clip: true; contentWidth: availableWidth
                    ColumnLayout {
                        width: textScroll.availableWidth; spacing: 18
                        DialogSection {
                            title: "Размеры и шрифты"; Layout.fillWidth: true
                            ColumnLayout {
                                anchors.fill: parent; spacing: 14
                                SettingsNumber { title: "Масштаб интерфейса"; description: "Подписи и элементы рабочего окна"; setting: "uiScale"; from: 85; to: 125; step: 5; unit: "%"; Layout.fillWidth: true }
                                SettingsNumber { title: "Текст в таблице"; setting: "tableFont"; from: 10; to: 22; Layout.fillWidth: true }
                                SettingsNumber { title: "Текст перевода / реплики"; setting: "editorFont"; from: 12; to: 30; Layout.fillWidth: true }
                                SettingsNumber { title: "Текст оригинала"; setting: "originalFont"; from: 10; to: 26; Layout.fillWidth: true }
                                SettingsChoice { title: "Шрифт текста"; setting: "textFamily"; labels: ["Системный", "Arial", "Georgia", "Моноширинный"]; values: ["", "Arial", "Georgia", backend.isMac ? "Menlo" : "Consolas"]; Layout.fillWidth: true }
                                SettingsChoice {
                                    title: "Шрифт таймкода"
                                    setting: "timecodeFont"
                                    labels: backend.appearance.timecodeOptions.map(option => option.label)
                                    values: backend.appearance.timecodeOptions.map(option => option.value)
                                    fieldWidth: 260
                                    Layout.fillWidth: true
                                }
                                SettingsNumber { title: "Размер таймкода"; setting: "timecodeSize"; from: 10; to: 28; Layout.fillWidth: true }
                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: Math.max(76, timecodeSample.implicitHeight + timecodeCaption.implicitHeight + 29)
                                    radius: 8
                                    color: dialog.colors.surface
                                    border.color: Qt.alpha(dialog.colors.border, 0.5)
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 5
                                        Label {
                                            id: timecodeSample
                                            objectName: "timecodeFontPreview"
                                            text: "00:01:08.000"
                                            font.family: backend.appearance.timecodeFamily
                                            font.bold: backend.appearance.timecodeBold
                                            font.pixelSize: backend.appearance.general.timecodeSize
                                            color: dialog.colors.text
                                        }
                                        Label { id: timecodeCaption; text: "Таблица, начало и конец реплики, плеер и аудиошкала"; color: dialog.colors.muted; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.Wrap }
                                    }
                                }
                            }
                        }
                        DialogSection {
                            title: "Таблица реплик"; Layout.fillWidth: true
                            ColumnLayout {
                                anchors.fill: parent; spacing: 12
                                SettingsNumber { title: "Минимальная высота строки"; setting: "rowHeight"; from: 28; to: 76; Layout.fillWidth: true }
                                CheckBox { text: "Переносить длинные реплики в таблице"; checked: backend.appearance.general.wrapRows; onClicked: backend.appearance.setValue("general", "wrapRows", checked) }
                                CheckBox { text: "Чередовать фон строк"; checked: backend.appearance.general.stripedRows; onClicked: backend.appearance.setValue("general", "stripedRows", checked) }
                                CheckBox { text: "Показывать разделители строк"; checked: backend.appearance.general.rowLines; onClicked: backend.appearance.setValue("general", "rowLines", checked) }
                                SettingsNumber { title: "Ширина боковой панели"; setting: "sidebarWidth"; from: 180; to: 340; Layout.fillWidth: true }
                            }
                        }
                        Rectangle {
                            Layout.fillWidth: true; implicitHeight: sample.implicitHeight + 28; radius: 10
                            color: dialog.colors.surface; border.color: dialog.colors.border
                            Label { id: sample; anchors.fill: parent; anchors.margins: 14; text: "Пример реплики — хорошо, когда текст легко читать."; font.pixelSize: backend.appearance.general.editorFont; font.family: backend.appearance.general.textFamily || dialog.font.family; color: dialog.colors.text; wrapMode: Text.Wrap }
                        }
                        Label { text: "Размеры в логических пикселях: Retina и системное масштабирование учитываются автоматически. Эти параметры не меняют оформление ASS на видео."; color: dialog.colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 11 }
                        Button { text: "Вернуть стандартные размеры"; onClicked: backend.appearance.resetSizes() }
                    }
                }
                LayoutSettingsPane { mode: "timing"; colors: dialog.colors }
                LayoutSettingsPane { mode: "translation"; colors: dialog.colors }
                ScrollView {
                    id: checksScroll
                    clip: true; contentWidth: availableWidth
                    ColumnLayout {
                        width: checksScroll.availableWidth; spacing: 18
                        DialogSection {
                            title: backend.isProject ? "Проверка текущего проекта" : "Проверка субтитров"; Layout.fillWidth: true
                            ColumnLayout {
                                anchors.fill: parent; spacing: 12
                                RowLayout {
                                    Label { text: "Скорость чтения, зн/с"; Layout.fillWidth: true }
                                    DialogSpinBox { objectName: "readingSpeedLimit"; from: 1; to: 100; value: backend.cpsLimit; editable: true; onValueModified: backend.preference("cpsLimit", value.toString()) }
                                }
                                RowLayout {
                                    Label { text: "Знаков в строке"; Layout.fillWidth: true }
                                    DialogSpinBox { objectName: "lineLengthLimit"; from: 10; to: 200; value: backend.lineLimit; editable: true; onValueModified: backend.preference("lineLimit", value.toString()) }
                                }
                                Label { text: backend.isProject ? "Сейчас изменяются проверки открытого .substance проекта. Их можно отменить через «Правка → Отменить»." : "Общие пороги проверок для документов без собственных настроек."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: dialog.colors.muted; font.pixelSize: 11 }
                            }
                        }
                        DialogSection {
                            title: "Импорт"; Layout.fillWidth: true
                            RowLayout {
                                anchors.fill: parent
                                Label { text: "Кодировка импорта"; Layout.fillWidth: true }
                                ComboBox {
                                    Layout.preferredWidth: 270
                                    model: ["Авто · UTF-8 / Windows-1251", "UTF-8", "Windows-1251", "Shift JIS", "Windows-1252"]
                                    currentIndex: Math.max(0, ["auto", "utf-8", "cp1251", "shift_jis", "cp1252"].indexOf(backend.importEncoding))
                                    onActivated: backend.preference("importEncoding", ["auto", "utf-8", "cp1251", "shift_jis", "cp1252"][currentIndex])
                                }
                            }
                        }
                    }
                }
                ScrollView {
                    id: documentScroll
                    clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: documentScroll.availableWidth
                        spacing: 18
                        DialogSection {
                            title: "Параметры документа"
                            Layout.fillWidth: true
                            ColumnLayout {
                                anchors.fill: parent
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label {
                                        text: "Частота кадров"
                                        Layout.preferredWidth: 160
                                    }
                                    DialogTextField {
                                        id: fps
                                        text: backend.fps.toString()
                                        validator: DoubleValidator {
                                            bottom: 1
                                            top: 120
                                            locale: "en_US"
                                        }
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label {
                                        text: "Кодировка ASS"
                                        Layout.preferredWidth: 160
                                    }
                                    ComboBox {
                                        id: encoding
                                        model: ["UTF-8", "Windows-1251", "UTF-16"]
                                        currentIndex: Math.max(0, ["utf-8", "cp1251", "utf-16"].indexOf(backend.encoding))
                                    }
                                }
                                Button {
                                    text: "Применить к документу"
                                    onClicked: backend.documentSettings(Number(fps.text), ["utf-8", "cp1251", "utf-16"][encoding.currentIndex])
                                }
                            }
                        }
                        DialogSection {
                            title: "Проверки проекта"
                            Layout.fillWidth: true
                            ColumnLayout {
                                anchors.fill: parent
                                Label {
                                    visible: !backend.isProject
                                    text: "Сохраните .substance для отдельных настроек проверок."
                                    color: dialog.colors.muted
                                    Layout.fillWidth: true
                                    wrapMode: Text.Wrap
                                }
                                CheckBox {
                                    objectName: "showLengthWarnings"
                                    text: "Превышение длины строки"
                                    enabled: backend.isProject
                                    checked: backend.reviewSettings.lineLength
                                    onClicked: backend.setReviewSetting("lineLength", checked)
                                }
                                CheckBox {
                                    text: "Превышение скорости чтения"
                                    enabled: backend.isProject
                                    checked: backend.reviewSettings.readingSpeed
                                    onClicked: backend.setReviewSetting("readingSpeed", checked)
                                }
                                CheckBox {
                                    text: "Превышение количества строк"
                                    enabled: backend.isProject
                                    checked: backend.reviewSettings.lineCount
                                    onClicked: backend.setReviewSetting("lineCount", checked)
                                }
                            }
                        }
                        Label {
                            text: "Точное время хранится в миллисекундах. ASS экспортируется с округлением до сотых секунды. Исходные стили и теги сохраняются."
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                            color: dialog.colors.muted
                        }
                        Label {
                            text: "Файл .ass.substance рядом с ASS сохраняет оригинал, перевод и связи исходных строк. Для переноса всего проекта можно сохранить .substance."
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                            color: dialog.colors.muted
                        }
                    }
                }
                ColumnLayout {
                    Label {
                        text: "Горячие клавиши"
                        font.bold: true
                        font.pixelSize: 16
                    }
                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        ScrollBar.vertical: ScrollBar {}
                        model: [
                            {
                                key: "new",
                                name: "Новый документ"
                            },
                            {
                                key: "open",
                                name: "Открыть"
                            },
                            {
                                key: "save",
                                name: "Сохранить"
                            },
                            {
                                key: "saveAs",
                                name: "Сохранить как"
                            },
                            {
                                key: "export",
                                name: "Экспорт"
                            },
                            {
                                key: "undo",
                                name: "Отмена"
                            },
                            {
                                key: "redo",
                                name: "Повтор"
                            },
                            {
                                key: "find",
                                name: "Поиск"
                            },
                            {
                                key: "replace",
                                name: "Замена"
                            },
                            {
                                key: "apply",
                                name: "Применить / следующая реплика"
                            },
                            {
                                key: "newLine",
                                name: "Новая реплика"
                            },
                            {
                                key: "duplicate",
                                name: "Дублировать"
                            },
                            {
                                key: "split",
                                name: "Разделить"
                            },
                            {
                                key: "merge",
                                name: "Объединить"
                            },
                            {
                                key: "previous",
                                name: "Предыдущая реплика"
                            },
                            {
                                key: "next",
                                name: "Следующая реплика"
                            },
                            {
                                key: "play",
                                name: "Воспроизведение"
                            },
                            {
                                key: "playLine",
                                name: "Воспроизвести реплику"
                            },
                            {
                                key: "setStart",
                                name: "Начало по текущему кадру"
                            },
                            {
                                key: "setEnd",
                                name: "Конец по текущему кадру"
                            },
                            {
                                key: "frameBack",
                                name: "Предыдущий кадр"
                            },
                            {
                                key: "frameForward",
                                name: "Следующий кадр"
                            },
                            {
                                key: "shift",
                                name: "Сдвиг времени"
                            },
                            {
                                key: "assignCharacter",
                                name: "Назначить персонажа"
                            },
                            { key: "formatBold", name: "Жирный текст" },
                            { key: "formatItalic", name: "Курсив" },
                            { key: "formatUnderline", name: "Подчёркивание" },
                            {
                                key: "copyLines",
                                name: "Копировать реплики"
                            },
                            {
                                key: "pasteLines",
                                name: "Вставить реплики"
                            },
                            {
                                key: "deleteLines",
                                name: "Удалить реплики"
                            }
                        ]
                        delegate: RowLayout {
                            required property var modelData
                            width: ListView.view.width
                            height: 36
                            Label {
                                text: modelData.name
                                Layout.fillWidth: true
                            }
                            Label {
                                text: {
                                    let revision = backend.shortcuts;
                                    return backend.shortcutLabel(modelData.key);
                                }
                                color: dialog.colors.muted
                                Layout.preferredWidth: 125
                            }
                            Button {
                                text: "Изменить…"
                                onClicked: backend.editShortcutDialog(modelData.key)
                            }
                        }
                    }
                    Button {
                        text: "Вернуть стандартные сочетания"
                        onClicked: backend.resetShortcuts()
                    }
                }
                LanguageSettingsPane { colors: dialog.colors }
            }
        }
    }
}
