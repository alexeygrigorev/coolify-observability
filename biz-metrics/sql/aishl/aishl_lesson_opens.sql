-- aishl_lesson_opens {course} — P0 collect-only (t1127u-D).
-- Lesson SESSIONS, not pageviews: the app dedupes per user x unit within
-- 30 min (analytics/activity.py::record_lesson_open, dedupe_minutes=30).
-- object_id is the text unit pk -> cb_curriculum_unit -> module -> course.
-- Unresolvable units (deleted course rows, non-numeric ids) land in
-- course='unknown'. The CASE guard matters: plain `object_id::integer`
-- in the JOIN would be evaluated before the regex guard and fail.
-- Params (psycopg): %(start)s, %(end)s as UTC day boundaries, [start, end).

SELECT date_trunc('day', ua.occurred_at AT TIME ZONE 'UTC')::date AS day,
       jsonb_build_object('course', COALESCE(c.slug, 'unknown')) AS dims,
       COUNT(*)::numeric AS value
  FROM analytics_useractivity AS ua
  LEFT JOIN cb_curriculum_unit AS u
    ON ua.object_type = 'unit'
   AND u.id = CASE
           WHEN ua.object_id ~ '^[0-9]+$' THEN ua.object_id::integer
       END
  LEFT JOIN cb_curriculum_module AS m ON m.id = u.module_id
  LEFT JOIN cb_curriculum_course AS c ON c.id = m.course_id
 WHERE ua.event_type = 'lesson_open'
   AND ua.occurred_at >= %(start)s
   AND ua.occurred_at < %(end)s
 GROUP BY 1, 2
 ORDER BY 1, 2;
