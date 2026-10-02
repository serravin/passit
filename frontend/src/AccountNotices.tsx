import { t } from "./i18n";
import type { AccountNotice } from "./api";

export function safetyCategory(code: string): string {
  return t(
    (
      {
        bullying: "Bullying or harassment",
        hate: "Hate targeting protected groups",
        threats: "Threats or encouragement of violence",
        sexual_abuse: "Sexual exploitation or abuse",
        personal_data: "Private personal information",
        self_harm: "Encouragement of self-harm",
      } as Record<string, string>
    )[code] || "Inappropriate content",
  );
}

export default function AccountNotices({
  notices,
  dismiss,
}: {
  notices: AccountNotice[];
  dismiss: (id: string) => void;
}) {
  if (!notices.length) return null;
  return (
    <section
      className="account-notices"
      aria-label={t("Account notices")}
      aria-live="polite"
    >
      {notices.map((notice) => (
        <article className="panel account-notice" key={notice.id}>
          <div>
            <strong>
              {t(
                notice.kind === "restored"
                  ? "Your account access was restored."
                  : notice.source === "guardrail"
                    ? "Your account was blocked by the story safety check."
                    : "Your account was blocked by an administrator.",
              )}
            </strong>
            {!!notice.categories.length && (
              <p>
                {t("Reason")}:{" "}
                {notice.categories.map(safetyCategory).join(", ")}
              </p>
            )}
            {notice.kind === "blocked" && (
              <p>
                {t(
                  "Contact an administrator to request a review. Your existing contributions remain stored.",
                )}
              </p>
            )}
          </div>
          <button
            className="button secondary compact"
            onClick={() => dismiss(notice.id)}
          >
            {t("Dismiss notice")}
          </button>
        </article>
      ))}
    </section>
  );
}
