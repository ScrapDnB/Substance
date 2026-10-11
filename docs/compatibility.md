# Контракт будущего адаптера Dubbing Manager

Открытие проектов Dubbing Manager намеренно не реализовано. Substance отклоняет чужой JSON, не переименовывает и не пересохраняет его как свой проект. Совместимость заложена в модели и требует отдельного адаптера и интеграционных тестов перед включением.

Изучены публичный репозиторий `ScrapDnB/DubbingManager` и локальные исходники на коммите `78e0c626eab12bd41c1ed90138c09627530b7b43`. В изученной версии проект имеет версию `2.0`; динамическое хранилище использует `model: dynamic_source`, `schema_revision: 1`. Главный контракт находится в `services/dynamic_script_storage.py`.

## Модель Substance

`Document` не зависит от Qt. Время в редакторе — целые миллисекунды; в реестре происхождения — секунды с исходными строковыми таймкодами. Номер строки в таблице не является идентификатором. `Cue.id` и `Cue.source_ids` сохраняются в `.substance` и служебном файле ASS.

| Dubbing Manager | Substance | Правило адаптера |
|---|---|---|
| `source_lines[].id` | `source_lines` и `source_ids` | Сохранить внешние ID, не генерировать новые при каждом сохранении |
| `order`, `origin.event_index` | Порядок импорта и индекс ASS-события | Не заменять исходный порядок порядком отсортированной таблицы |
| `start`, `end`, `s_raw`, `e_raw` | Секунды в источнике, миллисекунды в реплике | Переводить единицы на границе адаптера |
| `character`, `text` | Персонаж, оригинал, текст/перевод | Персонаж отделён от исполнителя/голоса |
| `edit_blocks[].source_ids` | Источники одной или нескольких реплик | Группировать связанные фрагменты в единый блок |
| `fragments[].id` | `Cue.id` | Сохранять ID фрагмента при обычном редактировании |
| Исходный снимок серии | Реестр исходных строк, SHA-256 файла | Сохранить снимок и метаданные серии при подключении адаптера |

Разделение создаёт новый ID фрагмента и сохраняет общий `source_ids`. Объединение соседних реплик объединяет источники, сохраняя их порядок, и не повторяет оригинал после обратного объединения разделённой строки. Удаление реплики не уничтожает её запись в реестре исходных строк. Дублирование сохраняет происхождение и получает новый ID фрагмента.

Сохраняются неизвестные поля проекта и реплик (`extras`), метаданные источника, поля ASS, служебные секции, вложения и необрабатываемые строки. Версия схемы проверяется независимо от версии приложения; более новая схема не перезаписывается молча. ASS после внешнего изменения не получает старый перевод из служебного файла.

## Требования к будущему адаптеру

1. Импортировать одну выбранную серию как документ с внешними ID серии, источников, блоков и фрагментов; не смешивать проектную версию с версией приложения.
2. Представлять связанные фрагменты через DM-блоки. DM требует непрерывные источники и покрытие исходных строк один раз; произвольное удаление, дублирование и сортировка в Substance могут нарушить эти ограничения. Адаптер должен явно разрешить эти случаи, а не обещать прямой экспорт текущего массива реплик.
3. Сохранять персонажей, алиасы, назначения актёров, параметры серии и чужие поля проекта. Голос/исполнитель не должны заменять `character`.
4. Использовать неизменный снимок исходника; применять изменения к фрагментам, сохраняя происхождение. Обратные и повреждённые ASS-события требуют согласованного отображения с парсером DM.
5. Проверить split/merge/delete/duplicate, переоткрытие, обновление внешнего исходника и отклонение новых схем на реальных проектах DM до включения записи.

Приватные файлы из `DubbingManager/test_files` используются только как данные проверок чтения/сохранения ASS; наличие этих тестов не является подтверждением готового импорта проектов DM.

## Substance schema 2

The standalone project stores `reviews`, `characters`, a content-addressed
`images` registry and `review_settings`. Cues link to characters by `character_id`.
Schema 1 is still read; former cue statuses are preserved as legacy extras and
have no runtime behavior. Unknown fields of cues, review records, cards and the
project survive round trips. More recent schemas are rejected.

Review proposals store a target field, baseline and replacement. Applying an
outdated proposal is rejected; rebasing selects one current cue. Structural edits
rebind notes and invalidate pending proposals. Deleted-cue records remain archived.

Image assets are JPEG/PNG encoded as Base64, keyed by SHA-256. Portraits reference
a bounded source image, crop rectangle, rendered image, video path and timestamp.
Resources are immutable; deleting an unused portrait prunes resources in the new
revision, while undo history retains the previous revision.

Plain export writes only subtitles. ASS translation sidecars omit project-only
records and clear character IDs; they are not character-card projects.
