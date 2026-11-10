"""Manual check: send one real message to the configured chat.

Needs a filled .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID), sent from the
supervisor's own Telegram account. Run from the repo root:

    python -m tests.manual_check_telegram
"""
from integrations import telegram


def main() -> None:
    if not telegram.is_configured():
        raise SystemExit(
            "Telegram is not configured: set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID in the .env file"
        )

    message_id = telegram.send_message(
        "GTM Tool: test de connexion.\n"
        "Si tu lis ce message, les notifications fonctionnent."
    )
    print("Sent, message id:", message_id)


if __name__ == "__main__":
    main()
