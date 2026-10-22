from datetime import datetime, timedelta, timezone
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app import models
from app.assistant_timestamps import AssistantUTCDateTime


class AssistantTimestampTests(unittest.TestCase):
    def test_bind_and_read_preserve_the_instant_across_offsets(self):
        datatype = AssistantUTCDateTime()
        instant = datetime(2026, 10, 22, 8, 30, 15, 123456, tzinfo=timezone.utc)
        for offset in (0, 8, -7):
            with self.subTest(offset=offset):
                local = instant.astimezone(timezone(timedelta(hours=offset)))
                stored = datatype.process_bind_param(local, None)
                self.assertEqual(stored, instant.replace(tzinfo=None))
                self.assertIsNone(stored.tzinfo)
                self.assertEqual(datatype.process_result_value(stored, None), instant)

    def test_legacy_naive_utc_and_nullable_values_are_preserved(self):
        datatype = AssistantUTCDateTime()
        naive = datetime(2026, 10, 22, 8, 30)
        self.assertEqual(datatype.process_bind_param(naive, None), naive)
        self.assertEqual(datatype.process_result_value(naive, None), naive.replace(tzinfo=timezone.utc))
        self.assertIsNone(datatype.process_bind_param(None, None))
        self.assertIsNone(datatype.process_result_value(None, None))

    def test_orm_reload_and_raw_sql_agree_on_utc_in_sqlite(self):
        engine = create_engine('sqlite://')
        instant = datetime(2026, 10, 22, 16, 30, tzinfo=timezone(timedelta(hours=8)))
        try:
            for table in (models.User.__table__, models.AssistantSession.__table__):
                table.create(engine)
            with Session(engine) as db:
                user = models.User(username='timestamp-only', display_name='Synthetic', hashed_password='unused')
                db.add(user); db.flush()
                room = models.AssistantSession(user_id=user.id, created_at=instant, updated_at=instant)
                db.add(room); db.commit()
                self.assertEqual(room.created_at, instant.astimezone(timezone.utc))
                self.assertEqual(room.updated_at.utcoffset(), timedelta(0))
                stored = db.execute(text('SELECT created_at FROM assistant_sessions')).scalar()
                self.assertEqual(datetime.fromisoformat(stored), instant.astimezone(timezone.utc).replace(tzinfo=None))
        finally:
            engine.dispose()
