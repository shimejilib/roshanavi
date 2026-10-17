"""Launch-file decomposition import (DESIGN §4.16).

``child`` / ``walker`` / ``extract`` run in a separate, time-limited process
(they import and evaluate the user's launch file). ``runner`` / ``plan`` /
``params_merge`` / ``importer`` run in the server and only see JSON.
"""
