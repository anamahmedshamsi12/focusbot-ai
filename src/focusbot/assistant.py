"""
assistant.py

Claude AI integration for alfred.ai.

Defines the two system prompt personalities (General and Focus Mode)
and the function that sends messages to the Claude API.
"""

import anthropic

from focusbot.config import ANTHROPIC_API_KEY


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


def create_client() -> anthropic.Anthropic:
    """
    Create and return an Anthropic API client.

    Returns:
        Configured Anthropic client using the API key from config.py.
    """
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def ask_alfred(
    user_message: str,
    conversation_history: list[dict],
    client: anthropic.Anthropic,
    system_prompt: str,
) -> str:
    """
    Send a user message to the Claude API and return Alfred's reply.

    Appends both the user message and the assistant reply to
    conversation_history so context is preserved across turns.

    Args:
        user_message: The raw text typed by the user.
        conversation_history: Running list of role/content dicts.
        client: Initialized Anthropic API client.
        system_prompt: Active personality prompt (General or Focus Mode).

    Returns:
        Alfred's reply as a plain string.
    """
    conversation_history.append({
        "role": "user",
        "content": user_message,
    })

    try:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=300,
            system=system_prompt,
            messages=conversation_history,
        )
        reply = response.content[0].text

        conversation_history.append({
            "role": "assistant",
            "content": reply,
        })

        return reply

    except anthropic.AuthenticationError:
        return "API key error. Please check ANTHROPIC_API_KEY in src/focusbot/config.py"
    except Exception as exc:
        return f"Error connecting to AI: {exc}"
        