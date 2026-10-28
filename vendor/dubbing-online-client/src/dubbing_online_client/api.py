"""Bounded HTTPS API transport. No Qt, desktop settings or server dependencies."""

import json
import ssl
from urllib import request, error
from urllib.parse import urlsplit, urlunsplit, urlencode
import ipaddress


class Cancelled(Exception):
    pass


MESSAGES = {
    "recording_context_required": "Обновите Dubbing Companion для безопасной отправки отметок записи. Затем проверьте актуальный текст и подтвердите отметку заново.",
    "membership_exists": "Этот человек уже в команде. Обновите проект и измените его роли в списке участников.",
    "project_import_invalid": "Данные .dub не соответствуют формату сервера. Проверьте имена, поля глоссария и тексты серий.",
    "workspace_revision_conflict": "Кастинг или отметки записи уже изменены коллегой. Черновик сохранён; откройте сравнение в разделе восстановления.",
    "workspace_data_invalid": "Проверьте данные актёров, назначения и отметки записи.",
    "recording_cues_changed": "Состав реплик изменился. Обновите проект перед сохранением отметок записи.",
    "recording_document_changed": "Текст серии изменился. Проверьте текущую версию перед отметкой записи.",
    "recording_history_immutable": "История записи доступна только для чтения.",
    "media_version_conflict": "На сервере уже другая версия шрифта. Обновите список перед новой загрузкой.",
    "media_integrity_failed": "Контрольная сумма файла не совпала. Повторите передачу исходного файла.",
    "media_incomplete": "Передача файла не завершена. Выберите тот же файл для продолжения.",
    "media_format_invalid": "Файл не является поддерживаемым шрифтом.",
    "media_not_found": "Шрифт проекта недоступен.",
    "local_storage_error": "Не удалось сохранить данные на компьютере. Проверьте свободное место и доступ к каталогу приложения.",
    "source_lease_changed": "Право автора изменилось. Обновите сравнение и подтвердите текущего автора.",
    "source_reviews_changed": "Замечания изменились. Обновите сравнение и повторно выберите перенос.",
    "source_mapping_invalid": "Проверьте сопоставление строк, перенос перевода и замечаний.",
    "source_identity_reused": "Новая версия исходника не должна повторно использовать старые ID.",
    "review_action_forbidden": "Замечания доступны назначенному редактору; ответы — переводчику и редактору серии.",
    "review_not_found": "Обсуждение недоступно в этой серии.",
    "review_cue_invalid": "Реплика отсутствует в указанной ревизии. Обновите серию.",
    "review_version_conflict": "В обсуждении появился новый ответ. Черновик сохранён; обновите обсуждение перед отправкой.",
    "review_open_threads": "Сначала решите или отклоните все открытые замечания.",
    "review_episode_accepted": "Серия уже принята. Переоткройте её перед добавлением замечаний.",
    "review_state_unchanged": "Обсуждение уже находится в этом состоянии.",
    "lease_lost": "Право редактирования серии истекло или передано другому участнику. Черновик сохранён на компьютере.",
    "episode_edit_forbidden": "Нет права редактировать эту серию. Черновик сохранён на компьютере.",
    "editor_code_invalid": "Код запуска редактора истёк или уже использован. Откройте серию из DubbingManager ещё раз.",
    "episode_empty": "Сначала загрузите текст серии.",
    "episode_name_conflict": "Серия с таким названием уже существует. Выберите пустую серию или другое название.",
    "project_archived": "Проект в архиве. Верните его в работу, чтобы вносить изменения.",
    "episode_deleted": "Серия удалена. Повтор старой загрузки не восстановит её.",
    "episode_not_empty": "В серии уже есть текст. Первичный импорт не заменяет существующие версии.",
    "episode_name_changed": "Название серии изменилось. Обновите проект.",
    "episode_busy": "Другой участник получил право редактирования этой серии.",
    "glossary_name_conflict": "Карточка с таким именем уже существует. Выберите её или задайте другое имя.",
    "import_glossary_target_invalid": "Выбранная карточка недоступна или находится в архиве.",
    "operation_id_reused": "Эта операция уже выполнена с другими данными. Обновите проект и проверьте результат.",
    "character_reference_invalid": "Реплика ссылается на недоступного персонажа.",
    "account_not_found": "Аккаунт с таким логином не найден или отключён.",
    "backup_not_available": "Резервная копия недоступна.",
    "backup_in_progress": "На сервере уже создаётся резервная копия.",
    "backup_integrity_failed": "Контрольная сумма копии не совпала. Файл не сохранён.",
    "backup_too_large": "Размер резервной копии превышает 1 ТБ. Файл не сохранён.",
    "authentication_required": "Войдите в аккаунт сервера.",
    "session_invalid": "Сессия истекла или отозвана. Войдите заново.",
    "account_disabled": "Аккаунт отключён администратором.",
    "invalid_credentials": "Неверный логин или пароль.",
    "login_rate_limited": "Слишком много попыток входа. Повторите позже.",
    "login_exists": "Аккаунт с таким логином уже существует.",
    "project_not_found": "Проект недоступен. Возможно, доступ был отозван.",
    "episode_not_found": "Серия недоступна.",
    "role_required": "У аккаунта нет прав на это действие.",
    "server_admin_required": "Требуются права администратора сервера.",
    "project_admin_required": "Требуются права администратора проекта.",
    "assignee_role_required": "У участника нет соответствующей роли в проекте.",
    "active_account_required": "Нужен активный аккаунт сервера.",
    "revision_conflict": "Версия уже изменилась. Обновите проект и повторите действие.",
    "invalid_transition": "Этот переход статуса сейчас недоступен.",
    "translation_incomplete": "Сервер использует прежнюю проверку пустых строк. Обновите сервер до версии 0.1.4 или новее.",
    "production_data_invalid": "Проверьте статус проекта и отметки загруженных переводов.",
    "return_reason_required": "Укажите причину возврата на доработку.",
    "reopen_reason_required": "Укажите причину переоткрытия работы.",
    "translation_assignment_required": "Перевод серии назначен другому участнику.",
    "editing_assignment_required": "Редактура серии назначена другому участнику.",
    "recording_role_required": "Отметить запись могут администратор проекта, режиссёр, звукорежиссёр или кастинг-менеджер.",
    "recording_not_ready": "Текущая версия текста ещё не готова к записи: сдайте перевод и, если в команде есть редактор, завершите редактуру.",
    "schedule_revision_conflict": "Срок или пометки уже изменены коллегой. Обновите данные перед повторным сохранением.",
    "schedule_note_empty": "Введите текст пометки.",
    "schedule_notes_limit": "Достигнут предел пометок для этой работы (500).",
    "schedule_workflow_required": "Изменяйте сроки и пометки в карточке работы по серии.",
    "review_disabled": "В команде проекта нет редактора. Этап редактуры выключен.",
    "recording_status_workflow_required": "Измените статус записи отдельным действием серии.",
    "validation_failed": "Проверьте поля формы: имя, логин и пароль (не менее 12 символов).",
    "glossary_field_conflict": "Эти поля глоссария уже изменены. Обновите запись и сравните правки.",
    "approved_entry_requires_proposal": "Для утверждённой записи отправьте предложение редактору.",
    "glossary_approval_required": "Утвердить запись может редактор или главред.",
    "database_unavailable": "База данных сервера временно недоступна.",
    "request_too_large": "Размер запроса превышает лимит сервера.",
}


