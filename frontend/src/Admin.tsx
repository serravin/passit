import { t, translateError, errorMessage } from "./i18n";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Check, RotateCcw, Settings, Sparkles } from "lucide-react";
import { api } from "./api";

type Action = (
  work: () => Promise<unknown>,
  message?: string,
) => Promise<boolean>;
type Profile = {
  id: string;
  revision: number;
  status: string;
  provider: string;
  model_reference: string;
  deployment_name: string;
  endpoint: string;
  validated_at: string | null;
};
type AdminState = {
  max_participants_per_chain: number;
  profiles: Profile[];
  assignments: Record<string, string>;
  failed_work: {
    id: string;
    task: string;
    attempts: number;
    error_code: string;
  }[];
};

export default function Admin({
  action,
  version,
}: {
  action: Action;
  version: number;
}) {
  const [state, setState] = useState<AdminState | null>(null);
  const [cap, setCap] = useState(20);
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState({
    provider: "azure_openai",
    endpoint: "",
    deployment_name: "",
    model_reference: "",
    api_version: "2024-10-21",
    auth_mode: "managed_identity",
    credential_reference: "PASSIT_AI_API_KEY",
    request_timeout_seconds: 30,
    max_retries: 3,
    prompt_version: "v1",
  });
  const [parameters, setParameters] = useState(
    '{"max_completion_tokens": 500}',
  );
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    api<AdminState>("/admin")
      .then((data) => {
        if (alive) {
          setState(data);
          setCap(data.max_participants_per_chain);
          setError("");
        }
      })
      .catch((e) => {
        if (alive) setError(errorMessage(e));
      });
    return () => {
      alive = false;
    };
  }, [version]);
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    await action(
      async () =>
        api("/admin/profiles", "POST", {
          ...profile,
          generation_parameters: JSON.parse(parameters),
        }),
      "Profile revision created. Validate it before activation.",
    );
    setBusy(false);
  }
  return (
    <section className="page">
      <span className="eyebrow">{t("BEHIND THE STORIES")}</span>
      <h1>{t("Platform configuration.")}</h1>
      <p className="page-intro">
        {t(
          "Manage participant limits, versioned AI profiles, and failed background work.",
        )}{" "}
      </p>
      {error && (
        <div className="alert" role="alert">
          {translateError(error)}
        </div>
      )}
      <div className="admin-layout">
        <div>
          <form
            className="panel"
            onSubmit={async (e) => {
              e.preventDefault();
              await action(
                () =>
                  api("/admin/platform", "PUT", {
                    max_participants_per_chain: cap,
                  }),
                "Global participant cap saved.",
              );
            }}
          >
            <h2>
              <Settings size={20} />
              {t("Participant limit")}{" "}
            </h2>
            <label className="field">
              {t("Global maximum")}{" "}
              <input
                type="number"
                min={2}
                max={100}
                value={cap}
                onChange={(e) => setCap(Number(e.target.value))}
              />
            </label>
            <p className="help">
              {t(
                "Applies at launch. Existing active Chains keep their settings.",
              )}{" "}
            </p>
            <button className="button secondary">
              {t("Save limit")} <Check size={16} />
            </button>
          </form>
          <section className="panel">
            <h2>{t("Profile revisions")}</h2>
            <p className="help">
              {t(
                "Validate connectivity and all four output schemas before activation. Queued work retains its resolved revision.",
              )}{" "}
            </p>
            {state?.profiles.map((p) => (
              <article className="profile-revision" key={p.id}>
                <div>
                  <h3>
                    {t("Revision")} {p.revision}{" "}
                    <span className="status">{p.provider}</span>
                  </h3>
                  <p>
                    {p.model_reference ||
                      p.deployment_name ||
                      t("No model reference")}
                  </p>
                  <p className="help">
                    {p.endpoint || t("Local sample generator")} ·{" "}
                    {p.validated_at ? t("Validated") : t("Not validated")}
                  </p>
                </div>
                <div className="profile-controls">
                  <button
                    className="button secondary compact"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      await action(
                        () => api(`/admin/profiles/${p.id}/validate`, "POST"),
                        "Profile validation passed.",
                      );
                      setBusy(false);
                    }}
                  >
                    {t("Validate")}{" "}
                  </button>
                  <select
                    aria-label={t("Activate revision {number} for a task", {
                      number: p.revision,
                    })}
                    defaultValue=""
                    disabled={busy || !p.validated_at}
                    onChange={(e) => {
                      const task = e.target.value;
                      if (task)
                        void action(
                          () =>
                            api(`/admin/profiles/${p.id}/activate`, "POST", {
                              task,
                            }),
                          t("Revision {number} activated for {task}.", {
                            number: p.revision,
                            task: t(task),
                          }),
                        );
                      e.target.value = "";
                    }}
                  >
                    <option value="">{t("Activate for…")}</option>
                    {[
                      "default",
                      "handoff",
                      "suggestions",
                      "title",
                      "setup",
                    ].map((task) => (
                      <option key={task} value={task}>
                        {t(task)}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="help">
                  {t("Active for:")}{" "}
                  {Object.entries(state.assignments)
                    .filter(([, id]) => id === p.id)
                    .map(([task]) => t(task))
                    .join(", ") || t("none")}
                </p>
              </article>
            ))}
          </section>
          <section className="panel">
            <h2>{t("Failed work")}</h2>
            {state?.failed_work.length ? (
              state.failed_work.map((w) => (
                <div className="failed-work" key={w.id}>
                  <div>
                    <strong>{t(w.task)}</strong>
                    <p className="help">
                      {t("{count} attempts", { count: w.attempts })} ·{" "}
                      {w.error_code}
                    </p>
                  </div>
                  <button
                    className="button secondary compact"
                    onClick={() =>
                      void action(
                        () => api(`/admin/work/${w.id}/retry`, "POST"),
                        "Work item queued for retry.",
                      )
                    }
                  >
                    <RotateCcw size={15} />
                    {t("Retry")}{" "}
                  </button>
                </div>
              ))
            ) : (
              <p className="help">{t("No failed work items.")}</p>
            )}
          </section>
        </div>
        <form className="panel" onSubmit={save}>
          <h2>
            <Sparkles size={20} />
            {t("New AI revision")}{" "}
          </h2>
          <label className="field">
            {t("Provider")}{" "}
            <select
              value={profile.provider}
              onChange={(e) =>
                setProfile({ ...profile, provider: e.target.value })
              }
            >
              <option value="azure_openai">Azure OpenAI</option>
              <option value="demo">{t("Local demo (development only)")}</option>
            </select>
          </label>
          <label className="field">
            {t("Approved HTTPS endpoint")}{" "}
            <input
              type="url"
              placeholder="https://your-resource.openai.azure.com"
              value={profile.endpoint}
              required={profile.provider === "azure_openai"}
              onChange={(e) =>
                setProfile({ ...profile, endpoint: e.target.value })
              }
            />
          </label>
          <label className="field">
            {t("Deployment name")}{" "}
            <input
              value={profile.deployment_name}
              required={profile.provider === "azure_openai"}
              onChange={(e) =>
                setProfile({ ...profile, deployment_name: e.target.value })
              }
            />
          </label>
          <label className="field">
            {t("Model / version reference")}{" "}
            <input
              value={profile.model_reference}
              onChange={(e) =>
                setProfile({ ...profile, model_reference: e.target.value })
              }
            />
          </label>
          <label className="field">
            {t("API version")}{" "}
            <input
              value={profile.api_version}
              required
              onChange={(e) =>
                setProfile({ ...profile, api_version: e.target.value })
              }
            />
          </label>
          <label className="field">
            {t("Authentication")}{" "}
            <select
              value={profile.auth_mode}
              onChange={(e) =>
                setProfile({ ...profile, auth_mode: e.target.value })
              }
            >
              <option value="managed_identity">{t("Managed identity")}</option>
              <option value="environment_reference">
                {t("Server environment reference")}{" "}
              </option>
            </select>
          </label>
          <p className="help">
            {t(
              "Key authentication reads PASSIT_AI_API_KEY on the server. Enter no secret values here.",
            )}{" "}
          </p>
          <label className="field">
            {t("Generation parameters (JSON)")}{" "}
            <textarea
              rows={3}
              value={parameters}
              onChange={(e) => setParameters(e.target.value)}
            />
          </label>
          <p className="help">
            {t(
              "Supported: max_completion_tokens or max_tokens, and temperature. Choose options your model accepts.",
            )}{" "}
          </p>
          <div className="field-row">
            <label className="field">
              {t("Request timeout")}{" "}
              <input
                type="number"
                min={1}
                max={60}
                value={profile.request_timeout_seconds}
                onChange={(e) =>
                  setProfile({
                    ...profile,
                    request_timeout_seconds: Number(e.target.value),
                  })
                }
              />
            </label>
            <label className="field">
              {t("Retries")}{" "}
              <input
                type="number"
                min={0}
                max={8}
                value={profile.max_retries}
                onChange={(e) =>
                  setProfile({
                    ...profile,
                    max_retries: Number(e.target.value),
                  })
                }
              />
            </label>
          </div>
          <button className="button primary full" disabled={busy}>
            {t("Create revision")} <Check size={17} />
          </button>
        </form>
      </div>
    </section>
  );
}
