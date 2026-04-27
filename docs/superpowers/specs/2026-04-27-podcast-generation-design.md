# Podcast Generation — Personalized Audio Learning

## Goal

Students can generate personalized podcast-style audio lessons based on their current mastery state. The system creates a two-speaker conversational script from skill content, renders it to audio using Fish Audio S2's multi-speaker TTS, and serves it as a playable audio file in the chat UI.

## How It Works

1. Student says "Generate a podcast about what I'm working on" (or clicks a quick-action pill)
2. The tutor agent:
   - Checks the mastery map to identify concepts at emerging/proficient level
   - Retrieves skill content for those concepts
   - Generates a conversational podcast script (~5-10 minutes) tailored to the student's level
3. The system renders the script to audio using Fish Audio S2 (multi-speaker)
4. The audio file is served to the frontend as a playable element in the chat

## Podcast Script Format

The tutor generates a script with two speakers:
- **Host** — enthusiastic, asks questions, bridges between topics
- **Expert** — knowledgeable, explains concepts clearly, gives examples

The script is tailored to the student:
- Focuses on concepts they're currently learning (emerging/proficient)
- References what they already know (mastered concepts) as foundation
- Addresses common misconceptions from the skill content
- Uses teaching approaches from the learner profile

Example script:
```
HOST: Welcome back! Today we're diving into something really cool — list comprehensions in Python. If you've been working with for loops, this is going to feel like a superpower.

EXPERT: Exactly. Think of a list comprehension as a way to write a for loop and the list it creates all in one line. Let me give you a concrete example...

HOST: So if I wanted to create a list of squares, I'd normally write a for loop, right?

EXPERT: Right, you'd do something like squares = [], then for i in range(10), squares.append(i**2). But with a list comprehension, you can write that as squares = [i**2 for i in range(10)]. Same result, one line.
```

## Architecture

### New Components

**Podcast generation endpoint** — A new API route or an agent capability that:
1. Takes a list of concept IDs + student context
2. Generates the script via Claude
3. Calls Fish Audio S2 to render audio
4. Stores the audio file and returns a URL

**Audio file serving** — Static file serving for generated audio (or S3-like storage). For the prototype, store in a local directory mounted as a Docker volume.

### Flow

```
Student: "Make me a podcast"
  → Tutor agent identifies concepts
  → Claude generates podcast script
  → POST to /api/generate-podcast with script + voice config
  → Fish Audio S2 renders multi-speaker audio
  → Audio file saved to /audio/{id}.mp3
  → Chat response includes audio player: "Here's your podcast!"
```

### Implementation Options

**Option A: Agent generates script, separate endpoint renders audio**
- Tutor generates the script as a tool call
- New MCP tool `media.generate_podcast(script, concept_ids)` handles Fish Audio
- Returns audio URL that the frontend renders as a player
- Clean separation of concerns

**Option B: Dedicated podcast endpoint**
- `POST /api/generate-podcast` takes `{person_id, course_id, concepts[]}`
- Handles both script generation and audio rendering
- Returns audio URL
- Simpler but bypasses the agent architecture

**Recommendation: Option A** — keeps everything in the agent system. The tutor decides what to podcast about, generates the script, and calls a tool to render it.

## New MCP Server or Tool

Add to the content server (or create a new `media` server):

**`media.generate_podcast(script_md, title, voice_host, voice_expert)`**
- Takes the podcast script (markdown with HOST:/EXPERT: prefixes)
- Calls Fish Audio S2 API to render each speaker's lines
- Concatenates audio segments
- Saves to `/audio/` directory
- Returns `{audio_url, duration_seconds, title}`

## Frontend

### Audio Player in Chat

When the final response includes an `audio_url` artifact, render an HTML5 audio player:

```html
<audio controls src="/audio/podcast-abc123.mp3">
  Your browser does not support audio.
</audio>
```

Styled to match the chat UI — a card with:
- 🎧 Podcast title
- Play/pause button, progress bar, time
- "Generated for Emma · 8 min · Covers: lists, tuples, dictionaries"

### Quick Action Pill

Add to the student mastery panel:
- "🎧 Generate a podcast" → triggers podcast generation for current concepts

## Fish Audio S2 Integration

### SDK Usage

```python
from fish_audio_sdk import Session, TTSRequest

session = Session(api_key="...")

# Generate host audio
host_audio = session.tts(TTSRequest(
    text="Welcome back! Today we're diving into...",
    reference_id="host-voice-id",
))

# Generate expert audio  
expert_audio = session.tts(TTSRequest(
    text="Think of a list comprehension as...",
    reference_id="expert-voice-id",
))

# Concatenate segments in order
```

### Voice Selection

Pre-select two voices from Fish Audio's voice library:
- Host voice: warm, enthusiastic, conversational
- Expert voice: clear, authoritative, patient

Store voice reference IDs in config.

### Audio Assembly

Parse the script into segments by speaker, render each segment, concatenate with brief pauses between speakers. Output as MP3.

## Environment

- `FISH_AUDIO_API_KEY` — env var for Fish Audio API key
- Audio files stored in `/app/audio/` (Docker volume)
- Served via a static file route on the orchestrator

## Implementation Order

1. **Script generation** — Add podcast script generation capability to the tutor (prompt update + tool)
2. **Fish Audio integration** — New module that calls Fish Audio S2, handles multi-speaker rendering
3. **Audio serving** — Static file route on orchestrator for serving generated audio
4. **Frontend player** — Audio player component in chat UI
5. **Quick action** — "Generate a podcast" pill in mastery panel
6. **Test end-to-end** — Generate a real podcast, play it in the browser

## Not In Scope

- Video generation
- Podcast library/history (generated on demand, not saved permanently)
- Custom voice cloning (use pre-selected voices)
- Background music/sound effects
- Podcast RSS feed
- Mobile app audio playback
