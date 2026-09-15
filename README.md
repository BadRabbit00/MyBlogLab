# MyBlogLab

[![CI](https://github.com/BadRabbit00/MyBlogLab/actions/workflows/ci.yml/badge.svg)](https://github.com/BadRabbit00/MyBlogLab/actions/workflows/ci.yml)

Telegram-бот для технического канала: генерирует посты через локальный llama-server,
учитывает материалы и историю канала, проверяет текст, отправляет черновики владельцу
на согласование и публикует их с обложкой.

## Возможности

- Контент-план в YAML, документы для контекста и повторная генерация по замечаниям.
- Проверка ответов: без китайских иероглифов, Markdown, XML/HTML и шаблонной разметки.
- Обложки из SVG, сгенерированная карточка или фотография владельца.
- Управление через `/start`, `/generate`, `/list`, `/review`, `/status`.
- Доступ к управлению только по разрешённым Telegram user ID и только в личном чате.
- Воспроизводимая Nix-сборка контейнера для **Linux amd64**.

Модель и её веса не входят в образ. Нужен отдельный llama-server с Gemma 4 и нативным
эндпоинтом `/completion`. Бот использует long polling: входящие порты открывать не нужно.
Даты контент-плана — метаданные; публикацию запускает владелец, встроенного таймера нет.

## Получить контейнер из GitHub

1. Открой [Actions → CI](https://github.com/BadRabbit00/MyBlogLab/actions/workflows/ci.yml).
2. Выбери успешный запуск для нужного коммита.
3. Скачай артефакт `blog-agent-linux-amd64-<commit SHA>` в разделе **Artifacts**.
4. Распакуй скачанный ZIP. Внутри будут архив образа и `SHA256SUMS`.

```sh
sha256sum -c SHA256SUMS
docker load --input blog-agent-linux-amd64.tar.gz
```

Имя загруженного образа: `blog-agent:latest`. Артефакты хранятся 30 дней.
Для загрузки артефактов через интерфейс GitHub нужна авторизация.

## Безопасный запуск через Docker Compose

Команды ниже рассчитаны на Linux, Docker Engine и Compose v2. Клонируй репозиторий:

```sh
git clone git@github.com:BadRabbit00/MyBlogLab.git
cd MyBlogLab
umask 077
mkdir -p secrets data
cp .env-example .env
```

Создай файл `secrets/telegram_bot_token` в редакторе и запиши туда **только токен**,
полученный от @BotFather, без кавычек и имени переменной. Не вставляй токен в команду
shell: она может попасть в историю. Файл `.env` содержит только настройки и путь к секрету.

```sh
${EDITOR:-vi} secrets/telegram_bot_token
${EDITOR:-vi} .env
sudo chown 10001:10001 data secrets/telegram_bot_token
sudo chmod 700 data
sudo chmod 400 secrets/telegram_bot_token
chmod 700 secrets
chmod 600 .env
```

В `.env` обязательно укажи свой **числовой Telegram user ID** в
`TELEGRAM_ALLOWED_USER_IDS`. Это ID пользователя, не username и не ID канала.
Для нескольких владельцев перечисли ID через запятую. Пустой или некорректный список
блокирует запуск бота. Групповые чаты не допускаются даже для владельцев.

### Настройки

| Переменная | Назначение |
| --- | --- |
| `TELEGRAM_BOT_TOKEN_FILE` | Путь к файлу токена в контейнере: `/run/secrets/telegram_bot_token` |
| `TELEGRAM_ALLOWED_USER_IDS` | Обязательный список владельцев, например `123456789,987654321` |
| `LLM_ENDPOINT` | Полный URL llama-server, по умолчанию в примере `http://host.docker.internal:8080/completion` |
| `BLOG_DATA_DIR` | Каталог изменяемых данных; для Compose оставь `/data` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` или `ERROR`; по умолчанию `INFO` |

При прямом запуске Python без контейнера адрес LLM по умолчанию —
`http://127.0.0.1:8080/completion`, данные хранятся в каталоге проекта.
Переменные `TELEGRAM_BOT_TOKEN`/`BOT_TOKEN` оставлены для совместимости с локальным
запуском; в предлагаемой конфигурации Compose используется файловый секрет.

### Соединение с LLM

`127.0.0.1` внутри контейнера указывает на сам контейнер. Compose добавляет имя
`host.docker.internal` для обращения к Docker-хосту. llama-server должен слушать
интерфейс, доступный из Docker bridge; сервер, слушающий только host loopback,
через это имя недоступен. Ограничь доступ к порту LLM локальной сетью Docker,
не публикуй незащищённый llama-server в интернет. Для отдельного LLM-сервиса
укажи его внутренний адрес в `LLM_ENDPOINT`.

### Первый запуск и канал

Инициализируй каталог данных без запуска Telegram-бота:

```sh
docker compose run --rm bot python3 -m src.cli status
sudo ${EDITOR:-vi} data/content-plan.yaml
```

Укажи в `meta.channel` адрес канала (`@channel_name`) или числовой ID. Добавь бота
в канал администратором с правом публикации. Скорректируй темы и даты в плане.
Новый каталог получает минимальный [пример плана](examples/content-plan.yaml);
корневой `content-plan.yaml` содержит расширенный исходный план проекта, который
можно перенести вручную. При таком переносе поставь `pending` постам, для которых
ещё нет файлов черновиков.

```sh
docker compose up -d
docker compose logs -f bot
```

Открой личный чат с ботом и отправь `/start`. Одобри черновик, затем выбери обложку
или отправь фотографию. Проверка формата повторяется непосредственно перед публикацией.

Токен монтируется Compose как read-only secret. В образе и переменных окружения
контейнера его нет. Процесс работает под UID/GID `10001:10001`, корневая файловая
система read-only, capabilities удалены, повышение привилегий запрещено. Запись
разрешена в `/data` и временный `/tmp`. Администратор Docker-хоста всё равно имеет
доступ к файлу секрета: Compose secrets не заменяет защиту самого хоста.
Токены Telegram маскируются в логах приложения и сообщениях об ошибках публикации.

## Запуск без Compose

После подготовки файлов и прав из предыдущего раздела:

```sh
docker run -d --name mybloglab --restart unless-stopped --init \
  --user 10001:10001 --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env-file .env \
  --add-host host.docker.internal:host-gateway \
  --mount type=bind,src="$PWD/data",dst=/data \
  --mount type=bind,src="$PWD/secrets/telegram_bot_token",dst=/run/secrets/telegram_bot_token,readonly \
  blog-agent:latest
```

## Данные, обновление и ротация токена

В `data/` сохраняются план, документы, черновики, обложки и журналы. Контейнер
инициализирует отсутствующие файлы и не перезаписывает существующий план.
Сделай резервную копию этого каталога перед обновлением.

```sh
docker compose down
docker load --input blog-agent-linux-amd64.tar.gz
docker compose up -d
```

Для ротации останови контейнер, замени токен в файле через `sudo`-редактор,
сохрани владельца `10001:10001` и права `0400`, затем выполни
`docker compose up -d --force-recreate`. Старый токен отзови в @BotFather.
Файлы `.env`, `secrets/`, `data/` и журналы исключены из Git.

## Разработка и локальная сборка

Требуется Nix с включёнными flakes и nix-command. Зависимости закреплены в `flake.lock`.

```sh
nix develop
python -m pytest -q
python -m src.cli --help
```

Без интерактивной оболочки:

```sh
nix develop . --command python -m pytest -q
nix build .#container --out-link result-container
docker load --input result-container
bash scripts/smoke-container.sh
```

Сборка не использует `.env`, secret-файлы, Git-историю и локальные данные: Nix
включает явно перечисленные исходники и ресурсы. CLI доступен и в контейнере:

```sh
docker compose run --rm bot python3 -m src.cli status
docker compose run --rm bot python3 -m src.cli draft --id demo-01
docker compose run --rm bot python3 -m src.cli review
```

Не запускай параллельно несколько процессов, меняющих один и тот же контент-план.
Для локального бота экспортируй `TELEGRAM_ALLOWED_USER_IDS` и
`TELEGRAM_BOT_TOKEN_FILE`, затем запусти `python -m src.bot`.

## CI/CD

[Workflow](.github/workflows/ci.yml) запускается при push в `main`, тегах `v*`,
pull request и вручную. Он выполняет тесты, собирает Nix-образ, загружает его в Docker,
проверяет запуск и генерацию карточки без сети, затем сохраняет образ и SHA-256
как [GitHub Actions artifact](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts).
Actions закреплены по commit SHA; Dependabot предлагает обновления.
Секреты Telegram для CI не нужны. Доставка выполняется через скачивание артефакта;
автоматического развёртывания на сервере нет.

## Структура

```text
src/             бот, генерация, проверка, публикация, работа с планом
tests/           тесты с имитацией LLM и Telegram
prompts/         инструкции для генерации и доработки
templates/       SVG-шаблон обложки
examples/        стартовый контент-план контейнера
docs/            документация и исходные материалы
scripts/         проверка собранного контейнера
.github/         CI и обновления Actions
```

Подробности проверки текста: [docs/VALIDATION.md](docs/VALIDATION.md).
Для локального графа проекта: `graphify update .`.
