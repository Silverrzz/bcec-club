from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from cope.core.models import EngineSpec
from cope.worker.uci_engine import EnginePreparationError, UciEngineProcess


BINARY = b"#!/bin/sh\nexit 0\n"


def engine_spec() -> EngineSpec:
    return EngineSpec(
        engine_id=1,
        name="Test Engine",
        author="COPE",
        version="1.0",
        binary_url="/api/worker/engine-binaries/1",
        binary_sha256=hashlib.sha256(BINARY).hexdigest(),
        binary_size=len(BINARY),
    )


def process(spec: EngineSpec | None = None) -> UciEngineProcess:
    return UciEngineProcess(
        spec or engine_spec(),
        server_url="wss://cope.invalid/worker",
        credential="worker-session",
    )


class MachineEngineCacheTests(unittest.TestCase):
    def test_concurrent_slots_download_exact_binary_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            downloads = 0

            def fake_download(url, destination, **kwargs):
                nonlocal downloads
                downloads += 1
                self.assertEqual(url, "https://cope.invalid/api/worker/engine-binaries/1")
                self.assertEqual(kwargs["credential"], "worker-session")
                destination.write_bytes(BINARY)

            with (
                patch.dict(os.environ, {"COPE_WORKER_ENGINE_DIR": temporary_root}),
                patch("cope.worker.uci_engine._download_binary", side_effect=fake_download),
            ):
                engines = [process() for _ in range(32)]
                with ThreadPoolExecutor(max_workers=32) as executor:
                    list(executor.map(lambda engine: engine.prepare(), engines))

                self.assertEqual(downloads, 1)
                self.assertEqual(len({engine._source_dir for engine in engines}), 1)
                self.assertEqual(engines[0]._binary_path.read_bytes(), BINARY)

    def test_hash_mismatch_is_shared_as_recent_machine_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            def bad_download(url, destination, **kwargs):
                destination.write_bytes(b"corrupt")

            def prepare_and_capture(engine: UciEngineProcess) -> str:
                try:
                    engine.prepare()
                except EnginePreparationError as error:
                    return f"{error.stage}: {error.detail}"
                self.fail("engine preparation unexpectedly succeeded")

            with (
                patch.dict(os.environ, {"COPE_WORKER_ENGINE_DIR": temporary_root}),
                patch("cope.worker.uci_engine._download_binary", side_effect=bad_download),
            ):
                errors = [prepare_and_capture(process()), prepare_and_capture(process())]

            self.assertIn("verify: SHA-256 mismatch", errors[0])
            self.assertIn("recent machine-wide download attempt failed", errors[1])

    def test_same_artifact_is_shared_between_registered_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            second = engine_spec().model_copy(update={"engine_id": 2, "version": "2.0", "binary_url": "/api/worker/engine-binaries/2"})
            with patch.dict(os.environ, {"COPE_WORKER_ENGINE_DIR": temporary_root}):
                self.assertEqual(process()._source_dir, process(second)._source_dir)


if __name__ == "__main__":
    unittest.main()
