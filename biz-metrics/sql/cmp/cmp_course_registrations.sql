-- cmp_course_registrations {platform, course, status} — P0 collect-only (t1127u).
-- CMP database only: courses_courseregistration HAS a status column
-- (pending/approved/rejected). Website twin is
-- cmp_course_registrations_website.sql (no status column there).
-- Returns (day, dims, value) for created_at in [start, end).
--
-- course dim: registration.course_id (auto-set from campaign.current_course
-- on save; NULL on old rows) with fallback to the campaign slug so every
-- row lands in exactly one series.
--
-- Params (psycopg): %(start)s, %(end)s as UTC date boundaries, [start, end).

SELECT (r.created_at AT TIME ZONE 'UTC')::date AS day,
       jsonb_build_object(
           'course', COALESCE(c.slug, camp.slug),
           'status', r.status
       ) AS dims,
       COUNT(*)::numeric AS value
  FROM courses_courseregistration AS r
  LEFT JOIN courses_course AS c ON c.id = r.course_id
  JOIN courses_registrationcampaign AS camp ON camp.id = r.campaign_id
 WHERE r.created_at >= %(start)s
   AND r.created_at < %(end)s
 GROUP BY 1, 2
 ORDER BY 1, 2;
