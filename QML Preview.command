#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ ! -x ".venv-qt612/bin/python" ]; then
    printf 'Сначала выполни: .venv/bin/python scripts/setup_qml_preview.py\n'
    exit 1
fi
".venv-qt612/bin/python" scripts/qml_preview.py "$@"
result=$?
if [ "$result" -ne 0 ]; then
    printf '\nНе удалось запустить предпросмотр. Нажми Enter, чтобы закрыть окно.\n'
    read -r reply
fi
exit "$result"
