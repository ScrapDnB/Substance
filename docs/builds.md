# Автоматические сборки

Workflow `Test and build alpha` автоматически запускается при обновлении
`main` и для pull request. В разделе **Actions → Test and build alpha → Run
workflow** можно запустить сборку вручную.

Две задачи выполняются независимо:

- Windows x64: Python 3.13, Qt, FFmpeg, ffprobe и libass; архив
  `Substance-Windows-x64.zip` содержит папку `Substance` с `Substance.exe`.
- macOS Apple Silicon: Python 3.13, Qt, переносимые библиотеки conda-forge и
  загрузчик с SDK 26+. Архив `Substance-macOS.zip` содержит `Substance.app`.
  Минимум macOS 15 проверяется для всех включённых Mach-O. Подпись локальная;
  Developer ID и notarization не настроены.

Перед упаковкой тестовые модули запускаются отдельными процессами с одним
`QApplication` на процесс. Видео в тестах декодируется программно, чтобы
проверки не зависели от GPU виртуальной машины. Затем запускается готовое
приложение из временной папки без путей к исходникам и сборочным библиотекам:
проверяются загрузка QML, системный стиль, встроенные FFmpeg, ffprobe и наличие
libass. Эта проверка не заменяет ручную проверку интерфейса, звука и видео.

Архивы доступны в **Actions → завершённый запуск → Artifacts** в течение
14 дней. В приватном репозитории для скачивания нужен доступ к репозиторию.
Артефакты `package-diagnostics-*` содержат сведения о проверке пакета.
macOS-приложение архивируется до загрузки, чтобы сохранить права исполнения
и символические ссылки.

## Сборка в Windows без виртуального окружения

Установить Python 3.13 x64 и MSYS2 в `C:\msys64`, скопировать репозиторий
на локальный диск Windows. В терминале **MSYS2 UCRT64** выполнить:

```sh
pacman -Syu
pacman -S --needed mingw-w64-ucrt-x86_64-libass mingw-w64-ucrt-x86_64-ffmpeg
```

Если обновление MSYS2 просит перезапуск терминала, выполнить его перед
установкой библиотек. Затем в PowerShell из корня репозитория:

```powershell
py -3.13 -m pip install ./vendor/dubbing-online-client
py -3.13 -m pip install -e ".[dev]"
$env:SUBSTANCE_LIBASS = "C:\msys64\ucrt64\bin\libass-9.dll"
$env:SUBSTANCE_FFPROBE = "C:\msys64\ucrt64\bin\ffprobe.exe"
$env:PATH = "C:\msys64\ucrt64\bin;" + $env:PATH
py -3.13 scripts/test.py
py -3.13 scripts/build.py
py -3.13 scripts/verify_package.py
```

Готовое приложение — `dist\Substance\Substance.exe`. Для переноса нужна вся
папка `dist\Substance`, включая `_internal`. Python и MSYS2 на компьютере
пользователя не требуются.
