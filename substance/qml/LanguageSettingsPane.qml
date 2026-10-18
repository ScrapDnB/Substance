import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: pane
    required property var colors
    readonly property var assistance: backend.languageAssistance
    readonly property var config: assistance.config
    clip: true
    contentWidth: availableWidth
    objectName: "languageSettingsPane"
    ColumnLayout {
        width: pane.availableWidth
        spacing: 18
        DialogSection {
            title: "Языки и работа панели"
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                spacing: 10
                CheckBox {
                    objectName: "assistanceLocalOnly"
                    text: "Только локальные словари"
                    checked: pane.config.localOnly
                    onClicked: pane.assistance.setOption("localOnly", checked)
                }
                Label {
                    visible: pane.config.localOnly
                    text: "Выделенный текст остаётся на этом компьютере. Доступны значения, примеры и переводы из установленных словарей. Перевод предложений и машинный перевод пояснений отключены."
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.muted
                }
                Label { text: "Язык оригинала" }
                ComboBox {
                    objectName: "assistanceSourceLanguage"
                    Layout.fillWidth: true
                    model: [{code: "auto", title: "Определять автоматически"}].concat(pane.assistance.languages)
                    textRole: "title"
                    currentIndex: Math.max(0, model.findIndex(l => l.code === pane.config.source))
                    onActivated: pane.assistance.setOption("source", model[currentIndex].code)
                }
                Label { text: "Язык переводов и пояснений" }
                ComboBox {
                    objectName: "assistanceTargetLanguage"
                    Layout.fillWidth: true
                    model: pane.assistance.languages
                    textRole: "title"
                    currentIndex: Math.max(0, model.findIndex(l => l.code === pane.config.target))
                    onActivated: pane.assistance.setOption("target", model[currentIndex].code)
                }
                CheckBox { text: pane.config.localOnly ? "Искать после выделения" : "Искать и переводить после выделения"; checked: pane.config.automatic; onClicked: pane.assistance.setOption("automatic", checked) }
                CheckBox { visible: !pane.config.localOnly; text: "Передавать текущую реплику как контекст в DeepL"; checked: pane.config.context; onClicked: pane.assistance.setOption("context", checked) }
                CheckBox { visible: !pane.config.localOnly; text: "Переводить словарные пояснения выбранным сервисом"; checked: pane.config.translateDefinitions; onClicked: pane.assistance.setOption("translateDefinitions", checked) }
                Label {
                    text: pane.config.localOnly ? "Выделите слово для просмотра значений и примеров. Для ручного поиска нажмите «Найти» на панели. Скачивание новых словарей запускается только кнопкой ниже."
                        : "Выделите слово для просмотра значений и примеров или фразу для связного перевода. Автопоиск срабатывает после паузы. Без него нажмите «Найти / перевести» на панели. Перевод пояснений тоже расходует квоту API."
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.muted
                }
            }
        }
        DialogSection {
            objectName: "assistanceOnlineSettings"
            visible: !pane.config.localOnly
            title: "Сервис перевода"
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                spacing: 10
                ComboBox {
                    objectName: "assistanceProvider"
                    Layout.fillWidth: true
                    model: ["Microsoft Azure", "DeepL", "LibreTranslate"]
                    currentIndex: ["azure", "deepl", "libre"].indexOf(pane.config.provider)
                    onActivated: { secret.text = ""; pane.assistance.setOption("provider", ["azure", "deepl", "libre"][currentIndex]) }
                    Accessible.name: "Сервис перевода"
                }
                Label { visible: pane.config.provider === "azure"; text: "Регион ресурса Azure (например, westeurope)"; Layout.fillWidth: true; wrapMode: Text.Wrap }
                DialogTextField {
                    objectName: "assistanceAzureRegion"
                    visible: pane.config.provider === "azure"
                    Layout.fillWidth: true
                    text: pane.config.azureRegion
                    placeholderText: "Можно оставить пустым для глобального ресурса"
                    onEditingFinished: pane.assistance.setOption("azureRegion", text.trim())
                }
                ComboBox {
                    visible: pane.config.provider === "deepl"
                    Layout.fillWidth: true
                    model: ["DeepL: автоматически по ключу", "DeepL: api-free.deepl.com", "DeepL: api.deepl.com"]
                    currentIndex: ["auto", "free", "pro"].indexOf(pane.config.deeplPlan)
                    onActivated: pane.assistance.setOption("deeplPlan", ["auto", "free", "pro"][currentIndex])
                    Accessible.name: "Адрес API DeepL"
                }
                Label { visible: pane.config.provider === "libre"; text: "Адрес сервера LibreTranslate" }
                DialogTextField {
                    objectName: "assistanceLibreUrl"
                    visible: pane.config.provider === "libre"
                    Layout.fillWidth: true
                    text: pane.config.libreUrl
                    placeholderText: "http://localhost:5000"
                    onEditingFinished: pane.assistance.setOption("libreUrl", text.trim())
                }
                Button {
                    objectName: "assistanceServerWizard"
                    visible: pane.config.provider === "libre"
                    text: "Установка и управление сервером…"
                    Layout.fillWidth: true
                    onClicked: { forceActiveFocus(); pane.assistance.serverManager.open() }
                }
                Label { text: pane.config.provider === "libre" ? "API-ключ (если сервер требует)" : "API-ключ" }
                DialogTextField {
                    id: secret
                    objectName: "assistanceApiKey"
                    Layout.fillWidth: true
                    echoMode: TextInput.Password
                    placeholderText: pane.assistance.hasKey ? "Ключ уже добавлен. Введите новый для замены." : "Вставьте API-ключ"
                    selectByMouse: true
                    Accessible.name: "API-ключ сервиса перевода"
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Button { text: "Сохранить ключ"; enabled: secret.text.trim().length > 0; onClicked: { pane.assistance.saveKey(secret.text); secret.text = "" } }
                    Button { text: "Удалить ключ"; enabled: pane.assistance.hasKey; onClicked: { secret.text = ""; pane.assistance.saveKey("") } }
                    Button { objectName: "assistanceCheckConnection"; text: "Проверить подключение"; enabled: !pane.assistance.checking; onClicked: { forceActiveFocus(); Qt.callLater(pane.assistance.checkConnection) } }
                }
                Label { text: pane.assistance.keyMessage; visible: !!text; Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.muted }
                Label { objectName: "assistanceCheckStatus"; text: pane.assistance.checkStatus; visible: !!text; Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.text; textFormat: Text.PlainText }
                Label {
                    text: "Ключи сохраняются в системном хранилище этого компьютера. Проверка переводит короткое приветствие с выбранными языками. При поиске в API уходит выделенный текст; при включённом контексте DeepL — также текущая реплика."
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.muted
                }
            }
        }
        DialogSection {
            objectName: "assistanceOnlineInstructions"
            visible: !pane.config.localOnly
            title: "Как подключить " + pane.assistance.providerTitle
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                spacing: 10
                Label {
                    objectName: "assistanceProviderInstructions"
                    text: pane.config.provider === "azure"
                        ? "1. Войдите в Azure Portal и создайте ресурс Translator.\n2. Выберите бесплатный тариф F0.\n3. В разделе Keys and Endpoint скопируйте ключ и регион.\n4. Вставьте ключ выше, сохраните его и укажите регион.\n5. Нажмите «Проверить подключение». Доступность регистрации зависит от страны и аккаунта."
                        : pane.config.provider === "deepl"
                        ? "1. Зарегистрируйте отдельный аккаунт DeepL API. Обычная подписка на переводчик не заменяет API.\n2. Скопируйте API-ключ в личном кабинете.\n3. Сохраните ключ выше. Автоматический режим выбирает api-free для ключа с окончанием :fx, иначе api.deepl.com. При необходимости выберите адрес вручную.\n4. Проверьте подключение. Бесплатный объём и тариф смотрите в своём кабинете."
                        : "1. Для VPS нажмите «Установка и управление сервером…». Укажите SSH-адрес, пользователя, ключ или пароль и домен существующего HTTPS-сайта nginx. Для сервера Dubbing Manager оставьте стандартный файл nginx.\n2. Сверьте отпечаток SSH-ключа с панелью провайдера. Мастер проверит сервер и покажет действия перед запуском.\n3. После установки HTTPS-адрес и API-ключ появятся здесь автоматически. В том же мастере можно переустановить или удалить сервис с сохранением моделей.\n4. Для запуска на этом компьютере используйте Docker-команду ниже и адрес http://localhost:5000. Собственный сервер использует ваши ресурсы; официальный облачный API оплачивается отдельно."
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.text
                }
                Label {
                    visible: pane.config.provider === "libre"
                    text: "Если установлен Docker Desktop, запустите команду ниже в терминале. При первом запуске загрузятся образ и модели английского и русского; дождитесь готовности сервера. После перезагрузки компьютера: docker start substance-libretranslate. Для других языков измените LT_LOAD_ONLY."
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.muted
                }
                Label {
                    visible: pane.config.provider === "libre"
                    text: pane.assistance.libreCommand
                    textFormat: Text.PlainText
                    font.family: backend.isMac ? "Menlo" : "Consolas"
                    font.pixelSize: 11
                    Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; color: pane.colors.text
                }
                Button { visible: pane.config.provider === "libre"; text: "Копировать команду запуска"; onClicked: pane.assistance.copyLibreCommand() }
                Button {
                    text: "Официальная инструкция ↗"
                    onClicked: Qt.openUrlExternally(pane.config.provider === "azure"
                        ? "https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/quickstart/rest-api"
                        : pane.config.provider === "deepl" ? "https://developers.deepl.com/docs/getting-started/auth" : "https://docs.libretranslate.com/")
                }
            }
        }
        DialogSection {
            title: "Локальные словари"
            Layout.fillWidth: true
            ColumnLayout {
                anchors.fill: parent
                spacing: 10
                Label {
                    text: "Скачайте словарь один раз: значения и примеры будут доступны без сети и API-ключа. Базовый английский компактный и содержит общеупотребительные слова. Русская редакция содержит статьи о словах разных языков с пояснениями на русском. Полнота переводов зависит от статьи."
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.muted
                }
                Repeater {
                    model: pane.assistance.packs
                    Button {
                        required property var modelData
                        text: "Скачать: " + modelData.title
                        Layout.fillWidth: true
                        enabled: !pane.assistance.installing
                        onClicked: pane.assistance.downloadDictionary(modelData.id)
                    }
                }
                Label { text: "Установленные словари"; font.bold: true }
                Label {
                    objectName: "assistanceInstalledDictionaries"
                    text: pane.assistance.installed.length ? pane.assistance.installed.join("\n") : "Словари ещё не установлены."
                    textFormat: Text.PlainText
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.text
                }
                Label { text: pane.assistance.installStatus; visible: !!text; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText; color: pane.colors.text }
                ProgressBar { visible: pane.assistance.installing; indeterminate: true; Layout.fillWidth: true }
                Button { text: "Отменить установку"; visible: pane.assistance.installing; onClicked: pane.assistance.cancelInstall() }
                Label {
                    text: "Для полного словаря откройте каталог Kaikki, скачайте raw Wiktextract JSONL или JSONL.GZ нужной редакции, выберите язык её пояснений ниже и импортируйте файл. Большие базы могут потребовать несколько гигабайт и время на индексирование. Во время обновления прежняя база остаётся доступной."
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.muted
                }
                Label { text: "Язык пояснений в импортируемом файле"; Layout.fillWidth: true; wrapMode: Text.Wrap }
                ComboBox { id: importLanguage; model: pane.assistance.languages; textRole: "title"; Layout.fillWidth: true }
                Flow {
                    Layout.fillWidth: true; spacing: 8
                    Button { text: "Импортировать словарь…"; enabled: !pane.assistance.installing; onClicked: pane.assistance.importDictionary(importLanguage.model[importLanguage.currentIndex].code) }
                    Button { text: "Каталог Kaikki ↗"; onClicked: Qt.openUrlExternally("https://kaikki.org/dictionary/rawdata.html") }
                }
                Label {
                    text: "Источник: Викисловарь / Kaikki, извлечение Wiktextract. Ссылки на исходные статьи и лицензии показаны рядом со значениями. Автоперевод пояснений обозначается отдельно."
                    Layout.fillWidth: true; wrapMode: Text.Wrap; color: pane.colors.muted
                }
            }
        }
    }
}
