-- aishl_active_learners {course, grain} — P0 collect-only (t1127u-D).
-- Distinct users with >= 1 lesson_open or resource_view. DAU per course
-- counts lesson_open users attributed unit -> course; resource_view rows
-- are not course-bound, so they only feed the course='all' rows.
-- Unresolvable lesson_open units land in course='unknown' (NOT 'all').
--
-- grain='day' rows cover exactly [%(start)s, %(end)s) (one UTC day per
-- runner call). grain='week' is a single row with day = ISO Monday of the
-- week containing %(start)s, counting distinct users over the FULL week
-- window -- so the runner rewrites the same Monday row each day as the
-- week fills; the D-1..D-7 recompute window settles the final value.
-- The grain dim keeps weekly rows from colliding with the daily Monday row
-- under the metric_daily PK. WAU is overall only (course='all').
-- Params (psycopg): %(start)s, %(end)s as UTC day boundaries, [start, end).

WITH bounds AS (
    SELECT (%(start)s::date
        - ((EXTRACT(ISODOW FROM %(start)s::date)::int) - 1)) AS mon
),
week_users AS (
    SELECT ua.occurred_at AS occurred_at,
           CASE
               WHEN ua.event_type = 'lesson_open'
                   THEN COALESCE(c.slug, 'unknown')
               ELSE 'all'
           END AS course,
           ua.user_id AS user_id,
           ua.event_type AS event_type
      FROM analytics_useractivity AS ua
      LEFT JOIN cb_curriculum_unit AS u
        ON ua.event_type = 'lesson_open'
       AND ua.object_type = 'unit'
       AND u.id = CASE
               WHEN ua.object_id ~ '^[0-9]+$' THEN ua.object_id::integer
           END
      LEFT JOIN cb_curriculum_module AS m ON m.id = u.module_id
      LEFT JOIN cb_curriculum_course AS c ON c.id = m.course_id
     WHERE ua.event_type IN ('lesson_open', 'resource_view')
       AND ua.occurred_at >= (SELECT mon FROM bounds)
       AND ua.occurred_at < (SELECT mon FROM bounds) + 7
),
day_users AS (
    SELECT * FROM week_users
     WHERE occurred_at >= %(start)s
       AND occurred_at < %(end)s
),
per_course_day AS (
    SELECT (occurred_at AT TIME ZONE 'UTC')::date AS day,
           course, COUNT(DISTINCT user_id)::numeric AS value
      FROM day_users
     WHERE event_type = 'lesson_open'
     GROUP BY 1, 2
),
overall_day AS (
    SELECT (occurred_at AT TIME ZONE 'UTC')::date AS day,
           'all' AS course, COUNT(DISTINCT user_id)::numeric AS value
      FROM day_users
     GROUP BY 1
),
overall_week AS (
    SELECT (SELECT mon FROM bounds) AS day,
           'all' AS course, COUNT(DISTINCT user_id)::numeric AS value
      FROM week_users
)
SELECT day, jsonb_build_object('course', course, 'grain', 'day') AS dims, value
  FROM per_course_day
UNION ALL
SELECT day, jsonb_build_object('course', course, 'grain', 'day') AS dims, value
  FROM overall_day
UNION ALL
SELECT day, jsonb_build_object('course', course, 'grain', 'week') AS dims, value
  FROM overall_week
 ORDER BY 1, 2;
