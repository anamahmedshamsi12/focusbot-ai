"""
memory.py

Persistent memory for alfred.ai.

Stores and retrieves user data between sessions using a local JSON file.
Alfred can remember names, preferences, ongoing tasks, and anything
the user explicitly asks him to remember.
"""

import json
import os
from datetime import datetime


MEMORY_FILE = os.path.join(os.path.expanduser("~"), ".alfred_memory.json")

DEFAULT_MEMORY = {
    "name":        None,
    "preferences": {},
    "tasks":       [],
    "notes":       [],
    "created_at":  None,
    "updated_at":  None,
}


def load_memory() -> dict:
    """
    Load memory from disk.

    Returns default memory structure if no file exists yet.

    Returns:
        Dictionary containing all stored memory.
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
    Save memory to disk.

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
    Build a short summary of what Alfred remembers about the user.
    This is injected into the system prompt so Claude has context.

    Args:
        memory: The full memory dictionary.

    Returns:
        A plain text summary string, or empty string if nothing stored.
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
    Store the user's name in memory.

    Args:
        memory: The full memory dictionary.
        name:   The user's name.
    """
    memory["name"] = name.strip().title()
    save_memory(memory)


def add_task(memory: dict, task: str) -> None:
    """
    Add an ongoing task to memory.

    Args:
        memory: The full memory dictionary.
        task:   Task description string.
    """
    if task not in memory["tasks"]:
        memory["tasks"].append(task.strip())
        save_memory(memory)


def remove_task(memory: dict, task: str) -> None:
    """
    Remove a completed or cancelled task from memory.

    Args:
        memory: The full memory dictionary.
        task:   Task description string to remove.
    """
    memory["tasks"] = [t for t in memory["tasks"] if task.lower() not in t.lower()]
    save_memory(memory)


def add_note(memory: dict, note: str) -> None:
    """
    Store something the user explicitly asked Alfred to remember.

    Args:
        memory: The full memory dictionary.
        note:   The thing to remember.
    """
    if note not in memory["notes"]:
        memory["notes"].append(note.strip())
        save_memory(memory)


def clear_memory(memory: dict) -> None:
    """
    Wipe all stored memory and reset to defaults.

    Args:
        memory: The full memory dictionary (modified in place).
    """
    memory.update(DEFAULT_MEMORY.copy())
    memory["created_at"] = datetime.now().isoformat()
    save_memory(memory)