class ApiError(Exception):
    def __init__(self, code, status=0, details=None):
        self.code, self.status, self.details = code, status, details or {}
        message = MESSAGES.get(code)
        if message is None:
            message = {
                "network_error": "Не удалось связаться с сервером. Проверьте адрес и соединение.",
                "tls_error": "Не удалось проверить HTTPS-сертификат сервера.",
                "incompatible_server": "Версия API сервера несовместима с этой программой.",
                "invalid_response": "Сервер вернул некорректный ответ.",
            }.get(
                code,
                "Сервер отклонил действие."
                if status
                else "Ошибка подключения к серверу.",
            )
        super().__init__(message)


def normalize_server_url(value):
    value = str(value).strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Некорректный адрес сервера") from exc
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or parsed.scheme not in ("https", "http")
    ):
        raise ValueError(
            "Укажите адрес сервера вида https://dub.example.com без пути и пароля"
        )
    if parsed.scheme == "http":
        loopback = parsed.hostname.lower() == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            pass
        if not loopback:
            raise ValueError(
                "Удалённый сервер должен использовать HTTPS. HTTP разрешён только на localhost"
            )
    if any(char.isspace() or ord(char) < 32 for char in parsed.hostname) or port == 0:
        raise ValueError("Некорректный адрес сервера")
    host = parsed.hostname.lower().encode("idna").decode("ascii")
    if ":" in host:
        host = "[" + host + "]"
    default = 443 if parsed.scheme == "https" else 80
    authority = host + (":" + str(port) if port and port != default else "")
    return urlunsplit((parsed.scheme, authority, "", "", ""))


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ApiClient:
    def __init__(self, server_url, token="", *, timeout=12, cancel=None):
        self.url = normalize_server_url(server_url)
        self.token, self.timeout, self.cancel = token, timeout, cancel
        context = ssl.create_default_context()
        try:
            import certifi

            context.load_verify_locations(certifi.where())
        except ImportError:
            pass
        # No redirects: Bearer credentials can never be forwarded to another host.
        handlers = [NoRedirect(), request.HTTPSHandler(context=context)]
        if self.url.startswith("http://"):
            # Loopback credentials must never travel through an environment proxy.
            handlers.append(request.ProxyHandler({}))
        self.opener = request.build_opener(*handlers)

    def request(self, method, path, body=None, *, query=None, binary=False):
        if not path.startswith("/v1/") or ".." in path or "?" in path or "#" in path:
            raise ValueError("Invalid API resource path")
        if self.cancel and self.cancel.is_set():
            raise Cancelled()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if binary:
            headers["Content-Type"] = "application/octet-stream"
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        payload = (
            body
            if binary
            else (
                json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
                if body is not None
                else None
            )
        )
        req = request.Request(
            self.url + path + ("?" + urlencode(query) if query else ""),
            data=payload,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                data = response.read(32 * 1024 * 1024 + 1)
                if len(data) > 32 * 1024 * 1024:
                    raise ApiError("invalid_response")
                result = json.loads(data)
        except error.HTTPError as exc:
            try:
                details = json.loads(exc.read(1024 * 1024)).get("detail", {})
            except (ValueError, AttributeError):
                details = {}
            if not isinstance(details, dict):
                details = {}
            raise ApiError(
                details.get("code", "http_error"), exc.code, details
            ) from None
        except error.URLError as exc:
            code = (
                "tls_error" if isinstance(exc.reason, ssl.SSLError) else "network_error"
            )
            raise ApiError(code) from None
        except (OSError, TimeoutError):
            raise ApiError("network_error") from None
        except (ValueError, UnicodeError):
            raise ApiError("invalid_response") from None
        if self.cancel and self.cancel.is_set():
            raise Cancelled()
        return result

    def negotiate(self):
        info = self.request("GET", "/v1/info")
        if (
            not isinstance(info, dict)
            or type(info.get("api_version")) is not int
            or info["api_version"] != 1
            or not isinstance(info.get("document_schema_versions"), list)
            or not any(
                type(version) is int and version == 1
                for version in info["document_schema_versions"]
            )
        ):
            raise ApiError("incompatible_server")
        return info

    def image(self, project_id, asset_id):
        """Download an authorized, bounded, content-addressed image."""
        import base64
        import hashlib
        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", project_id) or not re.fullmatch(r"img_[0-9a-f]{64}", asset_id):
            raise ValueError("Invalid asset identity")
        headers = {"Authorization": "Bearer " + self.token}
        req = request.Request(self.url + f"/v1/projects/{project_id}/assets/{asset_id}", headers=headers)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(6 * 1024 * 1024 + 1)
        except error.HTTPError as exc:
            raise ApiError("asset_not_found", exc.code) from None
        except (error.URLError, OSError, TimeoutError):
            raise ApiError("network_error") from None
        if (len(raw) > 6 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != asset_id[4:]
                or not raw.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))):
            raise ApiError("invalid_response")
        return base64.b64encode(raw).decode("ascii")

    def download(self, path, destination, expected_sha256):
        from .backup_archive import MAX_BYTES
        import hashlib
        import os
        from pathlib import Path
        import tempfile

        if (
            not path.startswith("/v1/admin/backups/")
            or not path.endswith("/download")
            or ".." in path
        ):
            raise ValueError("Invalid backup path")
        if self.cancel and self.cancel.is_set():
            raise Cancelled()
        destination = Path(destination)
        fd, temporary = tempfile.mkstemp(
            prefix=".dubbing-download-", dir=destination.parent
        )
        try:
            sha256 = hashlib.sha256()
            total = 0
            req = request.Request(
                self.url + path, headers={"Authorization": "Bearer " + self.token}
            )
            with os.fdopen(fd, "wb") as stream:
                try:
                    with self.opener.open(req, timeout=self.timeout) as response:
                        while True:
                            if self.cancel and self.cancel.is_set():
                                raise Cancelled()
                            chunk = response.read(64 * 1024)
                            if not chunk:
                                break
                            total += len(chunk)
                            if total > MAX_BYTES:
                                raise ApiError("backup_too_large")
                            sha256.update(chunk)
                            stream.write(chunk)
                except error.HTTPError as exc:
                    raise ApiError("backup_not_available", exc.code) from None
                except (error.URLError, OSError, TimeoutError):
                    raise ApiError("network_error") from None
                stream.flush()
                os.fsync(stream.fileno())
            if sha256.hexdigest() != expected_sha256:
                raise ApiError("backup_integrity_failed")
            if self.cancel and self.cancel.is_set():
                raise Cancelled()
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
