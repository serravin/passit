import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowRight,
  BarChart3,
  CalendarDays,
  Info,
  RefreshCw,
  Settings,
  TrendingUp,
} from "lucide-react";
import { api } from "./api";
import { errorMessage, t, translateError, useLanguage } from "./i18n";

type Metric = number | null;
type Summary = {
  metrics: Record<string, Metric>;
  funnel: Record<string, number>;
  retention: {
    day: number;
    eligible: number;
    returned: number;
    rate: Metric;
  }[];
  deadlines: { bucket: string; turns: number; timeout_rate: Metric }[];
  cost_coverage: { completed: number; covered: number };
};
type Period = {
  start_date: string;
  end_date: string;
  start: string;
  end_exclusive: string;
};
type Statistics = {
  period: Period & { preset: string; timezone: string };
  comparison: Period | null;
  current: Summary;
  previous: Summary | null;
  series: {
    date: string;
    started: number;
    completed: number;
    published: number;
  }[];
  granularity: string;
  totals: { users: number; stories: number };
  tracking_since: string;
  generated_at: string;
  coverage: {
    users_without_signup_date: number;
    likes_without_date: number;
    jobs_without_date: number;
    ai_partial_history: boolean;
  };
};
type Selection = {
  preset: string;
  timezone: string;
  start?: string;
  end?: string;
};
type Definition = [
  key: string,
  label: string,
  format?: "percent" | "usd" | "decimal" | "hours" | "minutes" | "ms",
];
const presets = [
  ["today", "Today"],
  ["this_week", "This week"],
  ["mtd", "MTD"],
  ["ytd", "YTD"],
  ["last7", "Last 7 days"],
  ["last30", "Last 30 days"],
  ["all_time", "All time"],
  ["custom", "Custom"],
];
const timezoneChoices = [
  "UTC",
  "Europe/Berlin",
  "Europe/Paris",
  "Europe/Rome",
  "Europe/London",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Tokyo",
  "Australia/Sydney",
];

function initialSelection(): Selection {
  const fallback = {
    preset: "mtd",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  };
  try {
    const saved = JSON.parse(
      localStorage.getItem("passit.statistics.period") || "null",
    );
    if (
      saved &&
      presets.some(([id]) => id === saved.preset) &&
      typeof saved.timezone === "string" &&
      (saved.preset !== "custom" ||
        (typeof saved.start === "string" && typeof saved.end === "string"))
    )
      return saved;
  } catch {
    /* Keep a usable default if storage is unavailable. */
  }
  return fallback;
}

