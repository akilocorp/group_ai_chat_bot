# Group AI Chat Bot (ACTR)

Research platform for group chat experiments with configurable AI personas, multi-session management, and **Qualtrics embedding**.

## Quick start

```bash
pip install -r requirements.txt
# Set OPENAI_API_KEY in .env
python main.py
```

- **Admin:** http://localhost:8000/admin
- **Dashboard:** http://localhost:8000/dashboard
- **Qualtrics participant chat:** http://localhost:8000/embed.html

---

## Qualtrics (3 steps)

1. **Admin** — create session, enable **Qualtrics integration**, copy the HTML block from the setup guide.
2. **Survey Flow → Embedded Data** — add `transcript`, `chat_status`, and `condition` (if you use conditions).
3. **Chat question → HTML** — paste the block (includes `qualtrics-parent-snippet.js` + iframe). Use your live server (e.g. `https://group.xjhuang.com`).

Preview until the chat header shows **Connected**. After the session, see **Data & Analysis** for `transcript` and `chat_status` (`completed_full`, `left_early`, `no_messages`, `never_joined`). Or use **Dashboard → Export**.

---

## Admin experiment options

| Option | Values | Use |
|--------|--------|-----|
| **Assignment** | FIFO / Stratified | FIFO = first-come matching; Stratified = separate waiting list per `condition` value |
| **Speaking turns** | Off / Round-robin / Timed | Controls which human may send |
| **AI starts conversation** | On / Off | First bot sends opening message when room is empty |
| **Qualtrics integration** | On / Off | Transcript to Embedded Data + auto-advance via parent script |

---

## Session modes (AI orchestration)

| Mode | Behavior |
|------|----------|
| 1 | All bots may reply |
| 2 | Intent router picks one bot |
| 3 | Only bots @mentioned or named in text |

Bot **timing** modes (per bot card) control delay/skip — separate from session mode.

---

## Architecture

- **Sessions** (`SES-*`): `config/sessions.json`
- **Groups** (`GRP-*`): many per session, same config
- **Participant index**: `config/participant_index.json` (uid → group for export)
- **Messages**: `db/local_db.json` or MongoDB

## Environment

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Required for bot replies |
| `OPENAI_CHAT_MODEL` | Default if persona has no model: `gpt-5.5`, `gpt-5`, or `gpt-4o` |
| `OPENAI_AUX_MODEL` | Orchestrator / scoring calls (default `gpt-5-mini`) |

Per-persona **GPT model** is set in Admin (dropdown: GPT-5.5 / GPT-5 / GPT-4o). Example preset uses **gpt-5** for both a and b.
| `MONGO_URL` | Optional MongoDB |
