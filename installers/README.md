# Установка ResearcherOS

Готовые установщики macOS, Windows и Linux доступны в [GitHub Releases](https://github.com/CognitiveAISystems/ResearcherOS/releases). Скачивать репозиторий и устанавливать Git LFS не нужно.

- [Стабильный выпуск](https://github.com/CognitiveAISystems/ResearcherOS/releases/latest): DMG `arm64` для Mac с Apple Silicon, DMG `x64` для Intel, `.exe` для Windows или `.AppImage` для Linux x86_64.
- [Сборки для A/B-тестирования](https://github.com/CognitiveAISystems/ResearcherOS/releases): выпуски `beta-test` с отметкой Pre-release. Они не заменяют стабильную версию.

На Linux разрешите выполнение `.AppImage` в свойствах файла. Нужна glibc 2.35 или новее (Ubuntu 22.04 и новее). Для подключения исследовательских репозиториев нужен Git.

В этой папке остаётся только [установщик macOS из исходников](Установить%20ResearcherOS.command). Запускайте его из клона репозитория. Это альтернативный способ установки; скрипт по-прежнему собирает приложение на вашем Mac.

[Подробная инструкция по установке](../README.md#установка).

Для установки из DMG перенесите приложение в Applications. DMG выпускаются без сертификата Developer ID и notarization Apple. Если macOS блокирует первый запуск, разрешите его в «Системные настройки → Конфиденциальность и безопасность».
