# Changes Summary

## Fixed Issues

### 1. User Identity System
**Problem**: When user "a" joined, they saw "user_xxx" and then a duplicate "a" appeared saying the same thing.

**Solution**:
- User now enters their unique participant ID on `/join` page first
- Backend assigns preset name (e.g., "a", "b", "c") based on session config
- WebSocket sends `display_name` message to client on connect
- Client renders own messages using display name, not uid
- Messages are NOT broadcast back to sender's own WebSocket (prevents duplicate)
- Team members list shows "a (you)" to indicate current user

### 2. Join Flow
**New page**: `/join?session_id=XXX&group_id=YYY`
- Shows assigned name before joining
- User enters their unique participant ID
- Redirects to chat with proper identity

### 3. Typing Indicators Removed
- All typing indicators disabled (no "typing..." shown for anyone)
- Bot messages appear instantly without typing animation
- Cleaner, faster chat experience

### 4. Session Mode Clarifications
**Mode 1** — All bots respond independently
- Every bot analyzes full chat context and decides what to say
- All bots respond to every human message
- Best for simulating multiple independent AI perspectives

**Mode 2** — All bots with jitter
- Same as Mode 1, but adds random delay (0.5-2.5s)
- More natural timing, less synchronized

**Mode 3** — Sequential after ANY message
- Every bot responds in sequence after ANY message (human OR bot)
- Creates continuous conversation flow
- Good for structured multi-bot experiments where bots build on each other

**Mode 4** — Turn-taking (human only)
- Every bot responds in sequence only after human messages
- Bots do not respond to other bots
- Good for controlled experiments with clear human-bot turns

### 5. Dashboard Enhancements
**New Session Management Tab**:
- View all sessions
- Delete sessions (removes session config + all associated rooms)

**Room Management**:
- View, Pause, Delete rooms
- Pause prevents new messages from being processed

### 6. Avatar Type Selection
In Admin → each bot persona card:
- Dropdown: "Bot Avatar" or "Human Avatar"
- "Human Avatar" removes purple bot-style label in chat
- Bot appears indistinguishable from human participant

## How to Use

### For Participants:
1. Admin creates session in `/admin` with participant names (e.g., "a", "b", "c")
2. Admin shares join link: `http://localhost:8000/join?session_id=SES-XXX&group_id=GRP-YYY`
3. Participant opens link, sees assigned name, enters their unique ID
4. Participant joins chat as their assigned name

### For Admins:
- Login: username `ACTR2026`, password `ACTR2026`
- Create sessions with specific participant names
- Choose session mode based on experiment needs
- Monitor rooms in Dashboard
- Delete sessions/rooms as needed

## Technical Details

### WebSocket Protocol
- Client sends `{type: "get_display_name"}` on connect
- Server responds with `{type: "display_name", name: "a"}`
- Plain text messages = chat messages
- Messages only broadcast to OTHER connections (not sender)

### Session Modes Implementation
- Mode 1: All bots enqueue independently
- Mode 2: All bots enqueue with `mode=2` flag (adds jitter in handler)
- Mode 3: All bots respond after ANY message (triggers on human AND bot messages)
- Mode 4: All bots respond only after human messages

### Pause Room
- Sets `group_info["paused"] = True`
- `process_ai_logic` checks pause flag and returns early
- Humans can still type, but no AI processing occurs