export default function Dashboard({
  navigate,
  version,
}: {
  navigate: (route: string) => void;
  version: number;
}) {
  const language = useLanguage();
  const [selection, setSelection] = useState<Selection>(initialSelection);
  const [preset, setPreset] = useState(selection.preset);
  const [timezone, setTimezone] = useState(selection.timezone);
  const [start, setStart] = useState(selection.start || "");
  const [end, setEnd] = useState(selection.end || "");
  const [compare, setCompare] = useState(true);
  const [data, setData] = useState<Statistics | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [tableOpen, setTableOpen] = useState(false);
  useEffect(() => {
    let alive = true;
    setBusy(true);
    setError("");
    const params = new URLSearchParams(selection as Record<string, string>);
    api<Statistics>("/admin/statistics?" + params)
      .then((result) => {
        if (!alive) return;
        setData(result);
        setStart(result.period.start_date);
        setEnd(result.period.end_date);
        try {
          localStorage.setItem(
            "passit.statistics.period",
            JSON.stringify(selection),
          );
        } catch {
          /* Optional browser persistence. */
        }
      })
      .catch((err) => {
        if (alive) setError(errorMessage(err));
      })
      .finally(() => {
        if (alive) setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [selection, revision, version]);

  const number = (value: Metric, format: Definition[2] = "decimal") => {
    if (value === null || value === undefined) return t("Unavailable");
    if (format === "usd")
      return new Intl.NumberFormat(language, {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 6,
      }).format(value);
    const digits =
      format === "decimal" || ["hours", "minutes"].includes(format) ? 2 : 1;
    const formatted = new Intl.NumberFormat(language, {
      maximumFractionDigits: digits,
    }).format(value);
    if (format === "percent") return formatted + "%";
    if (format === "hours") return formatted + " " + t("hours");
    if (format === "minutes") return formatted + " " + t("minutes");
    if (format === "ms") return formatted + " ms";
    return formatted;
  };
  const displayDate = (value: string) =>
    new Intl.DateTimeFormat(language, {
      dateStyle: "medium",
      timeZone: "UTC",
    }).format(new Date(value + "T12:00:00Z"));
  const range = (period: Period) =>
    `${displayDate(period.start_date)} – ${displayDate(period.end_date)}`;
  const changePreset = (next: string) => {
    setPreset(next);
    if (next !== "custom") setSelection({ preset: next, timezone });
  };
  const apply = (event: FormEvent) => {
    event.preventDefault();
    setSelection({
      preset,
      timezone,
      ...(preset === "custom" ? { start, end } : {}),
    });
  };
  const cards = (definitions: Definition[]) => (
    <div className="metric-grid">
      {definitions.map(([key, label, format]) => {
        const value = data?.current.metrics[key] ?? null;
        const previous = data?.previous?.metrics[key] ?? null;
        const delta =
          value !== null && previous !== null ? value - previous : null;
        return (
          <article className="metric-card" key={key} data-metric={key}>
            <span>{t(label)}</span>
            <strong className={value === null ? "unavailable" : ""}>
              {number(value, format)}
            </strong>
            {compare && data?.comparison && (
              <small>
                {t("Previous")}: {number(previous, format)}
                {delta !== null && (
                  <span className="metric-change">
                    {" "}
                    · {delta > 0 ? "+" : ""}
                    {number(delta, format === "percent" ? "decimal" : format)}
                    {format === "percent" ? " " + t("pp") : ""}
                  </span>
                )}
              </small>
            )}
          </article>
        );
      })}
    </div>
  );
  const metrics = data?.current.metrics;
  const funnel = data?.current.funnel;
  const maximum = Math.max(
    1,
    ...(data?.series.flatMap((row) => [row.started, row.completed]) || []),
  );
  const series = data?.series || [];
  const chartX = (index: number) =>
    42 + (index / Math.max(1, series.length - 1)) * 868;
  const chartY = (value: number) => 215 - (value / maximum) * 175;
  const points = (field: "started" | "completed") =>
    series
      .map((row, index) => `${chartX(index)},${chartY(row[field])}`)
      .join(" ");
  return (
    <section className="page statistics-page" aria-busy={busy}>
      <div className="section-heading dashboard-heading">
        <div>
          <span className="eyebrow">{t("THE BIGGER PICTURE")}</span>
          <h1>{t("Admin dashboard.")}</h1>
          <p className="page-intro">
            {t("See how people play, return, and bring stories to life.")}
          </p>
        </div>
        <div className="dashboard-actions">
          <button
            className="button secondary"
            onClick={() => navigate("admin/users")}
          >
            {t("Manage users")}
          </button>
          <button
            className="button secondary"
            onClick={() => navigate("admin/safety")}
          >
            {t("Safety reviews")}
          </button>
          <button
            className="button secondary"
            onClick={() => navigate("admin")}
          >
            <Settings size={17} />
            {t("Configuration")}
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => setRevision((v) => v + 1)}
          >
            <RefreshCw size={16} />
            {t("Refresh")}
          </button>
        </div>
      </div>
      <form className="panel period-panel" onSubmit={apply}>
        <div
          className="period-presets"
          role="group"
          aria-label={t("Reporting period")}
        >
          {presets.map(([id, label]) => (
            <button
              type="button"
              key={id}
              className={preset === id ? "selected" : ""}
              aria-pressed={preset === id}
              disabled={busy}
              onClick={() => changePreset(id)}
            >
              {t(label)}
            </button>
          ))}
        </div>
        <div className="period-fields">
          <label className="field">
            {t("Start date")}
            <input
              type="date"
              min="1970-01-01"
              value={start}
              required={preset === "custom"}
              disabled={busy}
              onChange={(event) => {
                setStart(event.target.value);
                setPreset("custom");
              }}
            />
          </label>
          <label className="field">
            {t("End date")}
            <input
              type="date"
              min={start || "1970-01-01"}
              value={end}
              required={preset === "custom"}
              disabled={busy}
              onChange={(event) => {
                setEnd(event.target.value);
                setPreset("custom");
              }}
            />
          </label>
          <label className="field">
            {t("Reporting timezone")}
            <input
              list="reporting-timezones"
              value={timezone}
              maxLength={100}
              required
              disabled={busy}
              onChange={(event) => setTimezone(event.target.value)}
            />
            <datalist id="reporting-timezones">
              {Array.from(
                new Set([...timezoneChoices, selection.timezone]),
              ).map((value) => (
                <option value={value} key={value} />
              ))}
            </datalist>
          </label>
          <button className="button primary" disabled={busy}>
            <CalendarDays size={16} />
            {t("Apply range")}
          </button>
        </div>
        <label className="comparison-toggle">
          <input
            type="checkbox"
            checked={compare}
            onChange={(event) => setCompare(event.target.checked)}
          />
          {t("Compare with the previous equivalent period")}
        </label>
        <p className="help">
          {t(
            "Weeks start on Monday. MTD means month to date; YTD means year to date. Today compares elapsed time, not a full previous day.",
          )}
        </p>
      </form>
      {error && (
        <div className="alert" role="alert">
          {translateError(error)}
        </div>
      )}
      {busy && (
        <div className="loading" role="status">
          {t("Loading statistics…")}
        </div>
      )}
      {data && !busy && (
        <>
          <div className="report-caption">
            <span>
              <CalendarDays size={15} />
              {range(data.period)} · {data.period.timezone}
            </span>
            <span>
              {t("All-time totals")}: {number(data.totals.users)}{" "}
              {t("accounts")} · {number(data.totals.stories)} {t("stories")}
            </span>
          </div>
          {compare && data.comparison && (
            <p className="help">
              {t("Compared with")} {range(data.comparison)}.{" "}
              {t("Percentage changes are shown in percentage points.")}
            </p>
          )}
          {compare && !data.comparison && (
            <p className="help">
              {t("All time has no previous equivalent period.")}
            </p>
          )}
          <section className="dashboard-section">
            <h2>
              <TrendingUp size={21} />
              {t("Activity & stories")}
            </h2>
            {cards([
              ["active_users", "Active players"],
              ["new_users", "Recorded signups"],
              ["stories_started", "Stories started"],
              ["stories_completed", "Stories completed"],
              ["stories_published", "Stories published"],
              ["cohort_in_progress", "Cohort in progress"],
              ["completion_rate", "Cohort completion rate", "percent"],
              ["avg_players", "Average players per story"],
            ])}
            <p className="help">
              <Info size={14} />{" "}
              {t(
                "Active players create a story or submit a contribution. Browsing, likes, and automatic fallbacks do not count.",
              )}
            </p>
          </section>
          <section className="panel chart-panel">
            <div className="section-heading">
              <h2>
                <BarChart3 size={20} />
                {t("Stories over time")}
              </h2>
              <span className="help">
                {t(
                  data.granularity === "day"
                    ? "Daily"
                    : data.granularity === "week"
                      ? "Weekly"
                      : "Monthly",
                )}
              </span>
            </div>
            <div className="chart-legend">
              <span className="started-key">{t("Started")}</span>
              <span className="completed-key">{t("Completed")}</span>
            </div>
            {series.some((row) => row.started || row.completed) ? (
              <svg
                className="statistics-chart"
                viewBox="0 0 940 265"
                role="img"
                aria-label={t("Stories started and completed over time")}
              >
                {[0, 0.5, 1].map((part) => (
                  <g key={part}>
                    <line
                      x1="42"
                      x2="910"
                      y1={chartY(maximum * part)}
                      y2={chartY(maximum * part)}
                      stroke="#dedfd5"
                    />
                    <text
                      x="30"
                      y={chartY(maximum * part) + 4}
                      textAnchor="end"
                    >
                      {number(maximum * part)}
                    </text>
                  </g>
                ))}
                <polyline
                  points={points("started")}
                  fill="none"
                  stroke="#df582b"
                  strokeWidth="3"
                />
                <polyline
                  points={points("completed")}
                  fill="none"
                  stroke="#526953"
                  strokeWidth="3"
                />
                {series.map((row, index) => (
                  <g
                    key={row.date}
                    tabIndex={0}
                    aria-label={`${displayDate(row.date)}: ${t("Started")} ${row.started}, ${t("Completed")} ${row.completed}`}
                  >
                    <title>
                      {displayDate(row.date)} · {t("Started")}: {row.started} ·{" "}
                      {t("Completed")}: {row.completed}
                    </title>
                    <circle
                      cx={chartX(index)}
                      cy={chartY(row.started)}
                      r="4"
                      fill="#df582b"
                    />
                    <circle
                      cx={chartX(index)}
                      cy={chartY(row.completed)}
                      r="4"
                      fill="#526953"
                    />
                  </g>
                ))}
                {[0, Math.floor((series.length - 1) / 2), series.length - 1]
                  .filter((v, i, a) => a.indexOf(v) === i)
                  .map((index) => (
                    <text
                      key={index}
                      x={chartX(index)}
                      y="250"
                      textAnchor={
                        index === 0
                          ? "start"
                          : index === series.length - 1
                            ? "end"
                            : "middle"
                      }
                    >
                      {displayDate(series[index].date)}
                    </text>
                  ))}
              </svg>
            ) : (
              <div className="chart-empty">
                {t("No stories in this period.")}
              </div>
            )}
            <button
              className="text-button"
              aria-expanded={tableOpen}
              onClick={() => setTableOpen(!tableOpen)}
            >
              {t(tableOpen ? "Hide chart data" : "View chart data")}
            </button>
            {tableOpen && (
              <div className="dashboard-table-wrap">
                <table>
                  <caption className="sr-only">
                    {t("Stories over time")}
                  </caption>
                  <thead>
                    <tr>
                      <th>{t("Date")}</th>
                      <th>{t("Started")}</th>
                      <th>{t("Completed")}</th>
                      <th>{t("Published")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {series.map((row) => (
                      <tr key={row.date}>
                        <th scope="row">{displayDate(row.date)}</th>
                        <td>{number(row.started)}</td>
                        <td>{number(row.completed)}</td>
                        <td>{number(row.published)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <div className="dashboard-columns">
            <section className="panel">
              <h2>{t("Participation funnel")}</h2>
              <p className="help">
                {t(
                  "Stories started in the selected period, followed through each stage up to its end.",
                )}
              </p>
              <div className="funnel-list">
                {[
                  ["started", "Started"],
                  ["handoff", "First handoff"],
                  ["completed", "Completed"],
                  ["published", "Published"],
                ].map(([key, label]) => (
                  <div key={key}>
                    <span>{t(label)}</span>
                    <strong>{number(funnel?.[key] ?? null)}</strong>
                    <div className="funnel-bar">
                      <i
                        style={{
                          width: `${funnel?.started ? (100 * funnel[key]) / funnel.started : 0}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </section>
            <section className="panel">
              <h2>{t("Activation & retention")}</h2>
              {cards([
                ["activation_rate", "Signup to first play", "percent"],
                ["activation_hours", "Median time to first play", "hours"],
              ])}
              <div className="dashboard-table-wrap">
                <table>
                  <caption className="sr-only">{t("Retention")}</caption>
                  <thead>
                    <tr>
                      <th>{t("Return day")}</th>
                      <th>{t("Returned / eligible")}</th>
                      <th>{t("Rate")}</th>
                      {compare && data.previous && <th>{t("Previous")}</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {data.current.retention.map((row) => (
                      <tr key={row.day}>
                        <th scope="row">{t("Day {day}", { day: row.day })}</th>
                        <td>
                          {number(row.returned)} / {number(row.eligible)}
                        </td>
                        <td>{number(row.rate, "percent")}</td>
                        {compare && data.previous && (
                          <td>
                            {number(
                              data.previous.metrics[`retention_d${row.day}`],
                              "percent",
                            )}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="help">
                {t(
                  "Retention follows players whose first contribution falls in the selected period. A return means playing on exactly day 1, 7, or 30. Only fully elapsed return days are eligible; follow-up includes activity after the selected period.",
                )}
              </p>
            </section>
          </div>
          <section className="dashboard-section">
            <h2>{t("Participation & repeat use")}</h2>
            {cards([
              ["contributions", "All contributions"],
              ["human_written", "Human-written"],
              ["ai_assisted", "AI-assisted"],
              ["automatic", "Automatic fallbacks"],
              ["unclassified_setups", "Unclassified older setups"],
              ["stories_per_active_user", "Stories per active player"],
              ["repeat_player_rate", "Players in multiple stories", "percent"],
              ["repeat_groups", "Casts playing together again"],
              ["completion_hours", "Median story completion time", "hours"],
            ])}
            <p className="help">
              {t(
                "The creator’s setup counts as a contribution. Repeat casts have the same participants in at least two stories started in the period.",
              )}
            </p>
          </section>
          <div className="dashboard-columns">
            <section className="panel">
              <h2>{t("Player responsiveness")}</h2>
              {cards([
                ["response_minutes", "Median human response time", "minutes"],
                ["timeout_rate", "Turn timeout rate", "percent"],
              ])}
              <div className="dashboard-table-wrap">
                <table>
                  <caption className="sr-only">
                    {t("Timeouts by turn deadline")}
                  </caption>
                  <thead>
                    <tr>
                      <th>{t("Turn deadline")}</th>
                      <th>{t("Settled turns")}</th>
                      <th>{t("Timeout rate")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.current.deadlines.map((row) => (
                      <tr key={row.bucket}>
                        <th scope="row">
                          {t(
                            (
                              {
                                under5: "Up to 5 minutes",
                                "5to15": "5–15 minutes",
                                "15to60": "15–60 minutes",
                                over60: "Over 60 minutes",
                              } as Record<string, string>
                            )[row.bucket],
                          )}
                        </th>
                        <td>{number(row.turns)}</td>
                        <td>{number(row.timeout_rate, "percent")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="help">
                {t(
                  "Settled turns only. Deadline comparisons describe outcomes and do not prove causation.",
                )}
              </p>
            </section>
            <section className="panel">
              <h2>{t("Publishing & engagement")}</h2>
              {cards([
                ["publication_pending", "Requests still awaiting approval"],
                ["publication_approved", "Publication approvals"],
                ["publication_declined", "Publication declines"],
                ["story_likes", "Retained story likes"],
                ["contribution_likes", "Retained contribution likes"],
              ])}
              <p className="help">
                {t(
                  "Pending requests were made in the period and remain undecided at its end. Likes are those added in the period that are still retained; removed likes are excluded.",
                )}
              </p>
            </section>
          </div>
          <section className="dashboard-section">
            <h2>{t("AI performance & cost")}</h2>
            {cards([
              ["ai_calls", "Recorded AI calls"],
              ["ai_failures", "Failed AI calls"],
              ["ai_retry_calls", "Recorded retry calls"],
              ["ai_failure_rate", "AI failure rate", "percent"],
              ["ai_latency_ms", "Median AI response time", "ms"],
              ["input_tokens", "Input tokens"],
              ["output_tokens", "Output tokens"],
              ["ai_cost_usd", "Estimated AI cost", "usd"],
              [
                "cost_per_completed_story",
                "Measured cost per completed story",
                "usd",
              ],
              ["jobs_queued", "Recorded jobs queued"],
              ["failed_jobs", "Queued jobs currently failed"],
              ["validation_calls", "Profile validation calls"],
              ["guardrail_calls", "Guardrail calls"],
            ])}
            <p className="help">
              {t(
                "Costs use recorded tokens and the USD prices saved in each AI profile revision, including retries and validation calls. Failed requests can have unknown usage. Costs are estimates, not Azure invoices.",
              )}
            </p>
            <p className="help">
              {t(
                "Complete cost coverage: {covered} of {completed} completed stories.",
                data.current.cost_coverage,
              )}{" "}
              {t(
                "Costs per story include its recorded game calls across its lifetime. Failed jobs reflect the current status of jobs queued in the period.",
              )}
            </p>
            {!!metrics?.demo_calls && (
              <p className="help">
                {t(
                  "{count} calls used the local demo generator: no billed tokens or model cost.",
                  { count: metrics.demo_calls },
                )}
              </p>
            )}
            <button className="text-button" onClick={() => navigate("admin")}>
              {t("Configure models and token prices")} <ArrowRight size={15} />
            </button>
          </section>
          <section className="panel revenue-panel">
            <h2>{t("Revenue")}</h2>
            {cards([
              ["paying_users", "Paying users"],
              ["paid_conversion", "Paid conversion", "percent"],
              ["mrr", "Monthly recurring revenue", "usd"],
              ["cancellations", "Cancellations"],
            ])}
            <p className="help">
              {t(
                "Payment reporting is unavailable until a payment integration is connected.",
              )}
            </p>
          </section>
          <section className="report-notes">
            <h3>
              <Info size={17} />
              {t("Data coverage")}
            </h3>
            <p>
              {t("New analytics tracking began on {date}.", {
                date: new Intl.DateTimeFormat(language, {
                  dateStyle: "medium",
                  timeStyle: "short",
                  timeZone: data.period.timezone,
                }).format(new Date(data.tracking_since)),
              })}
            </p>
            <p>
              {t(
                "Unknown historical dates: {users} accounts, {likes} likes, and {jobs} jobs. They are excluded from dated metrics; undated likes and jobs are included in All time.",
                {
                  users: data.coverage.users_without_signup_date,
                  likes: data.coverage.likes_without_date,
                  jobs: data.coverage.jobs_without_date,
                },
              )}
            </p>
            {data.coverage.ai_partial_history && (
              <p>
                {t(
                  "This range starts before AI usage tracking. Recorded call counts cover only measured calls; complete historical token and cost totals are unavailable.",
                )}
              </p>
            )}
            <p>
              {t(
                "Empty denominators and missing data display as Unavailable. All-time totals show currently stored accounts and stories. Only aggregate statistics are exposed.",
              )}
            </p>
          </section>
        </>
      )}
    </section>
  );
}
