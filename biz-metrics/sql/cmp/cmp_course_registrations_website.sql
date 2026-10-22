-- cmp_course_registrations {platform, course} on the WEBSITE database.
-- P0 collect-only (t1127u). The website courses_courseregistration table
-- has NO status column (verified 2026-10-22 via Model._meta.db_table /
-- fields), so website series carry no status label — the runner still
-- adds platform="website" and the metric name stays cmp_course_registrations.
-- course dim = Cohort slug (courses_course); fallback to campaign slug.
--
-- Params (psycopg): %(start)s, %(end)s as UTC date boundaries, [start, end).

SELECT (r.created_at AT TIME ZONE 'UTC')::date AS day,
       jsonb_build_object(
           'course', COALESCE(c.slug, camp.slug)
       ) AS dims,
       COUNT(*)::numeric AS value
  FROM courses_courseregistration AS r
  LEFT JOIN courses_course AS c ON c.id = r.course_id
  JOIN courses_registrationcampaign AS camp ON camp.id = r.campaign_id
 WHERE r.created_at >= %(start)s
   AND r.created_at < %(end)s
 GROUP BY 1, 2
 ORDER BY 1, 2;
