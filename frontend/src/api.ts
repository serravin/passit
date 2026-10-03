import type { Language } from "./i18n";
import { UserManager, WebStorageStateStore } from "oidc-client-ts";

const base = import.meta.env.VITE_API_URL || "";
const authority =
  window.passitConfig?.authority || import.meta.env.VITE_OIDC_AUTHORITY;
export const identity = authority
  ? new UserManager({
      authority,
      client_id:
        window.passitConfig?.clientId || import.meta.env.VITE_OIDC_CLIENT_ID,
      redirect_uri: `${window.location.origin}/auth/callback`,
      post_logout_redirect_uri: window.location.origin,
      response_type: "code",
      scope:
        window.passitConfig?.scope ||
        import.meta.env.VITE_OIDC_SCOPE ||
        "openid profile",
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    })
  : null;

export const accountBlockedMessage = "Your account has been blocked";

export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const user = await identity?.getUser();
  const response = await fetch(base + "/api" + path, {
    method,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(user && !user.expired
        ? { Authorization: `Bearer ${user.access_token}` }
        : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json();
  if (!response.ok) {
    const message =
      typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
          ? "Please check the form and try again."
          : "Something went wrong";
    if (
      response.status === 403 &&
      message === accountBlockedMessage &&
      path !== "/demo/login"
    )
      window.dispatchEvent(new Event("passit:account-blocked"));
    throw new Error(message);
  }
  return data;
}

export type Person = { id: string; name: string; color: string };
export type Me = Person & {
  admin: boolean;
  settings: {
    allow_random_participation: boolean;
    notifications_enabled: boolean;
    language: Language;
  };
};
export type Motive = { id: string; label: string; emoji: string };
export type Config = {
  mode: string;
  global_max_participants: number;
  motives: Motive[];
};
export type Group = {
  id: string;
  name: string;
  owner_id: string;
  members: Person[];
};
export type Turn = {
  id: string;
  position: number;
  user: Person;
  motive: Motive;
  status: string;
  text: string | null;
  deadline_at: string;
  ai_assisted: boolean;
  ai_generated: boolean;
  suggestions?: string[] | null;
  likes: number;
  liked: boolean;
};
export type Chain = {
  id: string;
  title: string;
  title_pending: boolean;
  setup: string;
  setup_ai_assisted: boolean | null;
  rules: string;
  creator_id: string;
  creator?: Person;
  created_at: string;
  status: string;
  visibility: string;
  publication_status: string;
  participant_count: number;
  completed_contributions: number;
  pass_count: number;
  your_turn: boolean;
  is_participant: boolean;
  motive_ids: string[];
  likes: number;
  liked: boolean;
  server_time: string;
  turns: Turn[];
  participants: (Person & { contributed: boolean })[];
  approvals: { user_id: string; decision: string }[];
};
export type Notice = {
  id: string;
  chain_id: string;
  message: string;
  read: boolean;
};

export type AccountNotice = {
  id: string;
  kind: string;
  source: string;
  categories: string[];
  created_at: string;
};
export type AccountStatus = {
  user_id: string;
  blocked_at: string | null;
  notices: AccountNotice[];
};
