#!/bin/sh
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
    printf 'Не найден Python: .venv/bin/python. Сначала настрой окружение Substance.\n'
    printf 'Нажми Enter, чтобы закрыть окно.\n'
    read -r reply
    exit 1
fi

SUBSTANCE_STYLE=FluentWinUI3 ".venv/bin/python" run.py "$@"
result=$?
if [ "$result" -ne 0 ]; then
    printf '\nНе удалось запустить Substance. Нажми Enter, чтобы закрыть окно.\n'
    read -r reply
fi
exit "$result"
