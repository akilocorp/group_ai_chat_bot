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

## Qualtrics: what is `postMessage`?

Your chat runs **inside an iframe** on a Qualtrics page. The iframe cannot call Qualtrics APIs directly. Instead, when chat ends it sends a message **up** to the parent page:

```javascript
window.parent.postMessage({ source: 'ACTR_CHAT', event: 'chat_ended', ... }, '*');
```

The **parent survey page** must listen and then:
1. **Push** data into Qualtrics Embedded Data (`setEmbeddedData`)
2. **Pull** is only needed if you did not include the transcript in the message — then the parent calls your server API

### Push (iframe → Qualtrics) — recommended

1. In **Admin**, enable:
   - **Qualtrics integration** — saves transcript to Embedded Data and auto-advances when chat ends
2. In Qualtrics, create Embedded Data field (e.g. `transcript`).
3. Add the parent listener script from `static/qualtrics-parent-snippet.js` to your survey (HTML question or Survey Flow JavaScript).

### Pull (Qualtrics / researcher → server)

Use when you need the transcript later (piped text, offline analysis, or web service):

```
GET /api/export/participant/{session_id}/{participant_id}
```

Returns `transcript_text`, `messages[]`, `group_id`, `display_name`.

Example Qualtrics **Web Service** at end of survey: call this URL with `${e://Field/session_id}` and `${e://Field/ResponseID}`.

You do **not** need both push and pull for every study — push is enough for storing chat inside Qualtrics; pull is for server-side archives and Dashboard export.

---

## Embed URL parameters

| Param | Qualtrics example | Purpose |
|-------|-------------------|---------|
| `session_id` | `${e://Field/session_id}` | Experiment config |
| `participant_id` | `${e://Field/ResponseID}` | Unique participant key |
| `condition` | `${e://Field/condition}` | Optional per-participant roster labels and stratified queues |
| `group_id` | fixed `GRP-XXXX` | Skip queue, join fixed room |

```html
<iframe
  src="https://YOUR-SERVER/embed.html?session_id=${e://Field/session_id}&participant_id=${e://Field/ResponseID}&condition=${e://Field/condition}"
  width="100%" height="600" style="border:none;"></iframe>
```

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
| `MONGO_URL` | Optional MongoDB |
