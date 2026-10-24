from datetime import datetime

from sqlalchemy import select

from torpeda.db.models import SyncLog
from torpeda.sync import sync_all


def test_log_uses_step_finish_time(wb_client, factory):
    started = {}

    def on_step(name, i, total, summary):
        if summary is None:
            started[name] = datetime.now()

    sync_all(wb_client, factory, on_step=on_step)
    with factory() as s:
        logs = {x.section: x.at for x in s.scalars(select(SyncLog))}
    assert logs["акции"] >= started["акции"] > logs["товары"]
