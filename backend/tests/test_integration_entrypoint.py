import os

import pytest


@pytest.mark.skipif(not os.getenv("PICAGENT_INTEGRATION"), reason="set PICAGENT_INTEGRATION=1 with PostgreSQL/MinIO test services")
def test_external_integration_entrypoint_is_opt_in() -> None:
    assert os.getenv("PICAGENT_INTEGRATION") == "1"
