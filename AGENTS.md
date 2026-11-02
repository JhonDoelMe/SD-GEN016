# AGENTS.md

Дивіться повний опис архітектури, правил та стандартів розробки для ШІ-агентів у файлі [AGENT.md](./AGENT.md).

## Обов'язкове правило Git-пушу (Multi-Remote Push to `main`)
По завершенню будь-якої задачі **ЗАВЖДИ** комітьте зміни та пуште їх у гілку `main` у **всі три віддалені репозиторії**:
- `origin` (`git push origin HEAD:main`)
- `gitlab` (`git push gitlab HEAD:main`)
- `codeberg` (`git push codeberg HEAD:main`)
(а також синхронізуйте локальну гілку `main`).
