-- cmp_homework_submissions {platform, course, homework} — P0 collect-only (t1127u).
-- Shared by CMP and website DBs: the runner tags platform (cmp|website)
-- by source DSN. Returns (day, dims, value) for submitted_at in [start, end).
--
-- Resubmit semantics (verified 2026-10-22,
-- courses/views/homework_submission.py::homework_submission_for_user):
-- EVERY submit (first or edit) sets submitted_at = now(), so this counts
-- rows by LAST-submit day; an edited submission moves to the edit day.
-- Scoring never touches submitted_at. Stable only after homework closes.
--
-- Params (psycopg): %(start)s, %(end)s as UTC date boundaries, [start, end).

SELECT date_trunc('day', s.submitted_at AT TIME ZONE 'UTC')::date AS day,
       jsonb_build_object('course', c.slug, 'homework', h.slug) AS dims,
       COUNT(*)::numeric AS value
  FROM courses_submission AS s
  JOIN courses_homework AS h ON h.id = s.homework_id
  JOIN courses_course AS c ON c.id = h.course_id
 WHERE s.submitted_at >= %(start)s
   AND s.submitted_at < %(end)s
 GROUP BY 1, 2
 ORDER BY 1, 2;
