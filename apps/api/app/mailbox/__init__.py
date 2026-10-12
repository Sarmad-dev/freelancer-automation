"""Mailbox connector framework (MVP Prompt 9). See docs/EMAIL.md.

Provider code (``gmail.py``, ``demo.py``) knows HTTP and mailbox formats. Domain code (``app.services.email_accounts``,
``app.services.drafts``) knows tenants, tokens, idempotency, suppression and audit, and talks to providers only through
the ``EmailConnector`` interface.
"""
