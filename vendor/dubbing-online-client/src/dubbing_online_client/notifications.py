"""Shared notification vocabulary. Project permissions are enforced by the server."""

TOPICS = {
    "projects": ("Проекты и доступ", "Новые проекты, состав команды и статус проекта."),
    "assignments": ("Назначения", "Назначение и смена исполнителей ваших работ."),
    "deadlines": ("Изменения сроков", "Изменения сроков и примечания к плану работ."),
    "workflow": ("Готовность и доработка", "Сдача перевода, проверка, принятие и возврат текста."),
    "documents": ("Тексты и исходники", "Загрузка и изменение доступных вам текстов."),
    "reviews": ("Обсуждения", "Комментарии к тексту, ответы и решения."),
    "glossary": ("Глоссарий", "Изменения карточек и предложения участников."),
    "casting": ("Кастинг", "Актёры и распределение персонажей."),
    "recording": ("Запись", "Отметки записи и готовность серий."),
    "server_updates": ("Обновления сервера", "Новая версия сервера. Только для администратора сервера."),
}


def allowed_topics(roles, *, server_admin=False, review=True):
    roles = set(roles)
    if server_admin or roles & {"admin", "chief_editor"}:
        result = set(TOPICS) - {"server_updates"}
    else:
        result = {"projects", "documents", "glossary", "reviews"}
        if roles & {"translator", "editor"}:
            result.update({"assignments", "deadlines", "workflow"})
        if roles & {"casting_director", "director", "sound_engineer", "actor"}:
            result.update({"casting", "recording", "deadlines", "workflow"})
    if server_admin:
        result.add("server_updates")
    return [key for key in TOPICS if key in result]


def event_topic(action):
    if action.startswith(("project.create", "project.archive", "project.restore", "project.status", "membership.", "episode.create", "episode.delete")):
        return "projects"
    if action == "task.assign":
        return "assignments"
    if action == "task.schedule":
        return "deadlines"
    if action in {"workflow.mark_recorded", "companion.actor_recording"}:
        return "recording"
    if action.startswith("workflow.") or action in {"project.translation_uploaded", "episode.translation_uploaded"}:
        return "workflow"
    if action.startswith(("document.", "source.", "episode.import", "media.publish", "episode.issue")):
        return "documents"
    if action.startswith(("review.", "companion.note")):
        return "reviews"
    if action.startswith("glossary."):
        return "glossary"
    if action.startswith(("actor.", "casting.")):
        return "casting"
    return None
