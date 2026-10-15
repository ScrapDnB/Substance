import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: dialog
    title: "Настройки Substance"
    preferredWidth: 760
    preferredHeight: 620
    modal: false
    standardButtons: Dialog.Close
    function reloadDocument() {
        fps.text = backend.fps.toString();
        encoding.currentIndex = Math.max(0, ["utf-8", "cp1251", "utf-16"].indexOf(backend.encoding));
    }
    onOpened: reloadDocument()
    Connections {
        target: backend
        function onDocumentReplaced() { if (dialog.visible) dialog.reloadDocument() }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 20
        DialogTabs {
            id: tabs
            objectName: "settingsTabs"
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 440
            labels: ["Интерфейс", "Документ", "Горячие клавиши"]
        }
        StackLayout {
            currentIndex: tabs.currentIndex
            Layout.fillWidth: true
            Layout.fillHeight: true
            ScrollView {
                id: interfaceScroll
                clip: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: interfaceScroll.availableWidth
                    spacing: 18
                    DialogSection {
                        title: "Внешний вид"
                        Layout.fillWidth: true
                        ColumnLayout {
                            anchors.fill: parent
                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    text: "Тема"
                                    Layout.preferredWidth: 160
                                }
                                ComboBox {
                                    Layout.fillWidth: true
                                    model: ["Системная", "Светлая", "Тёмная"]
                                    currentIndex: ["system", "light", "dark"].indexOf(backend.theme)
                                    onActivated: backend.preference("theme", ["system", "light", "dark"][currentIndex])
                                }
                            }
                            CheckBox {
                                text: "Плавные переходы"
                                checked: backend.motion
                                onClicked: backend.preference("motion", checked ? "true" : "false")
                            }
                            Label {
                                text: "Ввод текста и тайминг применяются сразу. Переходы не задерживают действия."
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                                color: dialog.colors.muted
                                font.pixelSize: 12
                            }
                        }
                    }
                    DialogSection {
                        title: "Проверка субтитров"
                        Layout.fillWidth: true
                        ColumnLayout {
                            anchors.fill: parent
                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    text: "Скорость чтения, зн/с"
                                    Layout.preferredWidth: 160
                                }
                                DialogSpinBox {
                                    objectName: "readingSpeedLimit"
                                    from: 1
                                    to: 100
                                    value: backend.cpsLimit
                                    editable: true
                                    onValueModified: backend.preference("cpsLimit", value.toString())
                                }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Label {
                                    text: "Знаков в строке"
                                    Layout.preferredWidth: 160
                                }
                                DialogSpinBox {
                                    objectName: "lineLengthLimit"
                                    from: 10
                                    to: 200
                                    value: backend.lineLimit
                                    editable: true
                                    onValueModified: backend.preference("lineLimit", value.toString())
                                }
                            }
                        }
                    }
                    DialogSection {
                        title: "Импорт"
                        Layout.fillWidth: true
                        RowLayout {
                            anchors.fill: parent
                            Label {
                                text: "Кодировка импорта"
                                Layout.preferredWidth: 160
                            }
                            ComboBox {
                                Layout.fillWidth: true
                                model: ["Авто · UTF-8 / Windows-1251", "UTF-8", "Windows-1251", "Shift JIS", "Windows-1252"]
                                currentIndex: Math.max(0, ["auto", "utf-8", "cp1251", "shift_jis", "cp1252"].indexOf(backend.importEncoding))
                                onActivated: backend.preference("importEncoding", ["auto", "utf-8", "cp1251", "shift_jis", "cp1252"][currentIndex])
                            }
                        }
                    }
                    Label {
                        text: "Изменения интерфейса сохраняются сразу."
                        color: dialog.colors.muted
                        Layout.fillWidth: true
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
        }
    }
}
