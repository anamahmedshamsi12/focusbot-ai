"""
alfred.core.brain
-------------------
Alfred's mind: the Claude API integration and the persistent memory
that gives it continuity across sessions. These two live in one module
because every call to Claude injects a summary of what's in memory —
they're tightly coupled by design, not just by file convenience.

Two responsibilities live here:

1. Claude API integration — the two system prompt personalities
   (General assistant and ADHD Focus Mode) and `ask_alfred`, which
   sends a message plus running conversation history to Claude and
   returns the reply.
2. Persistent memory — `load_memory`/`save_memory` and friends read
   and write a small JSON file in the user's home directory so Alfred
   remembers the user's name, ongoing tasks, and explicit notes between
   runs of the program.
"""

import json
import os
from datetime import datetime

import anthropic

from alfred.config.settings import ANTHROPIC_API_KEY

# =============================================================================
# System Prompts
# =============================================================================

GENERAL_PROMPT: str = """
You are Alfred, a friendly and capable AI desktop assistant.
You can help with anything - questions, writing, coding, research, ideas, conversation, math, you name it.

Your personality:
- Warm, helpful, and direct
- Conversational - match the user's tone
- Honest and thoughtful
- Use a robot emoji occasionally but don't overdo it

Response style:
- Be concise but complete
- Use numbered or bulleted lists only when it genuinely helps
- Don't over-explain simple things
"""

FOCUS_MODE_PROMPT: str = """
You are Alfred in Focus Mode - an AI assistant tuned specifically for ADHD support.
Your job is task management, focus, and getting unstuck.

Your personality:
- Warm, non-judgmental, encouraging
- Short and to the point, never overwhelming
- Always give a concrete first step, never vague advice
- Gently honest when needed

Rules for your responses:
- Keep responses SHORT, max 6 lines
- Break tasks into 3-4 numbered steps max
- End task breakdowns with "I'll check in with you soon!"
- Never give more than one thing to focus on at a time

You help with:
1. TASK BREAKDOWN - break any task into tiny doable steps
2. REMINDERS - acknowledge and confirm reminder requests
3. FOCUS SESSIONS - start Pomodoro sessions with one clear goal
4. ROUTINES - guide through morning/evening routines step by step
5. GETTING UNSTUCK - when the user doesn't know where to start
"""


# =============================================================================
# Claude API
# =============================================================================

def create_client() -> anthropic.Anthropic:
    """
    Create and return an Anthropic API client.

    Returns:
        An Anthropic client configured with the API key from
        alfred.config.settings.
    """
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def ask_alfred(
    user_message: str,
    conversation_history: list[dict],
    client: anthropic.Anthropic,
    system_prompt: str,
    memory: dict | None = None,
) -> str:
    """
    Send a user message to the Claude API and return Alfred's reply.

    Injects a memory summary into the system prompt (when memory is
    provided and non-empty) so Claude has context about the user across
    sessions — their name, ongoing tasks, and anything they've explicitly
    asked Alfred to remember.

    Mutates `conversation_history` in place, appending both the user's
    message and Alfred's reply, so the caller's running history stays in
    sync without needing to manage it manually.

    Args:
        user_message: The raw text typed or spoken by the user.
        conversation_history: Running list of {"role", "content"} dicts;
            appended to in place.
        client: An initialized Anthropic API client.
        system_prompt: The active personality prompt (GENERAL_PROMPT or
            FOCUS_MODE_PROMPT).
        memory: Optional memory dictionary (see `load_memory`) to inject
            as context.

    Returns:
        Alfred's reply as a plain string, or a human-readable error
        message if the API call failed.
    """
    # Layer the memory summary on top of the base personality prompt
    # rather than replacing it, so tone/rules stay intact either way.
    active_prompt = system_prompt
    if memory:
        summary = get_memory_summary(memory)
        if summary:
            active_prompt = f"{system_prompt}\n\nWhat you remember about this user:\n{summary}"

    conversation_history.append({
        "role": "user",
        "content": user_message,
    })

    try:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=300,
            system=active_prompt,
            messages=conversation_history,
        )
        reply = response.content[0].text

        conversation_history.append({
            "role": "assistant",
            "content": reply,
        })

        return reply

    except anthropic.AuthenticationError:
        return "API key error. Please check ANTHROPIC_API_KEY in alfred/config/settings.py"
    except Exception as exc:
        return f"Error connecting to AI: {exc}"


