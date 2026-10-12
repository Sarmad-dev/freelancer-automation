"""AI service layer (MVP Prompt 8). See docs/AI.md.

Domain code talks to ``AiService`` only; vendors live behind ``providers``. Every call: validated typed input ->
versioned prompt -> provider (timeout, bounded retries) -> strict output validation -> metered, content-free log.
"""
