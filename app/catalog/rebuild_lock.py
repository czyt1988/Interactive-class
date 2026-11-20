"""One process-wide lock for admin-triggered course rebuilds.

The watermark page and the intro/outro page both save a database row and then
rebuild the same course bundle. Two simultaneous rebuilds would race the
staging-directory swap in ``build_course``; one lock shared by both paths keeps
them serialised without introducing a task queue.
"""

from __future__ import annotations

import threading

WRITE_LOCK = threading.Lock()
