import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, ShieldCheck } from "lucide-react";
import { api } from "./api";
import type { Person } from "./api";
import { errorMessage, t, translateError, useLanguage } from "./i18n";
import { safetyCategory } from "./AccountNotices";

type Review = {
  id: string;
  user: Person | null;
  chain_id: string | null;
  kind: string;
  origin: string;
  categories: string[];
  text: string;
  context: {
    setup?: string;
    rules?: string;
    previous_contributions?: string[];
  };
  created_at: string;
  review_status: string;
  profile_id: string;
};
type Results = {
  items: Review[];
  total: number;
  offset: number;
  limit: number;
};
type Action = (
  work: () => Promise<unknown>,
  message?: string,
) => Promise<boolean>;

export default function SafetyReviews({
  action,
  version,
  navigate,
}: {
  action: Action;
  version: number;
  navigate: (route: string) => void;
}) {
  const language = useLanguage();
  const [selection, setSelection] = useState({ status: "pending", offset: 0 });
  const [results, setResults] = useState<Results | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let alive = true;
    setBusy(true);
    setError("");
    const params = new URLSearchParams({
      status: selection.status,
      offset: String(selection.offset),
    });
    api<Results>("/admin/safety-reviews?" + params)
      .then((data) => {
        if (alive) setResults(data);
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
  }, [selection, version]);
  async function decide(review: Review, decision: string) {
    const description =
      decision === "allow"
        ? t(
            "Allow this flagged text? Any automatic block is reversed only when all of this user's flags are cleared. Administrator blocks remain in place.",
          )
        : t(
            "Confirm this safety flag? The text stays withheld and any automatic account block remains in place.",
          );
    if (!window.confirm(description)) return;
    setSaving(true);
    await action(
      () => api(`/admin/safety-reviews/${review.id}`, "PUT", { decision }),
      "Safety review saved.",
    );
    setSaving(false);
  }
  return (
    <section className="page safety-page" aria-busy={busy}>
      <button className="back-link" onClick={() => navigate("dashboard")}>
        <ArrowLeft size={16} />
        {t("Admin dashboard")}
      </button>
      <span className="eyebrow">{t("A SAFER PLACE TO PLAY")}</span>
      <h1>{t("Story safety reviews.")}</h1>
      <p className="page-intro">
        {t(
          "Review guardrail flags, see the evidence, and correct mistaken decisions.",
        )}
      </p>
      <div className="dashboard-actions">
        <button className="button secondary" onClick={() => navigate("admin")}>
          {t("Configure the guardrail")}
        </button>
        <button
          className="button secondary"
          onClick={() => navigate("admin/users")}
        >
          {t("Manage users")}
        </button>
      </div>
      <p className="help">
        {t(
          "Every flagged human submission triggers an automatic block. AI output is withheld without blaming a player. Administrator accounts are protected, but their flagged content is withheld too.",
        )}
      </p>
      <label className="field safety-filter">
        {t("Review status")}
        <select
          aria-label={t("Review status")}
          value={selection.status}
          onChange={(event) =>
            setSelection({ status: event.target.value, offset: 0 })
          }
        >
          <option value="pending">{t("Awaiting review")}</option>
          <option value="confirmed">{t("Confirmed flags")}</option>
          <option value="allowed">{t("Allowed after review")}</option>
        </select>
      </label>
      {error && (
        <div className="alert" role="alert">
          {translateError(error)}
        </div>
      )}
      {busy && (
        <p className="loading" role="status">
          {t("Loading safety reviews…")}
        </p>
      )}
      {!busy && results && (
        <>
          <p className="help">
            {t("{count} flags found", { count: results.total })}
          </p>
          {results.items.map((review) => (
            <article className="panel safety-review" key={review.id}>
              <div className="section-heading">
                <h2>
                  <ShieldCheck size={22} />
                  {review.user?.name || t("AI-generated text")}
                </h2>
                <span className="status">
                  {t(
                    review.origin === "human"
                      ? "Human-written"
                      : "AI-generated text",
                  )}
                </span>
              </div>
              {review.user && (
                <p className="help account-id">{review.user.id}</p>
              )}
              <p className="help">
                {new Intl.DateTimeFormat(language, {
                  dateStyle: "medium",
                  timeStyle: "short",
                }).format(new Date(review.created_at))}
              </p>
              <div className="safety-categories">
                {review.categories.map((category) => (
                  <span className="status blocked-status" key={category}>
                    {safetyCategory(category)}
                  </span>
                ))}
              </div>
              <h3>{t("Flagged text")}</h3>
              <blockquote className="safety-evidence">{review.text}</blockquote>
              {!!Object.keys(review.context || {}).length && (
                <details className="safety-context">
                  <summary>{t("Story context")}</summary>
                  {review.context.setup && <p>{review.context.setup}</p>}
                  {review.context.rules && (
                    <p>
                      <strong>{t("Rules")}: </strong>
                      {review.context.rules}
                    </p>
                  )}
                  {review.context.previous_contributions?.map((text, index) => (
                    <p key={index}>{text}</p>
                  ))}
                </details>
              )}
              {review.review_status === "pending" && (
                <div className="dashboard-actions">
                  <button
                    className="button secondary"
                    disabled={saving}
                    onClick={() => void decide(review, "allow")}
                  >
                    {t("Allow & review account access")}
                  </button>
                  <button
                    className="button danger"
                    disabled={saving}
                    onClick={() => void decide(review, "confirm")}
                  >
                    {t("Confirm flag")}
                  </button>
                </div>
              )}
            </article>
          ))}
          {!results.items.length && (
            <div className="panel">
              <p>{t("No safety flags in this view.")}</p>
            </div>
          )}
          <div className="moderation-pagination">
            <button
              className="button secondary compact"
              disabled={!selection.offset}
              onClick={() =>
                setSelection({
                  ...selection,
                  offset: Math.max(0, selection.offset - results.limit),
                })
              }
            >
              <ArrowLeft size={15} />
              {t("Previous")}
            </button>
            <span className="help">
              {t("{start}–{end} of {total}", {
                start: results.items.length ? selection.offset + 1 : 0,
                end: selection.offset + results.items.length,
                total: results.total,
              })}
            </span>
            <button
              className="button secondary compact"
              disabled={selection.offset + results.limit >= results.total}
              onClick={() =>
                setSelection({
                  ...selection,
                  offset: selection.offset + results.limit,
                })
              }
            >
              {t("Next")}
              <ArrowRight size={15} />
            </button>
          </div>
        </>
      )}
    </section>
  );
}
