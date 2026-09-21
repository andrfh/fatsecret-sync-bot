# Безопасное обновление VPS

Инструкция рассчитана на подтверждённую конфигурацию из `.github/workflows/deploy.yml`:
репозиторий `/home/deploy/apps/fatsecret-sync-bot`, виртуальное окружение `.venv` и
systemd-unit `fatsecret-bot.service`. Если фактический unit или путь отличаются,
сначала подставьте реальные значения в `APP_DIR` и `SERVICE`.

## 1. Предварительная проверка

```bash
APP_DIR=/home/deploy/apps/fatsecret-sync-bot
SERVICE=fatsecret-bot.service
cd "$APP_DIR"

git status --short
git rev-parse HEAD
.venv/bin/python --version
.venv/bin/python -m pip check
df -h "$APP_DIR"
test -f .env
test -f data/app.db
stat -c '%a %U:%G %n' .env data data/app.db
systemctl cat "$SERVICE"
systemctl is-active "$SERVICE"
```

Ожидаются: чистые tracked-файлы, поддерживаемая проектом версия Python,
успешный `pip check`, достаточное место, `.env` с режимом `600`, каталог `data`
с режимом `700` и `data/app.db` с режимом `600`. Исправлять владельца и права
следует от имени администратора VPS; значения секретов выводить не нужно.

## 2. Резервная копия без Git

Создайте каталог вне репозитория. SQLite `.backup` делает согласованный снимок
работающей БД; конфигурация копируется с закрытыми правами.

```bash
BACKUP_DIR="$HOME/fatsecret-backups/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$BACKUP_DIR"
sqlite3 "$APP_DIR/data/app.db" ".backup '$BACKUP_DIR/app.db'"
install -m 600 "$APP_DIR/.env" "$BACKUP_DIR/.env"
git -C "$APP_DIR" rev-parse HEAD > "$BACKUP_DIR/git-revision.txt"
sqlite3 "$BACKUP_DIR/app.db" 'PRAGMA integrity_check;'
```

Результат `integrity_check` должен быть `ok`. Не добавляйте каталог резервных
копий в Git и не прикладывайте `.env` или БД к отчётам.

## 3. Репетиция миграции на копии

```bash
MIGRATION_DB="$BACKUP_DIR/migration-test.db"
cp "$BACKUP_DIR/app.db" "$MIGRATION_DB"
chmod 600 "$MIGRATION_DB"
MIGRATION_DB="$MIGRATION_DB" .venv/bin/python - <<'PY'
import os
import sqlite3
from pathlib import Path
from database import init_db

path = Path(os.environ['MIGRATION_DB'])
with sqlite3.connect(path) as db:
    before = db.execute(
        'SELECT telegram_id, language, fatsecret_token, fatsecret_token_secret, '
        'fatsecret_connected_at FROM users ORDER BY telegram_id'
    ).fetchall()

init_db.DB_PATH = path
init_db.init_db()

with sqlite3.connect(path) as db:
    after = db.execute(
        'SELECT telegram_id, language, fatsecret_token, fatsecret_token_secret, '
        'fatsecret_connected_at FROM users ORDER BY telegram_id'
    ).fetchall()
    assert before == after, 'existing users or OAuth credentials changed'
    assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    assert db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='meal_write_operations'"
    ).fetchone() == (1,)
print('Migration copy verified; existing credentials unchanged')
PY
```

Скрипт сравнивает значения в памяти и не печатает токены.

## 4. Проверка версии и остановка старого процесса

```bash
cd "$APP_DIR"
git fetch origin main
git log --oneline --decorate -5 origin/main
sudo -n systemctl stop "$SERVICE"
systemctl is-active "$SERVICE" || true
```

Перед продолжением процесс должен быть неактивен. Это исключает одновременную
работу двух экземпляров с одной SQLite-БД.

## 5. Обновление и локальная проверка

```bash
git checkout main
git merge --ff-only origin/main
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests
```

Тесты используют синтетические данные и моки. Они не должны обращаться к
Gemini, FatSecret, Telegram или рабочей БД. Не запускайте `app.py` как проверку:
это подключит polling к Telegram.

## 6. Контролируемый запуск

```bash
sudo -n systemctl start "$SERVICE"
systemctl is-active "$SERVICE"
journalctl -u "$SERVICE" --since '5 minutes ago' --no-pager
```

Проверьте отсутствие циклов рестарта, ошибок миграции и сообщений с ключами,
OAuth-параметрами или пользовательским текстом. Первый ручной внешний тест
выполняйте только после снятия перечисленных в отчёте блокеров.

## 7. Откат

Сначала остановите сервис. Для обычного отката верните только код к записанному
commit: добавленные таблица и столбцы совместимы со старым кодом и могут остаться.

```bash
sudo -n systemctl stop "$SERVICE"
PREVIOUS_REVISION=$(cat "$BACKUP_DIR/git-revision.txt")
git checkout --detach "$PREVIOUS_REVISION"
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
sudo -n systemctl start "$SERVICE"
systemctl is-active "$SERVICE"
```

Не восстанавливайте старую БД автоматически: это удалит пользователей, токены и
изменения, появившиеся после резервной копии. Восстановление БД допустимо только
при остановленном сервисе, после отдельного решения о допустимости такой потери
данных и с сохранением текущей БД ещё одной копией.
