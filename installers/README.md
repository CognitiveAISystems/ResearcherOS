# Установщики ResearcherOS

Клонируйте репозиторий с установленным [Git LFS](https://git-lfs.com/), затем запустите файл для своей системы.

| Система | Файл |
|---------|------|
| macOS | [Установить ResearcherOS.command](Установить%20ResearcherOS.command) |
| Windows | [ResearcherOS Setup 0.1.0.exe](ResearcherOS%20Setup%200.1.0.exe) |
| Linux | [ResearcherOS-0.1.0.AppImage](ResearcherOS-0.1.0.AppImage) |

На macOS установщик собирает приложение из исходников в этом клоне репозитория. Для Windows и Linux здесь лежат готовые тестовые сборки из [GitHub Actions](https://github.com/CognitiveAISystems/ResearcherOS/actions/runs/38227118667). Их установка и запуск проверены автоматически; первоначальная настройка и обновление на пользовательских компьютерах ещё требуют проверки.

Если `.exe` или `.AppImage` не запускается и вместо приложения скачался маленький текстовый файл, выполните `git lfs install` и `git lfs pull` из корня репозитория.

[Подробная установка и подключение проектов](../README.md#установка).
