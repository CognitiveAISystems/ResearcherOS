# Установщики ResearcherOS

Клонируйте репозиторий с установленным [Git LFS](https://git-lfs.com/), затем запустите файл для своей системы.

| Система | Файл |
|---------|------|
| macOS | [Установить ResearcherOS.command](Установить%20ResearcherOS.command) |
| Windows | [ResearcherOS Setup 0.1.0.exe](ResearcherOS%20Setup%200.1.0.exe) |
| Linux | [ResearcherOS-0.1.0.AppImage](ResearcherOS-0.1.0.AppImage) |

На macOS установщик собирает приложение из исходников текущего клона. Установщики Windows и Linux собраны 28 октября 2026 года из коммита `6505e15` ветки `beta` в [GitHub Actions](https://github.com/CognitiveAISystems/ResearcherOS/actions/runs/40708009441).

Сборка Windows прошла автоматическую проверку установки и запуска. Linux AppImage собран на Ubuntu 22.04 (x86_64, glibc 2.35) и прошёл проверку запуска на Ubuntu 22.04 и 24.04 на виртуальном экране Xvfb. Обновление поверх прежней установки и работу с физическим экраном для этих сборок не проверяли. Python и Node.js пользователю устанавливать не нужно; для подключения Git-репозиториев нужен Git.

Если `.exe` или `.AppImage` не запускается и вместо приложения скачался маленький текстовый файл, выполните `git lfs install` и `git lfs pull` из корня репозитория.

[Подробная установка и подключение проектов](../README.md#установка).