# =============================================================================
# Persistent Memory
# =============================================================================

MEMORY_FILE: str = os.path.join(os.path.expanduser("~"), ".alfred_memory.json")

DEFAULT_MEMORY: dict = {
    "name": None,
    "preferences": {},
    "tasks": [],
    "notes": [],
    "created_at": None,
    "updated_at": None,
}


def load_memory() -> dict:
    """
    Load memory from disk.

    Returns the default memory structure if no memory file exists yet
    (e.g. first run on a new machine), or if the existing file can't be
    parsed.

    Returns:
        A dictionary containing all stored memory.
    """
    if not os.path.exists(MEMORY_FILE):
        memory = DEFAULT_MEMORY.copy()
        memory["created_at"] = datetime.now().isoformat()
        return memory

    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[Alfred] Could not load memory: {exc}")
        return DEFAULT_MEMORY.copy()


def save_memory(memory: dict) -> None:
    """
    Save memory to disk, stamping it with the current time.

    Args:
        memory: The full memory dictionary to persist.
    """
    try:
        memory["updated_at"] = datetime.now().isoformat()
        with open(MEMORY_FILE, "w") as f:
            json.dump(memory, f, indent=2)
    except Exception as exc:
        print(f"[Alfred] Could not save memory: {exc}")


def get_memory_summary(memory: dict) -> str:
    """
    Build a short plain-text summary of what Alfred remembers about the
    user, for injection into the Claude system prompt.

    Args:
        memory: The full memory dictionary.

    Returns:
        A multi-line summary string, or an empty string if nothing has
        been stored yet.
    """
    lines = []

    if memory.get("name"):
        lines.append(f"The user's name is {memory['name']}.")

    if memory.get("preferences"):
        prefs = ", ".join(f"{k}: {v}" for k, v in memory["preferences"].items())
        lines.append(f"User preferences: {prefs}.")

    if memory.get("tasks"):
        task_list = ", ".join(memory["tasks"])
        lines.append(f"Ongoing tasks the user has mentioned: {task_list}.")

    if memory.get("notes"):
        note_list = "; ".join(memory["notes"])
        lines.append(f"Things the user has asked Alfred to remember: {note_list}.")

    return "\n".join(lines)


def update_name(memory: dict, name: str) -> None:
    """
    Store the user's name in memory and persist immediately.

    Args:
        memory: The full memory dictionary (modified in place).
        name: The user's name, as spoken or typed.
    """
    memory["name"] = name.strip().title()
    save_memory(memory)


def add_task(memory: dict, task: str) -> None:
    """
    Add an ongoing task to memory and persist immediately, unless an
    identical task is already stored.

    Args:
        memory: The full memory dictionary (modified in place).
        task: Task description string.
    """
    if task not in memory["tasks"]:
        memory["tasks"].append(task.strip())
        save_memory(memory)


def remove_task(memory: dict, task: str) -> None:
    """
    Remove any stored task whose text contains the given substring, and
    persist immediately.

    Args:
        memory: The full memory dictionary (modified in place).
        task: Substring identifying the task(s) to remove (case-insensitive).
    """
    memory["tasks"] = [t for t in memory["tasks"] if task.lower() not in t.lower()]
    save_memory(memory)


def add_note(memory: dict, note: str) -> None:
    """
    Store something the user explicitly asked Alfred to remember, and
    persist immediately, unless an identical note is already stored.

    Args:
        memory: The full memory dictionary (modified in place).
        note: The text to remember.
    """
    if note not in memory["notes"]:
        memory["notes"].append(note.strip())
        save_memory(memory)


def clear_memory(memory: dict) -> None:
    """
    Wipe all stored memory and reset to the default structure in place.

    Args:
        memory: The full memory dictionary (modified in place).
    """
    memory.update(DEFAULT_MEMORY.copy())
    memory["created_at"] = datetime.now().isoformat()
    save_memory(memory)
