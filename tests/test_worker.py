from __future__ import annotations

import unittest

from profile_manager.worker import AsyncWorker, WorkerUnavailableError


class AsyncWorkerTests(unittest.TestCase):
    def test_submit_after_stop_rejects_and_closes_coroutine(self) -> None:
        worker = AsyncWorker()
        worker.stop()

        async def unused() -> None:
            return None

        coroutine = unused()
        with self.assertRaises(WorkerUnavailableError):
            worker.submit(coroutine)
        self.assertIsNone(coroutine.cr_frame)


if __name__ == "__main__":
    unittest.main()