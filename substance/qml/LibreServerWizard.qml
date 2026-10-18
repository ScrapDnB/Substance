import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

NativeDialog {
    id: wizard
    objectName: "libreServerWizard"
    title: "Сервер LibreTranslate"
    preferredWidth: 650
    preferredHeight: 740
    readonly property var manager: backend.languageAssistance.serverManager
    readonly property var profile: manager.profile
    property string action: "install"
    onClosed: { sshPassword.text = ""; passphrase.text = ""; sudoPassword.text = "" }
    Connections {
        target: wizard.manager
        function onOpenRequested() { wizard.open() }
        function onChanged() { if (wizard.manager.step !== 2) consent.checked = false }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label {
            text: ["1. Подключение", "2. Ключ сервера", "3. Проверка и действие", "4. Выполнение", "5. Результат"][wizard.manager.step]
            font.bold: true; Layout.fillWidth: true; wrapMode: Text.Wrap
        }
        ScrollView {
            id: scroll
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: scroll.availableWidth
                spacing: 10
                ColumnLayout {
                    visible: wizard.manager.step === 0
                    enabled: !wizard.manager.busy
                    Layout.fillWidth: true; spacing: 10
                    Label {
                        text: "Мастер устанавливает LibreTranslate в Docker и подключает его к существующему HTTPS-сайту nginx. Подходит для сервера Dubbing Manager. Нужны Python 3, доступ root или sudo, минимум 2 ГБ свободного диска; для нескольких языков рекомендуется от 4 ГБ памяти."
                        Layout.fillWidth: true; wrapMode: Text.Wrap; color: wizard.colors.muted
                    }
                    Label { text: "IP-адрес или имя сервера SSH" }
                    DialogTextField {
                        objectName: "libreSshHost"; Layout.fillWidth: true
                        text: wizard.profile.host; placeholderText: "server.example.com"
                        enabled: !wizard.manager.pending
                        onEditingFinished: wizard.manager.setField("host", text)
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            Label { text: "Пользователь SSH" }
                            DialogTextField { objectName: "libreSshUser"; text: wizard.profile.ssh_user; Layout.fillWidth: true; enabled: !wizard.manager.pending; onEditingFinished: wizard.manager.setField("ssh_user", text) }
                        }
                        ColumnLayout {
                            Label { text: "Порт SSH" }
                            SpinBox { from: 1; to: 65535; editable: true; value: wizard.profile.ssh_port; enabled: !wizard.manager.pending; onValueModified: wizard.manager.setField("ssh_port", value) }
                        }
                    }
                    Label { text: "Закрытый SSH-ключ (пусто — SSH-агент или стандартные ключи)"; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    RowLayout {
                        Layout.fillWidth: true
                        DialogTextField { objectName: "libreSshKey"; text: wizard.profile.key_file; Layout.fillWidth: true; onEditingFinished: wizard.manager.setField("key_file", text) }
                        Button { text: "Выбрать…"; onClicked: wizard.manager.chooseKey() }
                    }
                    Label { text: "Пароль SSH (если не используете ключ)" }
                    DialogTextField { id: sshPassword; Layout.fillWidth: true; echoMode: TextInput.Password; Accessible.name: "Пароль SSH" }
                    Label { text: "Пароль закрытого ключа (если установлен)" }
                    DialogTextField { id: passphrase; Layout.fillWidth: true; echoMode: TextInput.Password; Accessible.name: "Пароль SSH-ключа" }
                    Label { text: "Пароль sudo (для пользователя без прав root)" }
                    DialogTextField { id: sudoPassword; Layout.fillWidth: true; echoMode: TextInput.Password; Accessible.name: "Пароль sudo" }
                    Label { text: "Домен существующего HTTPS-сайта" }
                    DialogTextField {
                        objectName: "libreHttpsDomain"; text: wizard.profile.domain
                        placeholderText: "example.com — без https://"
                        Layout.fillWidth: true; enabled: !wizard.manager.pending
                        onEditingFinished: wizard.manager.setField("domain", text)
                    }
                    Label { text: "Файл nginx, подключённый через include внутри server"; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    DialogTextField {
                        text: wizard.profile.snippet; Layout.fillWidth: true; enabled: !wizard.manager.pending
                        onEditingFinished: wizard.manager.setField("snippet", text)
                    }
                    Label { text: "Языковые модели (коды через запятую)" }
                    DialogTextField { text: wizard.profile.languages; Layout.fillWidth: true; enabled: !wizard.manager.pending; onEditingFinished: wizard.manager.setField("languages", text) }
                    Label { text: "Для сервера Dubbing Manager укажите его HTTPS-домен и оставьте стандартный файл nginx. Docker будет установлен из репозитория Debian / Ubuntu, если отсутствует. Пароли хранятся только в памяти до завершения операции."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: wizard.colors.muted }
                }
                ColumnLayout {
                    visible: wizard.manager.step === 1
                    Layout.fillWidth: true; spacing: 12
                    Label { text: "Сервер: " + wizard.profile.host + ":" + wizard.profile.ssh_port; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    Label { text: wizard.manager.hostKey.key_type || "" }
                    Label {
                        objectName: "libreHostFingerprint"
                        text: wizard.manager.hostKey.fingerprint || ""
                        textFormat: Text.PlainText; font.family: backend.isMac ? "Menlo" : "Consolas"
                        Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
                    }
                    Label {
                        visible: !!wizard.manager.hostKey.changed
                        text: "Ключ изменился. Подключение заблокировано. Сначала проверьте причину смены ключа у провайдера и обновите сохранённый ключ SSH. Пароли серверу не передавались."
                        Layout.fillWidth: true; wrapMode: Text.Wrap; color: wizard.colors.warning
                    }
                    CheckBox {
                        id: trusted
                        objectName: "libreTrustHost"
                        visible: !wizard.manager.hostKey.changed
                        text: "Отпечаток совпадает с ключом в панели провайдера"
                        Layout.fillWidth: true
                    }
                }
                ColumnLayout {
                    visible: wizard.manager.step === 2
                    Layout.fillWidth: true; spacing: 12
                    Label {
                        objectName: "libreServerPlan"
                        text: "Адрес сервиса: " + (wizard.manager.plan.url || "")
                            + "\nКонтейнер: " + (wizard.manager.plan.exists ? "найден, модели будут сохранены" : "будет установлен")
                            + "\nDocker: " + (wizard.manager.plan.dockerMissing ? "будет установлен из репозитория системы" : "уже установлен")
                            + "\nЛокальный порт: 127.0.0.1:" + (wizard.manager.plan.port || "")
                            + "\nСвободно на диске: " + (wizard.manager.plan.freeGB || "") + " ГБ"
                        textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.Wrap
                    }
                    Label { text: "Действие" }
                    ComboBox {
                        objectName: "libreServerAction"
                        Layout.fillWidth: true
                        model: wizard.manager.plan.exists
                            ? (wizard.manager.plan.managed ? ["Настроить подключение", "Переустановить", "Удалить"] : ["Подключить существующий контейнер", "Переустановить"])
                            : ["Установить"]
                        onActivated: { wizard.action = ["install", "reinstall", "uninstall"][currentIndex]; consent.checked = false }
                    }
                    Label {
                        text: wizard.action === "uninstall"
                            ? "Сервис будет остановлен, его путь /libretranslate/ удалён из nginx. Модели, база ключей и остановленная копия контейнера останутся для восстановления."
                            : "Мастер создаст защищённый API-ключ и маршрут /libretranslate/ в существующем nginx. При переустановке используется установленная версия образа. Модели и прежний контейнер сохраняются; при ошибке мастер выполнит откат. Адрес и новый API-ключ будут добавлены в настройки Substance."
                        Layout.fillWidth: true; wrapMode: Text.Wrap
                    }
                    Label { text: "Первый запуск может занять до 30 минут из-за загрузки моделей. После обрыва связи нажмите «Подключиться снова»: мастер найдёт эту же операцию."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: wizard.colors.muted }
                    CheckBox { id: consent; objectName: "libreServerConsent"; text: wizard.action === "uninstall" ? "Подтверждаю удаление сервиса" : "Подтверждаю изменения на этом сервере"; Layout.fillWidth: true }
                }
                Label {
                    objectName: "libreServerStatus"
                    text: wizard.manager.status; visible: !!text
                    textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.Wrap
                }
                ProgressBar { visible: wizard.manager.busy || wizard.manager.step === 3; indeterminate: true; Layout.fillWidth: true }
            }
        }
        Flow {
            Layout.fillWidth: true; spacing: 8
            Button {
                objectName: "libreConnect"
                visible: wizard.manager.step === 0
                text: wizard.manager.pending ? "Продолжить операцию" : "Подключиться"
                enabled: !wizard.manager.busy
                onClicked: {
                    forceActiveFocus()
                    Qt.callLater(function() {
                        wizard.manager.connectToServer(sshPassword.text, passphrase.text, sudoPassword.text)
                        sshPassword.text = ""; passphrase.text = ""; sudoPassword.text = ""
                    })
                }
            }
            Button { text: "Проверить сервер"; visible: wizard.manager.step === 1 && !wizard.manager.hostKey.changed; enabled: trusted.checked && !wizard.manager.busy; onClicked: wizard.manager.confirmHostKey() }
            Button {
                objectName: "libreExecute"
                text: wizard.action === "uninstall" ? "Удалить LibreTranslate" : wizard.action === "reinstall" ? "Переустановить" : "Установить / настроить"
                visible: wizard.manager.step === 2
                enabled: consent.checked && !wizard.manager.busy
                onClicked: wizard.manager.execute(wizard.action)
            }
            Button { text: wizard.manager.pending ? "Подключиться снова" : "К подключению"; visible: wizard.manager.step > 0; enabled: !wizard.manager.busy; onClicked: { wizard.action = "install"; trusted.checked = false; wizard.manager.reconnect() } }
            Button { text: "Закрыть"; onClicked: wizard.close() }
        }
    }
}
