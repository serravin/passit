import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Ban,
  Search,
  ShieldCheck,
  UnlockKeyhole,
  X,
} from "lucide-react";
import { api } from "./api";
import type { Person } from "./api";
import { errorMessage, t, translateError, useLanguage } from "./i18n";

type User = Person & {
  admin: boolean;
  blocked_at: string | null;
  block_reason: string | null;
};
type UserPage = { items: User[]; total: number; offset: number; limit: number };
type Event = {
  id: string;
  user: Person;
  admin: Person | null;
  source: string;
  blocked: boolean;
  reason: string | null;
  created_at: string;
};
type Action = (
  work: () => Promise<unknown>,
  message?: string,
) => Promise<boolean>;

export default function UserManagement({
  action,
  version,
  navigate,
}: {
  action: Action;
  version: number;
  navigate: (route: string) => void;
}) {
  const language = useLanguage();
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState({
    q: "",
    status: "all",
    offset: 0,
  });
  const [users, setUsers] = useState<UserPage | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [target, setTarget] = useState<User | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState("");
  useEffect(() => {
    let alive = true;
    setBusy(true);
    setError("");
    const params = new URLSearchParams({
      ...selection,
      offset: String(selection.offset),
    });
    Promise.all([
      api<UserPage>("/admin/users?" + params),
      api<Event[]>("/admin/moderation"),
    ])
      .then(([accounts, history]) => {
        if (alive) {
          setUsers(accounts);
          setEvents(history);
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
  }, [selection, version]);
  useEffect(() => {
    if (!target) return;
    const previous = document.activeElement as HTMLElement | null;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) setTarget(null);
      if (event.key === "Tab") {
        const elements = Array.from(
          document.querySelectorAll<HTMLElement>(
            ".moderation-dialog button:not(:disabled), .moderation-dialog textarea:not(:disabled)",
          ),
        );
        const first = elements[0],
          last = elements[elements.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.getElementById("moderation-reason")?.focus();
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [target, saving]);
  const date = (value: string) =>
    new Intl.DateTimeFormat(language, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  const count = (value: number) =>
    new Intl.NumberFormat(language).format(value);
  function choose(user: User) {
    setReason("");
    setDialogError("");
    setTarget(user);
  }
  async function apply() {
    if (!target || saving) return;
    setSaving(true);
    const ok = await action(
      async () => {
        try {
          await api(`/admin/users/${target.id}/block`, "PUT", {
            blocked: !target.blocked_at,
            reason: reason.trim() || null,
          });
        } catch (err) {
          setDialogError(errorMessage(err));
          throw err;
        }
      },
      target.blocked_at ? "User unblocked." : "User blocked.",
    );
    setSaving(false);
    if (ok) setTarget(null);
  }
  return (
    <section className="page moderation-page" aria-busy={busy}>
      <button className="back-link" onClick={() => navigate("dashboard")}>
        <ArrowLeft size={16} /> {t("Admin dashboard")}
      </button>
      <span className="eyebrow">{t("KEEP THE GAME WELCOMING")}</span>
      <h1>{t("User management.")}</h1>
      <button
        className="button secondary"
        onClick={() => navigate("admin/safety")}
      >
        {t("Safety reviews")}
      </button>
      <p className="page-intro">
        {t("Find accounts and manage access when someone misuses the app.")}
      </p>
      <form
        className="panel moderation-filters"
        onSubmit={(event) => {
          event.preventDefault();
          setSelection({ ...selection, q: query, offset: 0 });
        }}
      >
        <label className="field">
          {t("Search users")}
          <input
            value={query}
            maxLength={80}
            placeholder={t("Name or account ID")}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label className="field">
          {t("Account status")}
          <select
            aria-label={t("Account status")}
            value={selection.status}
            onChange={(event) =>
              setSelection({
                ...selection,
                status: event.target.value,
                offset: 0,
              })
            }
          >
            <option value="all">{t("All accounts")}</option>
            <option value="active">{t("Active accounts")}</option>
            <option value="blocked">{t("Blocked accounts")}</option>
          </select>
        </label>
        <button className="button primary" disabled={busy}>
          <Search size={16} />
          {t("Search")}
        </button>
      </form>
      {error && (
        <div className="alert" role="alert">
          {translateError(error)}
        </div>
      )}
      {busy && (
        <p className="loading" role="status">
          {t("Loading users…")}
        </p>
      )}
      {!busy && users && (
        <>
          <section className="panel">
            <div className="section-heading">
              <h2>
                <ShieldCheck size={22} />
                {t("Account access")}
              </h2>
              <span className="help">
                {t("{count} accounts found", { count: count(users.total) })}
              </span>
            </div>
            <p className="help">
              {t(
                "Blocks stop signed-in access immediately and exclude accounts from new stories. Administrator accounts are protected.",
              )}
            </p>
            <div className="moderation-users">
              {users.items.map((user) => (
                <article className="moderation-user" key={user.id}>
                  <span
                    className="avatar small"
                    style={{ background: user.color }}
                    aria-hidden="true"
                  >
                    {user.name.slice(0, 1)}
                  </span>
                  <div className="moderation-user-details">
                    <h3>
                      {user.name}{" "}
                      <span
                        className={`status ${user.blocked_at ? "blocked-status" : ""}`}
                      >
                        {t(
                          user.admin
                            ? "Administrator"
                            : user.blocked_at
                              ? "Blocked"
                              : "Active",
                        )}
                      </span>
                    </h3>
                    <p className="help account-id">{user.id}</p>
                    {user.blocked_at && (
                      <p className="help">
                        {t("Blocked on {date}", {
                          date: date(user.blocked_at),
                        })}
                      </p>
                    )}
                    {user.block_reason && (
                      <p className="moderation-reason">{user.block_reason}</p>
                    )}
                  </div>
                  <button
                    className={`button ${user.blocked_at ? "secondary" : "danger"} compact`}
                    disabled={user.admin}
                    aria-label={t(
                      user.blocked_at ? "Unblock {name}" : "Block {name}",
                      { name: user.name },
                    )}
                    onClick={() => choose(user)}
                  >
                    {user.blocked_at ? (
                      <UnlockKeyhole size={16} />
                    ) : (
                      <Ban size={16} />
                    )}
                    {t(user.blocked_at ? "Unblock" : "Block")}
                  </button>
                </article>
              ))}
              {!users.items.length && (
                <p className="help">{t("No accounts match your search.")}</p>
              )}
            </div>
            <div className="moderation-pagination">
              <button
                className="button secondary compact"
                disabled={!selection.offset}
                onClick={() =>
                  setSelection({
                    ...selection,
                    offset: Math.max(0, selection.offset - users.limit),
                  })
                }
              >
                <ArrowLeft size={15} />
                {t("Previous")}
              </button>
              <span className="help">
                {t("{start}–{end} of {total}", {
                  start: count(users.items.length ? selection.offset + 1 : 0),
                  end: count(selection.offset + users.items.length),
                  total: count(users.total),
                })}
              </span>
              <button
                className="button secondary compact"
                disabled={selection.offset + users.limit >= users.total}
                onClick={() =>
                  setSelection({
                    ...selection,
                    offset: selection.offset + users.limit,
                  })
                }
              >
                {t("Next")}
                <ArrowRight size={15} />
              </button>
            </div>
          </section>
          <section className="panel moderation-history">
            <h2>{t("Recent administrator actions")}</h2>
            <p className="help">
              {t(
                "The latest 20 block and unblock actions. Reasons and history are visible only to administrators.",
              )}
            </p>
            {events.length ? (
              <div className="dashboard-table-wrap">
                <table>
                  <caption className="sr-only">
                    {t("Recent administrator actions")}
                  </caption>
                  <thead>
                    <tr>
                      <th>{t("Account")}</th>
                      <th>{t("Action")}</th>
                      <th>{t("Administrator")}</th>
                      <th>{t("Date")}</th>
                      <th>{t("Private reason")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((event) => (
                      <tr key={event.id}>
                        <th scope="row">
                          {event.user.name}
                          <small className="account-id">{event.user.id}</small>
                        </th>
                        <td>{t(event.blocked ? "Blocked" : "Unblocked")}</td>
                        <td>{event.admin?.name || t("Automated guardrail")}</td>
                        <td>{date(event.created_at)}</td>
                        <td className="moderation-reason">
                          {event.reason || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="help">{t("No moderation actions yet.")}</p>
            )}
          </section>
        </>
      )}
      {target && (
        <div
          className="modal-backdrop"
          onClick={() => {
            if (!saving) setTarget(null);
          }}
        >
          <form
            className="modal moderation-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="moderation-title"
            onClick={(event) => event.stopPropagation()}
            onSubmit={(event) => {
              event.preventDefault();
              void apply();
            }}
          >
            <button
              type="button"
              className="modal-close icon-button"
              disabled={saving}
              aria-label={t("Close")}
              onClick={() => setTarget(null)}
            >
              <X size={20} />
            </button>
            <h2 id="moderation-title">
              {t(target.blocked_at ? "Unblock {name}?" : "Block {name}?", {
                name: target.name,
              })}
            </h2>
            <p className="help account-id">{target.id}</p>
            <p>
              {t(
                target.blocked_at
                  ? "This account will be able to sign in and play again."
                  : "This account will lose signed-in access immediately. Existing contributions stay in their stories.",
              )}
            </p>
            <label className="field" htmlFor="moderation-reason">
              {t("Private reason (optional)")}
            </label>
            <textarea
              id="moderation-reason"
              rows={3}
              maxLength={500}
              value={reason}
              disabled={saving}
              onChange={(event) => setReason(event.target.value)}
            />
            <p className="help">
              {t("Visible only to administrators. Up to 500 characters.")}
            </p>
            {dialogError && (
              <div className="alert" role="alert">
                {translateError(dialogError)}
              </div>
            )}
            <div className="modal-actions">
              <button
                type="button"
                className="button secondary"
                disabled={saving}
                onClick={() => setTarget(null)}
              >
                {t("Cancel")}
              </button>
              <button
                className={`button ${target.blocked_at ? "primary" : "danger"}`}
                disabled={saving}
              >
                {t(
                  saving
                    ? "Saving…"
                    : target.blocked_at
                      ? "Unblock user"
                      : "Block user",
                )}
              </button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}
