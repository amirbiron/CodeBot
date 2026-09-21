"""``note_reminder_state`` — המודול הטהור שמכריע מהי תזכורת פעילה, ועכשיו גם איך כותבים אותה.

שלושה דברים נבדקים כאן בלי Flask ובלי מסד: שדות הכתיבה של מחזור החיים
(דריכה ודחייה) מגיעים מהמודול ולא ממחרוזות מודפסות במסלולים; ``seconds_until``
מעגל כלפי מעלה, כדי שהלקוח לא יתעורר רגע לפני המועד; ו-``parse_remind_at``
הופך את המועד שההתראה נשאה למפתח שמתאים למה שהמסד שומר.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import note_reminder_state as st

NOW = datetime(2026, 9, 21, 8, 0, 0, tzinfo=timezone.utc)


class TestLifecycleWrites(unittest.TestCase):
    """WARN-010: מי שמשנה קבוע מצב משנה מה נקרא — ועכשיו גם מה נכתב, כי אין מחרוזת אחרת."""

    def test_arming_comes_from_the_module(self):
        at = NOW + timedelta(hours=1)
        fields = st.armed_fields(at, NOW)
        self.assertEqual(fields['status'], st.REMINDER_STATUS_PENDING)
        self.assertEqual(fields['remind_at'], at)
        self.assertIsNone(fields['snooze_until'])
        self.assertIsNone(fields['ack_at'], 'דריכה מחדש חייבת לפתוח תזכורת שכבר אושרה')
        self.assertEqual(fields['updated_at'], NOW)
        self.assertTrue(fields['needs_push'])

    def test_snoozing_moves_the_time_and_leaves_the_ack_alone(self):
        """SUGG-010: הדחייה חלה רק על תזכורת פעילה, שבה ``ack_at`` כבר ריק — אין מה לאפס."""
        until = NOW + timedelta(minutes=10)
        fields = st.snoozed_fields(until, NOW)
        self.assertEqual(fields['status'], st.REMINDER_STATUS_SNOOZED)
        self.assertEqual(fields['remind_at'], until)
        self.assertEqual(fields['snooze_until'], until)
        self.assertNotIn('ack_at', fields)
        self.assertEqual(fields['updated_at'], NOW)
        self.assertTrue(fields['needs_push'])


class TestSecondsUntil(unittest.TestCase):
    def test_rounds_up_so_the_client_never_wakes_before_the_reminder(self):
        """SUGG-002: ``int()`` חתך מטה. הלקוח התעורר רגע לפני המועד, לא מצא כלום,
        קיבל 0, והרצפה של דקה הפכה את זה לכמעט דקה שלמה של איחור בבועה."""
        self.assertEqual(st.seconds_until(NOW + timedelta(seconds=0.4), NOW), 1)
        self.assertEqual(st.seconds_until(NOW + timedelta(seconds=61.5), NOW), 62)
        self.assertEqual(st.seconds_until(NOW + timedelta(seconds=60), NOW), 60)

    def test_a_value_in_another_offset_is_the_same_instant(self):
        plus_three = timezone(timedelta(hours=3))
        value = (NOW + timedelta(minutes=10)).astimezone(plus_three)
        self.assertEqual(st.seconds_until(value, NOW), 600)

    def test_a_naive_value_is_read_as_utc(self):
        """ביטוח ללקוח שנבנה בלי ``tz_aware``. כל לקוחות המסד בריפו נבנים איתו, ולכן
        הענף הזה אינו ראיה לכיסוי מסלול אזור הזמן בייצור — רק לכך שאינו זורק."""
        self.assertEqual(st.seconds_until(datetime(2026, 9, 21, 8, 10, 0), NOW), 600)


class TestParseRemindAt(unittest.TestCase):
    """WARN-001: המועד שההתראה נשאה חוזר כמחרוזת ISO; המפתח חייב להתאים למה שמונגו שומר."""

    def test_absent_means_no_binding(self):
        self.assertIsNone(st.parse_remind_at(None))
        self.assertIsNone(st.parse_remind_at(''))

    def test_an_iso_string_with_offset_becomes_the_stored_key(self):
        """BSON שומר מילישניות (``_datetime_to_millis`` ב-pymongo מחלק ב-1000), ולכן
        המפתח נחתך למילישניות: מחרוזת עם מיקרו-שניות עדיין מתאימה למסמך."""
        parsed = st.parse_remind_at('2026-09-20T09:00:00.123456+00:00')
        self.assertEqual(parsed, datetime(2026, 9, 20, 9, 0, 0, 123000, tzinfo=timezone.utc))

    def test_an_offset_is_converted_not_relabelled(self):
        parsed = st.parse_remind_at('2026-09-20T12:00:00+03:00')
        self.assertEqual(parsed, datetime(2026, 9, 20, 9, 0, 0, tzinfo=timezone.utc))

    def test_a_naive_string_is_utc(self):
        parsed = st.parse_remind_at('2026-09-20T09:00:00')
        self.assertEqual(parsed, datetime(2026, 9, 20, 9, 0, 0, tzinfo=timezone.utc))

    def test_a_z_suffix_is_utc(self):
        parsed = st.parse_remind_at('2026-09-20T09:00:00Z')
        self.assertEqual(parsed, datetime(2026, 9, 20, 9, 0, 0, tzinfo=timezone.utc))

    def test_anything_unreadable_raises(self):
        for bad in ('yesterday', 123, ['2026-09-20T09:00:00+00:00'], {'at': 1}):
            with self.subTest(raw=bad):
                with self.assertRaises(ValueError):
                    st.parse_remind_at(bad)


if __name__ == '__main__':
    unittest.main()
