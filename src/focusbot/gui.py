"""
gui.py
------
Tkinter GUI for FocusBot.

FocusBotApp is the main application window. It wires together the
assistant, reminders, and voice modules into a single chat interface
with a mode toggle, quick-action buttons, and a live status bar.
"""

import threading
import tkinter as tk
from tkinter import scrolledtext

import pyttsx3

from focusbot.assistant import (
    FOCUS_MODE_PROMPT,
    GENERAL_PROMPT,
    ask_focusbot,
    create_client,
)
from focusbot.config import FOCUS_MINUTES
from focusbot.reminders import (
    detect_intent,
    parse_reminder,
    set_reminder,
    start_focus_timer,
)
from focusbot.voice import init_tts, speak


class FocusBotApp:
    """
    Main application window for FocusBot.

    Responsibilities:
    - Build and manage all tkinter widgets
    - Route user messages to the correct handler (AI, timer, reminder)
    - Provide thread-safe display_message and update_status callbacks
      used by reminders.py and other background threads
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("🤖 FocusBot — AI Assistant")
        self.root.geometry("600x700")
        self.root.configure(bg="#1a1a2e")
        self.root.resizable(True, True)

        # ── State ──────────────────────────────────────────────────────────
        self.conversation_history: list[dict] = []
        self.focus_active: bool = False
        self.focus_mode: bool = False          # False = General, True = ADHD Focus

        # ── External dependencies ──────────────────────────────────────────
        self.tts_engine: pyttsx3.Engine | None = init_tts()
        self.client = create_client()

        # ── Build UI and greet the user ────────────────────────────────────
        self._build_ui()
        self._welcome()

    # ── UI Construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Construct all tkinter widgets and lay them out."""
        self._build_title_bar()
        self._build_quick_buttons()
        self._build_chat_display()
        self._build_input_area()
        self._build_status_bar()

    def _build_title_bar(self) -> None:
        frame = tk.Frame(self.root, bg="#16213e", pady=10)
        frame.pack(fill="x")

        tk.Label(
            frame, text="🤖  FocusBot",
            font=("Helvetica", 20, "bold"),
            bg="#16213e", fg="#00d4ff",
        ).pack(side="left", padx=20)

        tk.Label(
            frame, text="AI Assistant",
            font=("Helvetica", 11),
            bg="#16213e", fg="#888888",
        ).pack(side="left")

        # Mode toggle — top right corner
        self.mode_btn = tk.Button(
            frame,
            text="🧠 Focus Mode: OFF",
            command=self._toggle_mode,
            bg="#0f3460", fg="#888888",
            font=("Helvetica", 10),
            relief="flat", padx=12, pady=4, cursor="hand2",
        )
        self.mode_btn.pack(side="right", padx=15)

    def _build_quick_buttons(self) -> None:
        frame = tk.Frame(self.root, bg="#1a1a2e", pady=8)
        frame.pack(fill="x", padx=15)

        buttons = [
            ("🎯 Focus 25min", self._quick_focus),
            ("📋 Breakdown",   self._quick_breakdown),
            ("☀️ Routine",     self._quick_routine),
            ("⏹ Stop Timer",   self._stop_focus),
        ]
        for label, cmd in buttons:
            tk.Button(
                frame, text=label, command=cmd,
                bg="#0f3460", fg="white",
                font=("Helvetica", 10),
                relief="flat", padx=10, pady=5, cursor="hand2",
                activebackground="#e94560", activeforeground="white",
            ).pack(side="left", padx=4)

    def _build_chat_display(self) -> None:
        frame = tk.Frame(self.root, bg="#1a1a2e")
        frame.pack(fill="both", expand=True, padx=15, pady=(0, 5))

        self.chat_display = scrolledtext.ScrolledText(
            frame,
            wrap=tk.WORD,
            bg="#0d0d1a", fg="#e0e0e0",
            font=("Helvetica", 12),
            relief="flat", padx=12, pady=10,
            state="disabled", insertbackground="white",
        )
        self.chat_display.pack(fill="both", expand=True)

        # Colour tags for different message types
        self.chat_display.tag_configure("bot_name",  foreground="#00d4ff", font=("Helvetica", 12, "bold"))
        self.chat_display.tag_configure("bot_text",  foreground="#e0e0e0", font=("Helvetica", 12))
        self.chat_display.tag_configure("user_name", foreground="#ff6b9d", font=("Helvetica", 12, "bold"))
        self.chat_display.tag_configure("user_text", foreground="#cccccc", font=("Helvetica", 12))
        self.chat_display.tag_configure("system",    foreground="#888888", font=("Helvetica", 10, "italic"))

    def _build_input_area(self) -> None:
        frame = tk.Frame(self.root, bg="#16213e", pady=10)
        frame.pack(fill="x", padx=15, pady=(0, 5))

        self.input_field = tk.Entry(
            frame,
            bg="#0d0d1a", fg="white",
            font=("Helvetica", 13),
            relief="flat", insertbackground="white",
        )
        self.input_field.pack(side="left", fill="x", expand=True, ipady=10, padx=(0, 8))
        self.input_field.bind("<Return>", self._on_send)
        self.input_field.focus()

        tk.Button(
            frame, text="Send ➤",
            command=self._on_send,
            bg="#e94560", fg="white",
            font=("Helvetica", 12, "bold"),
            relief="flat", padx=16, pady=8, cursor="hand2",
        ).pack(side="right")

    def _build_status_bar(self) -> None:
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(
            self.root,
            textvariable=self.status_var,
            bg="#0d0d1a", fg="#555555",
            font=("Helvetica", 10),
            anchor="w", padx=10,
        ).pack(fill="x")

    # ── Thread-safe UI Callbacks ───────────────────────────────────────────

    def display_message(self, sender: str, message: str) -> None:
        """
        Append a message to the chat display.
        Safe to call from any thread — uses root.after() to schedule
        the update on the main tkinter thread.

        Args:
            sender:  'FocusBot', 'You', or anything else (shown as system text).
            message: The message body to display.
        """
        def _update() -> None:
            self.chat_display.configure(state="normal")
            if sender == "FocusBot":
                self.chat_display.insert("end", "\nFocusBot  ", "bot_name")
                self.chat_display.insert("end", f"\n{message}\n", "bot_text")
            elif sender == "You":
                self.chat_display.insert("end", "\nYou  ", "user_name")
                self.chat_display.insert("end", f"\n{message}\n", "user_text")
            else:
                self.chat_display.insert("end", f"\n{message}\n", "system")
            self.chat_display.configure(state="disabled")
            self.chat_display.see("end")

        self.root.after(0, _update)

    def update_status(self, text: str) -> None:
        """
        Update the status bar text.
        Safe to call from any thread.

        Args:
            text: Status string to display.
        """
        self.root.after(0, lambda: self.status_var.set(text))

    # ── Message Routing ────────────────────────────────────────────────────

    def _on_send(self, event: tk.Event | None = None) -> None:
        """Called when the user presses Enter or clicks Send."""
        text = self.input_field.get().strip()
        if not text:
            return
        self.input_field.delete(0, tk.END)
        self.display_message("You", text)
        threading.Thread(target=self._process_message, args=(text,), daemon=True).start()

    def _process_message(self, text: str) -> None:
        """
        Route a user message to the correct handler based on detected intent.
        Runs in a background thread to keep the UI responsive.

        Args:
            text: The user's raw input string.
        """
        self.update_status("FocusBot is thinking...")
        intent = detect_intent(text)

        if intent == "stop":
            self.focus_active = False
            self.display_message("FocusBot", "⏹ Focus session stopped. Good effort!")
            speak("Focus session stopped. Good effort!", self.tts_engine)
            self.update_status("Ready")

        elif intent == "focus":
            reply = ask_focusbot(text, self.conversation_history, self.client, self._active_prompt())
            self.display_message("FocusBot", reply)
            speak(reply, self.tts_engine)
            start_focus_timer(FOCUS_MINUTES, self)

        elif intent == "reminder":
            minutes = parse_reminder(text)
            reply = ask_focusbot(text, self.conversation_history, self.client, self._active_prompt())
            self.display_message("FocusBot", reply)
            speak(reply, self.tts_engine)
            if minutes:
                set_reminder(minutes, text, self)
                self.display_message("System", f"⏰ Reminder set for {minutes} minutes from now.")
            else:
                self.display_message("System", "⚠️ Couldn't find a time. Try: 'Remind me in 20 minutes to...'")
            self.update_status("Ready")

        else:
            # General chat, task breakdown, routine — all handled by Claude
            reply = ask_focusbot(text, self.conversation_history, self.client, self._active_prompt())
            self.display_message("FocusBot", reply)
            speak(reply, self.tts_engine)
            self.update_status("Ready")

    # ── Mode Toggle ────────────────────────────────────────────────────────

    def _toggle_mode(self) -> None:
        """
        Switch between General Mode and ADHD Focus Mode.
        Clears conversation history on switch so the AI isn't confused.
        """
        self.focus_mode = not self.focus_mode
        self.conversation_history = []

        if self.focus_mode:
            self.mode_btn.config(text="🧠 Focus Mode: ON", fg="#00d4ff")
            self.display_message("System", "── Switched to ADHD Focus Mode. Conversation reset. ──")
            self.display_message("FocusBot", "Focus Mode on 🤖 I'll keep things short and break tasks down. What are we working on?")
        else:
            self.mode_btn.config(text="🧠 Focus Mode: OFF", fg="#888888")
            self.display_message("System", "── Switched to General Mode. Conversation reset. ──")
            self.display_message("FocusBot", "General mode on 🤖 I can help with anything now — what's on your mind?")

    def _active_prompt(self) -> str:
        """Return the system prompt for whichever mode is currently active."""
        return FOCUS_MODE_PROMPT if self.focus_mode else GENERAL_PROMPT

    # ── Quick Action Buttons ───────────────────────────────────────────────

    def _quick_focus(self) -> None:
        self.input_field.delete(0, tk.END)
        self.input_field.insert(0, "Start a 25-minute focus session")
        self._on_send()

    def _quick_breakdown(self) -> None:
        self.input_field.delete(0, tk.END)
        self.input_field.insert(0, "I need help breaking down a task")
        self._on_send()

    def _quick_routine(self) -> None:
        self.input_field.delete(0, tk.END)
        self.input_field.insert(0, "Help me with my morning routine")
        self._on_send()

    def _stop_focus(self) -> None:
        self.focus_active = False
        self.update_status("Ready")
        self.display_message("FocusBot", "⏹ Timer stopped. That's okay — every minute counts!")

    # ── Welcome Message ────────────────────────────────────────────────────

    def _welcome(self) -> None:
        """Display and speak the initial greeting when the app launches."""
        message = (
            "Hey! I'm FocusBot 🤖  Your AI desk assistant.\n\n"
            "I can help with pretty much anything — questions, tasks,\n"
            "writing, ideas, or just a chat.\n\n"
            "Need ADHD focus support? Hit the 🧠 Focus Mode button\n"
            "in the top right to switch modes anytime.\n\n"
            "What can I help you with?"
        )
        self.display_message("FocusBot", message)
        speak("Hey! I'm FocusBot. What can I help you with today?", self.tts_engine)
