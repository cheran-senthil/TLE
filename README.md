# TLE ― The Competitive-Programming Discord Bot

TLE is a feature-packed Discord bot aimed at competitive programmers.
It can recommend problems, show stats & graphs, run duels on your server
and manage starboards – all with a single prefix `;`.

If you have Docker ≥ 24 (or Docker Desktop on Win/Mac) you are ready to
go.

---

## 1 · Features (quick glance)

| Cog | What it does |
|-----|--------------|
| **Codeforces** | problem / contest recommender, rating changes, user look-ups |
| **Contests** | shows upcoming & live contests |
| **Graphs** | rating distributions, solved-set histograms, etc. |
| **Handles** | link Discord users to CF handles |
| **Starboard** | pins popular messages to a channel |
| **CacheControl** | warm-up & manage local caches |

All graphs require cairo + pango; the Docker image already contains
everything.

---

## 2 · Quick start (production)

```bash
# 1 · clone the repo
git clone https://github.com/cheran-senthil/TLE
cd TLE

# 2 · create a config file
cp .env.example .env          # then edit BOT_TOKEN, LOGGING_COG_CHANNEL_ID …

# 3 · create the data directory and start the bot (first run takes ~2 min)
mkdir -p data
docker compose up -d
```

That’s it.  
The bot will appear online in your Discord server; use
`;help` inside Discord to explore commands.

### Updating to a new release

```sh
git pull
docker compose build --pull    # fetch newer base images
docker compose up -d           # zero-downtime restart
```

---

## 3 · Environment variables ( `.env` )

| Variable | Required | Example | Description |
|----------|----------|---------|-------------|
| `BOT_TOKEN` | ✅ | `MTEz…` | Discord bot token from the Dev Portal |
| `LOGGING_COG_CHANNEL_ID` | ✅ | `123456789012345678` | channel where uncaught errors are sent |
| `ALLOW_DUEL_SELF_REGISTER` | ❌ | `true` | let users self-register for duels |
| `TLE_ADMIN` | ❌ | `Admin` | role name that can run admin cmds |
| `TLE_MODERATOR` | ❌ | `Moderator` | role name that can run mod cmds |

Feel free to add any extra variables your cogs consume; Compose passes
every key in `.env` to the container.

---

## 4 · Data & cache folder

`docker compose` mounts `./data` into the container.  
It holds:

* Codeforces caches & contest writers JSON  
* downloaded CJK fonts (~36 MB, fetched automatically)  

You can back this directory up or move it to a dedicated volume; wiping
it only means the bot will re-download items on first run.

---

## 5 · Local development (optional)

You can hack on the code without touching your system Python:

```bash
# live-reload dev run (blocks & shows logs)
docker compose up --build
```

Lint & format (Ruff):

```bash
docker run --rm -v $PWD:/app -w /app python:3.11-slim \
       sh -c "pip install ruff && ruff check . && ruff format --check ."
```

---

## 6 · Repository layout

```sh
.
├─ Dockerfile              # 2-stage image, installs native cairo stack
├─ compose.yaml            # single-service compose file
├─ requirements.txt        # runtime Python deps (no pins)
├─ .env.example            # template for your secrets
├─ data/                   # persisted cache & fonts (git-ignored)
├─ tle/ …                  # bot source code
└─ extra/ fonts.conf …     # helper resources
```

---

## 7 · Contributing

Pull requests are welcome!  
Before opening a PR, please

1. run `ruff check --fix .` (auto-formats touched lines),
2. keep commits focused; large refactors in a separate PR.

---

## 8 · License

MIT ― see `LICENSE`.
