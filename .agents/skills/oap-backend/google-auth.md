# Authentication Rules

Before authentication changes:

1. Discover the current auth routes from the smallest authoritative source.
2. Discover the current signup, login, and consent flow.
3. Reuse the existing user creation and consent flow where applicable.
4. Prevent duplicate users and duplicate consent history.
5. Preserve the current refresh and session lifecycle unless the requested task requires changing it.
6. Verify only the auth paths affected by the task.
