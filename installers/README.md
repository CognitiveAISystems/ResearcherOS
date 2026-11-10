# Установщики ResearcherOS

Новые сборки Windows и Linux публикуются в [GitHub Releases](https://github.com/CognitiveAISystems/ResearcherOS/releases): стабильные — `vX.Y.Z`, для A/B-тестирования — `vX.Y.Z-beta-test.N` с отметкой Pre-release. Первые файлы появятся после успешного запуска сборки по тегу.

Файлы в этой папке оставлены для переходного периода и больше не обновляются автоматически. Для macOS пока используется установщик из исходников, описанный ниже.

Клонируйте репозиторий с установленным [Git LFS](https://git-lfs.com/), затем запустите файл для своей системы.

| Система | Файл |
|---------|------|
| macOS | [Установить ResearcherOS.command](Установить%20ResearcherOS.command) |
| Windows | [ResearcherOS Setup 0.1.0.exe](ResearcherOS%20Setup%200.1.0.exe) |
| Linux | [ResearcherOS-0.1.0.AppImage](ResearcherOS-0.1.0.AppImage) |

На macOS установщик собирает приложение из исходников текущего клона. Установщики Windows и Linux собраны из коммита `5663182` ветки `beta` в [GitHub Actions](https://github.com/CognitiveAISystems/ResearcherOS/actions/runs/42776409292).

Сборка Windows прошла автоматическую проверку установки и запуска. Linux AppImage собран на Ubuntu 22.04 (x86_64, glibc 2.35) и прошёл проверку запуска на Ubuntu 22.04 и 24.04 на виртуальном экране Xvfb. Обновление поверх прежней установки и работу с физическим экраном для этих сборок не проверяли. Python и Node.js пользователю устанавливать не нужно; для подключения Git-репозиториев нужен Git.

Если `.exe` или `.AppImage` не запускается и вместо приложения скачался маленький текстовый файл, выполните `git lfs install` и `git lfs pull` из корня репозитория.

[Подробная установка и подключение проектов](../README.md#установка).
