import { useCallback, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Bell,
  Check,
  ChevronDown,
  Clock,
  Compass,
  Heart,
  LockKeyhole,
  Plus,
  Settings,
  Shuffle,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import { api, identity } from "./api";
import type { Chain, Config, Group, Me, Notice, Person, Turn } from "./api";
import Admin from "./Admin";

type Navigate = (route: string) => void;
type Action = (
  work: () => Promise<unknown>,
  message?: string,
) => Promise<boolean>;
const categories = [
  { id: "trending", label: "🔥 Trending" },
  { id: "new", label: "✨ New" },
  { id: "awkward", label: "😂 Awkward" },
  { id: "absurd", label: "🌀 Absurd" },
  { id: "twist", label: "🤯 Plot twists" },
];
const routeNow = () => window.location.hash.slice(1) || "discover";
let signinCallback: Promise<unknown> | undefined;

export function Avatar({
  person,
  small = false,
}: {
  person: Person;
  small?: boolean;
}) {
  return (
    <span
      className={`avatar ${small ? "small" : ""}`}
      style={{ background: person.color }}
      title={person.name}
    >
      {person.name.slice(0, 1)}
    </span>
  );
}
export function Empty({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export default function App() {
  const [route, setRoute] = useState(routeNow);
  const [config, setConfig] = useState<Config | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [accounts, setAccounts] = useState<Person[]>([]);
  const [loginOpen, setLoginOpen] = useState(false);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const refresh = () => setVersion((v) => v + 1);
  const navigate: Navigate = useCallback((path) => {
    window.location.hash = path;
    setRoute(path);
    window.scrollTo(0, 0);
  }, []);
  const action: Action = async (work, message) => {
    setError("");
    try {
      await work();
      refresh();
      if (message) setToast(message);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  };
  useEffect(() => {
    const changed = () => {
      setRoute(routeNow());
      setError("");
    };
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(""), 4000);
      return () => clearTimeout(timer);
    }
  }, [toast]);
  useEffect(() => {
    let alive = true;
    async function initialize() {
      try {
        if (window.location.pathname === "/auth/callback" && identity) {
          // React StrictMode can run initialization twice; consume the OIDC state once.
          signinCallback ??= identity.signinRedirectCallback();
          await signinCallback;
          window.history.replaceState({}, "", "/#chains");
          setRoute("chains");
        }
        const data = await api<Config>("/config");
        if (!alive) return;
        setConfig(data);
        if (data.mode === "demo")
          setAccounts(await api<Person[]>("/demo/accounts"));
        try {
          const user = await api<Me>("/me");
          if (alive) setMe(user);
        } catch {
          if (alive) setMe(null);
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
      } finally {
        if (alive) setReady(true);
      }
    }
    void initialize();
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (!me) {
      setNotices([]);
      return;
    }
    let alive = true;
    const load = () =>
      api<Notice[]>("/notifications")
        .then((data) => {
          if (alive) setNotices(data);
        })
        .catch(() => {});
    void load();
    const timer = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [me, version]);
  async function signIn(person: Person) {
    if (
      await action(async () => {
        await api("/demo/login", "POST", { user_id: person.id });
        setMe(await api<Me>("/me"));
      })
    )
      setLoginOpen(false);
  }
  function requireLogin(target?: string) {
    if (me) {
      if (target) navigate(target);
    } else if (config?.mode === "demo") setLoginOpen(true);
    else if (identity) void identity.signinRedirect();
    else setError("Sign-in has not been configured for this deployment.");
  }
  const unread = notices.filter((n) => !n.read).length;
  return (
    <>
      <header className="header">
        <div className="header-inner">
          <button
            className="brand"
            onClick={() => navigate("discover")}
            aria-label="PassIt home"
          >
            <span className="brand-icon">
              <ArrowUpRight size={23} />
            </span>
            pass<span>it</span>
            <i>®</i>
          </button>
          <nav aria-label="Main navigation">
            <button
              className={route === "discover" ? "active" : ""}
              onClick={() => navigate("discover")}
            >
              <Compass size={17} />
              Discover
            </button>
            <button
              className={route === "chains" ? "active" : ""}
              onClick={() => requireLogin("chains")}
            >
              <Shuffle size={17} />
              My chains
            </button>
            <button
              className={route === "groups" ? "active" : ""}
              onClick={() => requireLogin("groups")}
            >
              <Users size={17} />
              My people
            </button>
          </nav>
          <div className="header-actions">
            {me && (
              <button
                className="icon-button notification-button"
                aria-label="Notifications"
                onClick={() => {
                  setNoticeOpen(!noticeOpen);
                  if (!noticeOpen)
                    void action(() => api("/notifications/read", "POST"));
                }}
              >
                <Bell size={19} />
                {unread > 0 && <span className="dot" />}
              </button>
            )}
            <button
              className="button primary compact"
              onClick={() => requireLogin("create")}
            >
              <Plus size={17} />
              New chain
            </button>
            {me ? (
              <button
                className="profile-button"
                onClick={() => navigate("settings")}
                aria-label="Your settings"
              >
                <Avatar person={me} small />
              </button>
            ) : (
              <button className="text-button" onClick={() => requireLogin()}>
                Sign in <ArrowRight size={15} />
              </button>
            )}
          </div>
        </div>
      </header>
      {config?.mode === "demo" && (
        <div className="demo-bar">
          Local demo · fictional accounts & sample AI continuations{" "}
          <button onClick={() => setLoginOpen(true)}>
            {me ? `Playing as ${me.name} · Switch player` : "Choose a player"}{" "}
            <ChevronDown size={13} />
          </button>
        </div>
      )}
      {noticeOpen && (
        <div className="notification-panel">
          <div className="section-heading">
            <h3>Updates</h3>
            <button
              className="icon-button"
              aria-label="Close notifications"
              onClick={() => setNoticeOpen(false)}
            >
              <X size={18} />
            </button>
          </div>
          {notices.length ? (
            notices.map((n) => (
              <button
                key={n.id}
                onClick={() => {
                  navigate(`story/${n.chain_id}`);
                  setNoticeOpen(false);
                }}
              >
                {n.message}
                <ArrowRight size={14} />
              </button>
            ))
          ) : (
            <p>You’re all caught up.</p>
          )}
        </div>
      )}
      <main>
        {error && (
          <div className="alert" role="alert">
            {error}
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {!ready ? (
          <div className="loading">Getting the next chapter ready…</div>
        ) : !config ? (
          <Empty icon={<Shuffle />} title="Unable to connect">
            <p>Check that the API is running, then reload.</p>
          </Empty>
        ) : route.startsWith("story/") ? (
          <Story
            id={route.split("/")[1]}
            me={me}
            version={version}
            action={action}
            navigate={navigate}
            signIn={() => requireLogin()}
          />
        ) : route === "discover" ? (
          <Discover
            me={me}
            version={version}
            navigate={navigate}
            create={() => requireLogin("create")}
          />
        ) : !me ? (
          <Empty icon={<Users />} title="Your story starts here">
            <p>Sign in to create a Chain and play with friends.</p>
            <button className="button primary" onClick={() => requireLogin()}>
              Choose a player <ArrowRight size={17} />
            </button>
          </Empty>
        ) : route.startsWith("create") ? (
          <Create
            key={route}
            initialGroup={route.split("/")[1]}
            me={me}
            config={config}
            action={action}
            navigate={navigate}
          />
        ) : route === "groups" ? (
          <People
            me={me}
            version={version}
            action={action}
            navigate={navigate}
          />
        ) : route === "settings" ? (
          <Preferences
            me={me}
            setMe={setMe}
            action={action}
            navigate={navigate}
            switchPlayer={() => setLoginOpen(true)}
            demo={config.mode === "demo"}
          />
        ) : route === "admin" && me.admin ? (
          <Admin action={action} version={version} />
        ) : (
          <MyChains me={me} version={version} navigate={navigate} />
        )}
      </main>
      <footer>
        <span className="footer-brand">passit</span>
        <span>Stories nobody writes alone.</span>
        <span>Made for a little more unexpected.</span>
      </footer>
      {toast && (
        <div className="toast" role="status">
          <Check size={18} />
          {toast}
        </div>
      )}
      {loginOpen && (
        <div className="modal-backdrop" onClick={() => setLoginOpen(false)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="login-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close icon-button"
              aria-label="Close player picker"
              onClick={() => setLoginOpen(false)}
            >
              <X />
            </button>
            <span className="eyebrow">THE DEMO CAST</span>
            <h2 id="login-title">Who’s telling the story?</h2>
            <p>
              Switch between players to try a complete round. Each fictional
              account has its own turn and publication decision.
            </p>
            <div className="account-list">
              {accounts.map((person) => (
                <button
                  key={person.id}
                  aria-label={`Play as ${person.name}`}
                  onClick={() => void signIn(person)}
                >
                  <Avatar person={person} />
                  <span>{person.name}</span>
                  {me?.id === person.id ? (
                    <Check size={20} />
                  ) : (
                    <ArrowRight size={18} />
                  )}
                </button>
              ))}
            </div>
          </section>
        </div>
      )}
    </>
  );
}

function Discover({
  me,
  version,
  navigate,
  create,
}: {
  me: Me | null;
  version: number;
  navigate: Navigate;
  create: () => void;
}) {
  const [category, setCategory] = useState("trending");
  const [stories, setStories] = useState<Chain[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    setLoaded(false);
    setError("");
    api<Chain[]>(`/discover?category=${category}`)
      .then((data) => {
        if (alive) setStories(data);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, [category, version, me]);
  return (
    <>
      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">
            <span className="mini-star">✳</span> A LITTLE CHAOS. A GREAT STORY.
          </span>
          <h1>
            One story.
            <br />
            Many minds.
            <br />
            <em>Zero idea what’s next.</em>
          </h1>
          <p>
            Start with a sentence. Pass it to a friend.
            <br />
            See where a little collective imagination takes you.
          </p>
          <div className="hero-buttons">
            <button className="button primary" onClick={create}>
              Start a chain <ArrowUpRight size={19} />
            </button>
            <a
              className="text-button"
              href="#how-it-works"
              onClick={(e) => {
                e.preventDefault();
                document
                  .getElementById("how-it-works")
                  ?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              How it works <ArrowDown size={16} />
            </a>
          </div>
          <div className="hero-footnote">
            <span className="tiny-avatars">
              <i>A</i>
              <i>S</i>
              <i>J</i>
            </span>
            <span>Better stories. Together.</span>
          </div>
        </div>
        <div className="hero-art" aria-label="A story passes between friends">
          <div className="scribble">the plot thickens ↴</div>
          <article className="floating-card premise">
            <span className="paper-label">
              THE SETUP <span>01</span>
            </span>
            <p>“The hotel handed me a crown instead of a room key.”</p>
            <span className="paper-author">
              <i>A</i> Alex started something…
            </span>
          </article>
          <div className="pass-arrow">
            <ArrowDown size={38} />
          </div>
          <article className="floating-card continuation">
            <span className="motive-sticker">🤯 ADD A PLOT TWIST</span>
            <p>“Apparently, ‘king-sized’ wasn’t about the bed.”</p>
            <span className="paper-author">
              <i>S</i> Sam made it interesting.
            </span>
          </article>
          <div className="starburst">
            your
            <br />
            turn!
          </div>
          <span className="art-caption">
            Two minds. One very questionable holiday.
          </span>
        </div>
      </section>
      <section className="discover-section">
        <div className="section-heading">
          <div>
            <span className="eyebrow">
              STRAIGHT FROM THE COLLECTIVE IMAGINATION
            </span>
            <h2>The stories that made it.</h2>
          </div>
          <span className="subtle-label">
            <LockKeyhole size={14} />
            Shared only when everyone agrees
          </span>
        </div>
        <div className="tabs" role="tablist" aria-label="Story categories">
          {categories.map((c) => (
            <button
              role="tab"
              aria-selected={category === c.id}
              key={c.id}
              className={category === c.id ? "selected" : ""}
              onClick={() => setCategory(c.id)}
            >
              {c.label}
            </button>
          ))}
        </div>
        {!loaded ? (
          <div className="loading">Finding good stories…</div>
        ) : error ? (
          <div className="alert" role="alert">
            {error}
          </div>
        ) : stories.length ? (
          <div className="story-grid">
            {stories.map((story, i) => (
              <StoryCard
                key={story.id}
                story={story}
                index={i}
                navigate={navigate}
              />
            ))}
          </div>
        ) : (
          <Empty
            icon={<Sparkles size={26} />}
            title="The next great story could be yours."
          >
            <p>
              {category === "trending" || category === "new"
                ? "Finished Chains appear here once every player approves publication."
                : "No published stories in this category yet."}
            </p>
            <button className="text-button" onClick={create}>
              Get your friends in on it <ArrowRight size={16} />
            </button>
          </Empty>
        )}
      </section>
      <section className="how-it-works" id="how-it-works">
        <div>
          <span className="eyebrow">THE PLAN IS TO HAVE NO PLAN</span>
          <h2>
            A good story is
            <br />a group effort.
          </h2>
        </div>
        <div className="how-steps">
          <article>
            <span>01</span>
            <h3>Set the scene.</h3>
            <p>
              A curious sentence. A few friends. That’s all it takes to start a
              Chain.
            </p>
          </article>
          <article>
            <span>02</span>
            <h3>Follow the twist.</h3>
            <p>
              AI picks a comic direction. You add your part, then pass to a
              random friend.
            </p>
          </article>
          <article>
            <span>03</span>
            <h3>Enjoy the finale.</h3>
            <p>
              Everyone gets one contribution. Share the story when the whole
              group agrees.
            </p>
          </article>
        </div>
      </section>
    </>
  );
}

function StoryCard({
  story,
  index = 0,
  navigate,
}: {
  story: Chain;
  index?: number;
  navigate: Navigate;
}) {
  return (
    <button
      className={`story-card tone-${index % 4}`}
      onClick={() => navigate(`story/${story.id}`)}
    >
      <div className="card-top">
        <span className={`status ${story.your_turn ? "turn" : ""}`}>
          {story.your_turn
            ? "Your turn"
            : story.status === "active"
              ? "In progress"
              : story.visibility === "published"
                ? "Published"
                : "Finished · for your group"}
        </span>
        <ArrowUpRight size={20} />
      </div>
      <h3>{story.title}</h3>
      <p>“{story.setup}”</p>
      <div className="card-meta">
        <span>
          <Users size={15} />
          {story.participant_count} players
        </span>
        <span>
          <Heart size={15} />
          {story.likes}
        </span>
        <span>
          <Shuffle size={15} />
          {story.pass_count} passes
        </span>
      </div>
      {story.status === "active" && (
        <div className="progress">
          <span
            style={{
              width: `${(100 * story.completed_contributions) / story.participant_count}%`,
            }}
          />
        </div>
      )}
    </button>
  );
}

function MyChains({
  me,
  version,
  navigate,
}: {
  me: Me;
  version: number;
  navigate: Navigate;
}) {
  const [chains, setChains] = useState<Chain[]>([]);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api<Chain[]>("/chains")
        .then((data) => {
          if (alive) {
            setChains(data);
            setLoaded(true);
          }
        })
        .catch((e) => {
          if (alive) setError(e.message);
        });
    void load();
    const timer = setInterval(load, 4000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [me, version]);
  const shown = chains.filter(
    (c) =>
      filter === "all" ||
      (filter === "turn" && c.your_turn) ||
      (filter === "active" && c.status === "active") ||
      (filter === "completed" && c.status === "completed"),
  );
  return (
    <section className="page">
      <div className="section-heading">
        <div>
          <span className="eyebrow">YOUR LITTLE CORNER OF CHAOS</span>
          <h1>
            Hey, {me.name}. <em>What’s the story?</em>
          </h1>
          <p>Pick up where your friends left off, or start something new.</p>
        </div>
        <button className="button primary" onClick={() => navigate("create")}>
          <Plus size={18} />
          New chain
        </button>
      </div>
      <div className="tabs">
        {[
          ["all", "All chains"],
          ["turn", "Your turn"],
          ["active", "In progress"],
          ["completed", "Finished"],
        ].map(([id, label]) => (
          <button
            key={id}
            className={filter === id ? "selected" : ""}
            onClick={() => setFilter(id)}
          >
            {label}
            {id === "turn" && (
              <span className="count">
                {chains.filter((c) => c.your_turn).length}
              </span>
            )}
          </button>
        ))}
      </div>
      {error ? (
        <div className="alert">{error}</div>
      ) : !loaded ? (
        <div className="loading">Loading your chains…</div>
      ) : shown.length ? (
        <div className="story-grid">
          {shown.map((c, i) => (
            <StoryCard key={c.id} story={c} index={i} navigate={navigate} />
          ))}
        </div>
      ) : (
        <Empty
          icon={<Shuffle size={27} />}
          title={
            filter === "turn"
              ? "The story is in someone else’s hands."
              : "Every good story starts somewhere."
          }
        >
          <p>
            {filter === "turn"
              ? "We’ll let you know when it’s your turn."
              : "Create a Chain and see what your friends come up with."}
          </p>
          <button className="button primary" onClick={() => navigate("create")}>
            Start a chain <ArrowRight size={17} />
          </button>
        </Empty>
      )}
    </section>
  );
}

function Create({
  me,
  config,
  action,
  navigate,
  initialGroup,
}: {
  me: Me;
  config: Config;
  action: Action;
  navigate: Navigate;
  initialGroup?: string;
}) {
  const [friends, setFriends] = useState<Person[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [mode, setMode] = useState("friends");
  const [group, setGroup] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [setup, setSetup] = useState("");
  const [rules, setRules] = useState("");
  const [minimum, setMinimum] = useState(2);
  const [maximum, setMaximum] = useState(
    Math.min(5, config.global_max_participants),
  );
  const [minutes, setMinutes] = useState(15);
  const [busy, setBusy] = useState(false);
  const [helping, setHelping] = useState(false);
  useEffect(() => {
    void action(async () => {
      const [f, g] = await Promise.all([
        api<{ friends: Person[] }>("/friends"),
        api<Group[]>("/groups"),
      ]);
      setFriends(f.friends);
      setGroups(g);
      if (initialGroup) {
        setMode("saved_group");
        setGroup(initialGroup);
        setMembers(
          g
            .find((group) => group.id === initialGroup)
            ?.members.filter((p) => p.id !== me.id)
            .map((p) => p.id) || [],
        );
      }
    });
  }, [me.id, initialGroup]);
  function chooseMode(next: string) {
    setMode(next);
    setMembers([]);
    setGroup("");
  }
  function chooseGroup(id: string) {
    setGroup(id);
    setMembers(
      groups
        .find((g) => g.id === id)
        ?.members.filter((p) => p.id !== me.id)
        .map((p) => p.id) || [],
    );
  }
  const available =
    mode === "saved_group"
      ? groups
          .find((g) => g.id === group)
          ?.members.filter((p) => p.id !== me.id) || []
      : friends;
  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    await action(async () => {
      const chain = await api<Chain>("/chains", "POST", {
        setup,
        rules,
        group_mode: mode,
        source_group_id: mode === "saved_group" ? group : null,
        member_ids: mode === "random" ? [] : members,
        min_participants: minimum,
        max_participants: maximum,
        turn_timeout_seconds: Math.round(minutes * 60),
      });
      navigate(`story/${chain.id}`);
    }, "Your Chain is off and running.");
    setBusy(false);
  }
  return (
    <section className="page narrow">
      <button className="back-link" onClick={() => navigate("chains")}>
        <ArrowLeft size={16} />
        My chains
      </button>
      <span className="eyebrow">SET SOMETHING IN MOTION</span>
      <h1>
        A sentence is <em>all it takes.</em>
      </h1>
      <p className="page-intro">
        You set the scene. Your friends take it somewhere unexpected.
      </p>
      <form onSubmit={send} className="create-layout">
        <div className="form-main">
          <section className="panel">
            <label htmlFor="setup" className="field-heading">
              <span className="step-number" aria-hidden="true">
                1
              </span>
              Set the scene
            </label>
            <p className="field-description">
              Give everyone a jumping-off point. Keep it short and leave room
              for trouble.
            </p>
            <textarea
              id="setup"
              required
              maxLength={1500}
              value={setup}
              onChange={(e) => setSetup(e.target.value)}
              placeholder="I woke up in a hotel room and had no idea how I got there…"
              rows={5}
            />
            <div className="textarea-footer">
              <button
                type="button"
                className="text-button"
                disabled={helping}
                onClick={async () => {
                  setHelping(true);
                  await action(async () => {
                    const result = await api<{ setup: string }>(
                      "/setup-assistance",
                      "POST",
                      {},
                    );
                    setSetup(result.setup);
                  });
                  setHelping(false);
                }}
              >
                <Sparkles size={15} />
                {helping ? "Finding a premise…" : "Give me a starting point"}
              </button>
              <span>{setup.length}/1500</span>
            </div>
            <p className="help">
              Your setup is your contribution. AI creates the title after the
              first pass.
            </p>
          </section>
          <section className="panel">
            <h2 className="field-heading">
              <span className="step-number">2</span>Bring your people
            </h2>
            <div className="segmented">
              {[
                ["friends", "Friends"],
                ["saved_group", "Saved group"],
                ["random", "Surprise me"],
              ].map(([id, label]) => (
                <button
                  type="button"
                  className={mode === id ? "selected" : ""}
                  key={id}
                  onClick={() => chooseMode(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            {mode === "saved_group" && (
              <label className="field">
                Your group
                <select
                  required
                  value={group}
                  onChange={(e) => chooseGroup(e.target.value)}
                >
                  <option value="">Choose a group</option>
                  {groups.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name} · {g.members.length} people
                    </option>
                  ))}
                </select>
              </label>
            )}
            {mode === "random" ? (
              <div className="info-box">
                <Shuffle size={24} />
                <p>
                  We’ll randomly choose up to {maximum - 1} other players who
                  have opted in. Your story stays within the group.
                </p>
              </div>
            ) : (
              <>
                <div className="people-picker">
                  {available.map((person) => (
                    <label
                      key={person.id}
                      className={members.includes(person.id) ? "checked" : ""}
                    >
                      <Avatar person={person} small />
                      <span>{person.name}</span>
                      <input
                        type="checkbox"
                        checked={members.includes(person.id)}
                        onChange={(e) =>
                          setMembers(
                            e.target.checked
                              ? [...members, person.id]
                              : members.filter((id) => id !== person.id),
                          )
                        }
                      />
                    </label>
                  ))}
                </div>
                {!available.length && (
                  <p className="help">
                    {mode === "friends"
                      ? "Add friends in My people, or try a random group."
                      : "Choose or create a saved group in My people."}
                  </p>
                )}
                <p className="help">
                  {members.length + 1} players, including you · Everyone joins
                  immediately, with no invitations.
                </p>
              </>
            )}
          </section>
        </div>
        <aside>
          <section className="panel">
            <h2 className="field-heading">
              <span className="step-number">3</span>The ground rules
            </h2>
            <label className="field">
              Minutes per turn
              <input
                type="number"
                min="0.0167"
                max="10080"
                step="any"
                value={minutes}
                onChange={(e) => setMinutes(Number(e.target.value))}
                required
              />
            </label>
            <div className="field-row">
              <label className="field">
                Min. players
                <input
                  type="number"
                  min={2}
                  max={maximum}
                  value={minimum}
                  onChange={(e) => setMinimum(Number(e.target.value))}
                  required
                />
              </label>
              <label className="field">
                Max. players
                <input
                  type="number"
                  min={minimum}
                  max={config.global_max_participants}
                  value={maximum}
                  onChange={(e) => setMaximum(Number(e.target.value))}
                  required
                />
              </label>
            </div>
            <label className="field">
              House rules <span className="optional">optional</span>
              <textarea
                rows={3}
                maxLength={500}
                placeholder="Keep it PG. Bonus points for callbacks."
                value={rules}
                onChange={(e) => setRules(e.target.value)}
              />
            </label>
            <div className="rules-note">
              <LockKeyhole size={17} />
              <p>
                Your story is for the group. It only becomes public if everyone
                agrees after the finale.
              </p>
            </div>
            <button
              type="submit"
              className="button primary full"
              disabled={
                busy || !setup.trim() || (mode === "saved_group" && !group)
              }
            >
              {busy ? "Launching…" : "Launch & pass"}
              <ArrowRight size={17} />
            </button>
            <p className="help centered">
              One contribution each. Random passes.
              <br />A prepared AI fallback if someone times out.
            </p>
          </section>
        </aside>
      </form>
    </section>
  );
}

function Story({
  id,
  me,
  version,
  action,
  navigate,
  signIn,
}: {
  id: string;
  me: Me | null;
  version: number;
  action: Action;
  navigate: Navigate;
  signIn: () => void;
}) {
  const [chain, setChain] = useState<Chain | null>(null);
  const [error, setError] = useState("");
  const [clock, setClock] = useState(Date.now());
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    setChain(null);
    setError("");
  }, [id, me?.id]);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api<Chain>(`/chains/${id}`)
        .then((data) => {
          if (alive) {
            setChain(data);
            setOffset(Date.parse(data.server_time) - Date.now());
            setError("");
          }
        })
        .catch((e) => {
          if (alive) setError(e.message);
        });
    void load();
    const timer = setInterval(load, 3000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id, me?.id, version]);
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  if (error)
    return (
      <Empty
        icon={<LockKeyhole size={26} />}
        title="This story is staying with its people."
      >
        <p>{error}</p>
        <button
          className="button secondary"
          onClick={() => navigate("discover")}
        >
          Back to Discover
        </button>
      </Empty>
    );
  if (!chain) return <div className="loading">Unfolding the story…</div>;
  const active = chain.turns.find((t) => t.status !== "submitted");
  const seconds = active
    ? Math.max(
        0,
        Math.ceil((Date.parse(active.deadline_at) - clock - offset) / 1000),
      )
    : 0;
  const mine = !!active && active.user.id === me?.id;
  const approval = chain.approvals.find((a) => a.user_id === me?.id);
  const approved = chain.approvals.filter(
    (a) => a.decision === "approved",
  ).length;
  const like = (target: string, targetId: string, liked: boolean) =>
    me
      ? action(() =>
          api(`/likes/${target}/${targetId}`, liked ? "DELETE" : "PUT"),
        )
      : (signIn(), Promise.resolve(false));
  return (
    <section className="page story-page">
      <button
        className="back-link"
        onClick={() => navigate(chain.is_participant ? "chains" : "discover")}
      >
        <ArrowLeft size={16} />
        {chain.is_participant ? "My chains" : "Discover"}
      </button>
      <div className="story-heading">
        <span className="eyebrow">
          {chain.visibility === "published"
            ? "A STORY FROM THE COLLECTIVE IMAGINATION"
            : "JUST BETWEEN YOUR PEOPLE"}
        </span>
        <h1>{chain.title}</h1>
        <div className="story-meta">
          <span>
            <Users size={16} />
            {chain.participant_count} players
          </span>
          <span>
            <Shuffle size={16} />
            {chain.pass_count} passes
          </span>
          <span>
            <LockKeyhole size={16} />
            {chain.visibility === "published"
              ? "Published"
              : "Participants only"}
          </span>
          <button
            className={`like-button ${chain.liked ? "liked" : ""}`}
            onClick={() => void like("chains", id, chain.liked)}
            aria-label={chain.liked ? "Unlike chain" : "Like chain"}
          >
            <Heart size={17} fill={chain.liked ? "currentColor" : "none"} />
            {chain.likes}
          </button>
        </div>
      </div>
      <div className="story-layout">
        <div className="story-content">
          <article className="story-entry setup-entry">
            <div className="entry-heading">
              <span className="story-step">01</span>
              <span className="eyebrow">THE SETUP</span>
              {chain.creator && (
                <span className="entry-author">
                  <Avatar person={chain.creator} small />
                  {chain.creator.name}
                </span>
              )}
            </div>
            <p>{chain.setup}</p>
          </article>
          {chain.turns
            .filter((t) => t.status === "submitted")
            .map((turn) => (
              <article className="story-entry" key={turn.id}>
                <div className="entry-heading">
                  <span className="story-step">
                    {String(turn.position + 1).padStart(2, "0")}
                  </span>
                  <span className={`motive motive-${turn.motive.id}`}>
                    {turn.motive.emoji} {turn.motive.label}
                  </span>
                  <span className="entry-author">
                    <Avatar person={turn.user} small />
                    {turn.user.name}
                  </span>
                </div>
                <p>{turn.text}</p>
                <div className="entry-footer">
                  <span>
                    {turn.ai_generated
                      ? "AI-generated · participant timed out"
                      : turn.ai_assisted
                        ? "Written with an AI suggestion"
                        : "A human plot development"}
                  </span>
                  <button
                    className={`like-button ${turn.liked ? "liked" : ""}`}
                    onClick={() => void like("turns", turn.id, turn.liked)}
                    aria-label={`${turn.liked ? "Unlike" : "Like"} turn ${turn.position}`}
                  >
                    <Heart
                      size={16}
                      fill={turn.liked ? "currentColor" : "none"}
                    />
                    {turn.likes}
                  </button>
                </div>
              </article>
            ))}
          {chain.status === "active" ? (
            active ? (
              mine && seconds > 0 ? (
                <Composer
                  key={active.id}
                  turn={active}
                  seconds={seconds}
                  chainId={id}
                  action={action}
                />
              ) : (
                <div className="waiting-card">
                  <div className="empty-icon">
                    <Clock size={25} />
                  </div>
                  <h3>
                    {seconds === 0
                      ? "The deadline has passed."
                      : `${active.user.name} has the next chapter.`}
                  </h3>
                  <p>
                    {seconds === 0
                      ? "The prepared AI suggestion will complete this turn. If preparation is delayed, the story waits for it."
                      : `Their direction: ${active.motive.emoji} ${active.motive.label.toLowerCase()}.`}
                  </p>
                  {seconds > 0 && (
                    <span className="timer">
                      <Clock size={14} />
                      {Math.floor(seconds / 60)}:
                      {String(seconds % 60).padStart(2, "0")} remaining
                    </span>
                  )}
                </div>
              )
            ) : (
              <div className="waiting-card">
                <Sparkles />
                <h3>The next pass is being prepared.</h3>
                <p>
                  The system is assigning a Motive and randomly choosing the
                  next player.
                </p>
              </div>
            )
          ) : (
            <div className="finale">
              <span>✳</span>
              <h2>And that’s a wrap.</h2>
              <p>
                {chain.participant_count} minds. One story that nobody could
                have written alone.
              </p>
            </div>
          )}
        </div>
        <aside className="story-aside">
          <section className="panel">
            <span className="eyebrow">THE CAST</span>
            <h3>Good company.</h3>
            <div className="cast-list">
              {chain.participants.map((p) => (
                <div key={p.id}>
                  <Avatar person={p} small />
                  <span>
                    {p.name}
                    {p.id === me?.id && <small> (you)</small>}
                  </span>
                  {p.contributed ? (
                    <Check size={16} />
                  ) : active?.user.id === p.id ? (
                    <span className="dot active-dot" />
                  ) : (
                    <span className="cast-wait">soon</span>
                  )}
                </div>
              ))}
            </div>
            {chain.rules && (
              <div className="house-rules">
                <span className="eyebrow">HOUSE RULES</span>
                <p>{chain.rules}</p>
              </div>
            )}
          </section>
          {chain.status === "completed" && (
            <section className="panel publication-panel">
              <span className="eyebrow">THE NEXT CHAPTER</span>
              <h3>
                {chain.visibility === "published"
                  ? "Out in the world."
                  : chain.publication_status === "rejected"
                    ? "A story just for you."
                    : "Worth sharing?"}
              </h3>
              <p>
                {chain.visibility === "published"
                  ? "Every player approved. Your story is now in Discover."
                  : chain.publication_status === "rejected"
                    ? "A participant declined publication. This story stays with the group."
                    : "Publishing puts the full story in Discover. Every player must explicitly approve."}
              </p>
              {chain.is_participant &&
                chain.publication_status === "not_requested" && (
                  <button
                    className="button primary full"
                    onClick={() =>
                      void action(
                        () =>
                          api(`/chains/${id}/publication`, "POST", {
                            decision: "request",
                          }),
                        "Your publication approval is recorded.",
                      )
                    }
                  >
                    Request publication
                    <ArrowUpRight size={16} />
                  </button>
                )}
              {chain.publication_status === "awaiting_approvals" && (
                <>
                  <div className="approval-count">
                    {approved} of {chain.participant_count} approved
                  </div>
                  {approval?.decision === "pending" ? (
                    <div className="approval-buttons">
                      <button
                        className="button primary"
                        onClick={() =>
                          void action(
                            () =>
                              api(`/chains/${id}/publication`, "POST", {
                                decision: "approved",
                              }),
                            "Your approval is recorded.",
                          )
                        }
                      >
                        Approve
                      </button>
                      <button
                        className="button secondary"
                        onClick={() =>
                          void action(
                            () =>
                              api(`/chains/${id}/publication`, "POST", {
                                decision: "rejected",
                              }),
                            "The story will stay within the group.",
                          )
                        }
                      >
                        Decline
                      </button>
                    </div>
                  ) : (
                    <p className="help">
                      Your approval is recorded. Waiting for the others.
                    </p>
                  )}
                </>
              )}
              {chain.visibility === "published" && (
                <button
                  className="button secondary full"
                  onClick={() =>
                    void action(
                      () => navigator.clipboard.writeText(window.location.href),
                      "Story link copied.",
                    )
                  }
                >
                  Copy story link <ArrowUpRight size={16} />
                </button>
              )}
            </section>
          )}
          <div className="sidebar-note">
            <Sparkles size={18} />
            <p>
              One contribution each.
              <br />
              The system chooses the next player.
              <br />
              Every completed line stays.
            </p>
          </div>
        </aside>
      </div>
    </section>
  );
}

function Composer({
  turn,
  seconds,
  chainId,
  action,
}: {
  turn: Turn;
  seconds: number;
  chainId: string;
  action: Action;
}) {
  const [text, setText] = useState("");
  const [assisted, setAssisted] = useState(false);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    await action(
      () =>
        api(`/chains/${chainId}/turns/${turn.id}/submit`, "POST", {
          text,
          ai_assisted: assisted,
        }),
      "Your contribution is saved. Passing it on…",
    );
    setBusy(false);
  }
  return (
    <form className="composer" onSubmit={submit}>
      <div className="section-heading">
        <span className="eyebrow">THE STORY IS IN YOUR HANDS</span>
        <span className={`timer ${seconds < 60 ? "urgent" : ""}`}>
          <Clock size={14} />
          {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
        </span>
      </div>
      <h2>
        Your turn. <em>{turn.motive.label}.</em>
      </h2>
      <label className="sr-only" htmlFor="contribution">
        Your contribution
      </label>
      <textarea
        id="contribution"
        rows={5}
        required
        maxLength={1500}
        placeholder="And then…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="textarea-footer">
        <span>
          {assisted
            ? "Using an AI suggestion · edit it however you like"
            : "Your words. Your unexpected twist."}
        </span>
        <span>{text.length}/1500</span>
      </div>
      <div className="suggestions">
        <span className="eyebrow">
          <Sparkles size={14} />A LITTLE INSPIRATION
        </span>
        {turn.suggestions ? (
          turn.suggestions.map((suggestion, i) => (
            <button
              type="button"
              key={i}
              onClick={() => {
                setText(suggestion);
                setAssisted(true);
              }}
            >
              {suggestion}
              <Plus size={16} />
            </button>
          ))
        ) : (
          <p className="help">
            Suggestions are being prepared. You can write independently.
          </p>
        )}
      </div>
      <div className="composer-bottom">
        <p>
          If your timer runs out, a prepared AI suggestion will be submitted and
          labeled automatically.
        </p>
        <button
          className="button primary"
          disabled={busy || !text.trim()}
          type="submit"
        >
          {busy ? "Passing…" : "Submit & Pass"}
          <ArrowRight size={17} />
        </button>
      </div>
    </form>
  );
}

function People({
  me,
  version,
  action,
  navigate,
}: {
  me: Me;
  version: number;
  action: Action;
  navigate: Navigate;
}) {
  const [friends, setFriends] = useState<Person[]>([]);
  const [requests, setRequests] = useState<(Person & { incoming: boolean })[]>(
    [],
  );
  const [groups, setGroups] = useState<Group[]>([]);
  const [editing, setEditing] = useState<Group | "new" | null>(null);
  const [name, setName] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Person[]>([]);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  useEffect(() => {
    let alive = true;
    Promise.all([
      api<{ friends: Person[]; requests: (Person & { incoming: boolean })[] }>(
        "/friends",
      ),
      api<Group[]>("/groups"),
    ])
      .then(([f, g]) => {
        if (alive) {
          setFriends(f.friends);
          setRequests(f.requests);
          setGroups(g);
          setLoadError("");
        }
      })
      .catch((e) => {
        if (alive) setLoadError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [me.id, version]);
  function edit(group: Group | "new") {
    setEditing(group);
    setName(group === "new" ? "" : group.name);
    setMembers(
      group === "new"
        ? []
        : group.members.filter((p) => p.id !== me.id).map((p) => p.id),
    );
  }
  return (
    <section className="page">
      <span className="eyebrow">THE BEST STORIES HAVE A GOOD CAST</span>
      <h1>
        Your people. <em>Your possibilities.</em>
      </h1>
      <p className="page-intro">
        Keep your favorite collaborators close. Saved groups make the next Chain
        easy.
      </p>
      <div className="section-heading">
        <h2>Saved groups</h2>
        <button className="button secondary" onClick={() => edit("new")}>
          <Plus size={17} />
          New group
        </button>
      </div>
      <div className="group-grid">
        {groups.map((g) => (
          <article className="panel group-card" key={g.id}>
            <div className="group-symbol">
              <Users size={24} />
            </div>
            <h3>{g.name}</h3>
            <div className="group-avatars">
              {g.members.map((p) => (
                <Avatar person={p} small key={p.id} />
              ))}
            </div>
            <p>{g.members.map((p) => p.name).join(", ")}</p>
            <div className="group-actions">
              <button
                className="text-button"
                onClick={() => navigate(`create/${g.id}`)}
              >
                Start a chain
                <ArrowUpRight size={16} />
              </button>
              {g.owner_id === me.id ? (
                <button className="text-button muted" onClick={() => edit(g)}>
                  Edit
                </button>
              ) : (
                <button
                  className="text-button muted"
                  onClick={() =>
                    void action(
                      () => api(`/groups/${g.id}/membership`, "DELETE"),
                      "You left the saved group.",
                    )
                  }
                >
                  Leave
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
      {!groups.length && (
        <p className="help">
          No saved groups yet. Choose friends and give your group a name.
        </p>
      )}
      {loadError && (
        <div className="alert" role="alert">
          {loadError}
        </div>
      )}
      <section className="panel friends-panel">
        <div className="section-heading">
          <h2>
            Friends <span className="count">{friends.length}</span>
          </h2>
        </div>
        <div className="friend-grid">
          {friends.map((person) => (
            <div key={person.id}>
              <Avatar person={person} />
              <span>{person.name}</span>
              <button
                className="text-button muted"
                onClick={() =>
                  void action(
                    () => api(`/friends/${person.id}`, "DELETE"),
                    "Friend removed. Existing Chains stay intact.",
                  )
                }
              >
                Remove
              </button>
            </div>
          ))}
        </div>
        <form
          className="search-form"
          onSubmit={async (e) => {
            e.preventDefault();
            await action(async () =>
              setResults(
                await api<Person[]>(`/users?q=${encodeURIComponent(query)}`),
              ),
            );
          }}
        >
          <label className="sr-only" htmlFor="friend-search">
            Search people by name
          </label>
          <input
            id="friend-search"
            placeholder="Find a friend by name…"
            minLength={2}
            maxLength={80}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            required
          />
          <button className="button secondary">Find people</button>
        </form>
        {results.map((p) => (
          <div className="search-result" key={p.id}>
            <Avatar person={p} small />
            <span>{p.name}</span>
            {friends.some((f) => f.id === p.id) ? (
              <span className="help">Already friends</span>
            ) : (
              <button
                className="text-button"
                onClick={() =>
                  void action(
                    () => api("/friends", "POST", { user_id: p.id }),
                    "Friend request sent.",
                  )
                }
              >
                Add friend <Plus size={14} />
              </button>
            )}
          </div>
        ))}
        {requests.length > 0 && (
          <div className="friend-requests">
            <h3>Friend requests</h3>
            {requests.map((p) => (
              <div className="search-result" key={p.id}>
                <Avatar person={p} small />
                <span>{p.name}</span>
                {p.incoming ? (
                  <>
                    <button
                      className="text-button"
                      onClick={() =>
                        void action(
                          () =>
                            api(`/friends/${p.id}/respond`, "POST", {
                              accept: true,
                            }),
                          "Friend added.",
                        )
                      }
                    >
                      Accept
                    </button>
                    <button
                      className="text-button muted"
                      onClick={() =>
                        void action(() =>
                          api(`/friends/${p.id}/respond`, "POST", {
                            accept: false,
                          }),
                        )
                      }
                    >
                      Decline
                    </button>
                  </>
                ) : (
                  <span className="help">Request sent</span>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
      {editing && (
        <div className="modal-backdrop">
          <form
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="group-title"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              if (
                await action(
                  () =>
                    api(
                      editing === "new" ? "/groups" : `/groups/${editing.id}`,
                      editing === "new" ? "POST" : "PUT",
                      { name, member_ids: members },
                    ),
                  "Group saved.",
                )
              )
                setEditing(null);
              setBusy(false);
            }}
          >
            <button
              type="button"
              className="modal-close icon-button"
              aria-label="Close group editor"
              onClick={() => setEditing(null)}
            >
              <X />
            </button>
            <h2 id="group-title">
              {editing === "new"
                ? "Bring the cast together."
                : "A little cast adjustment."}
            </h2>
            <label className="field">
              Group name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={80}
              />
            </label>
            <div className="people-picker">
              {friends.map((p) => (
                <label key={p.id}>
                  <Avatar person={p} small />
                  <span>{p.name}</span>
                  <input
                    type="checkbox"
                    checked={members.includes(p.id)}
                    onChange={(e) =>
                      setMembers(
                        e.target.checked
                          ? [...members, p.id]
                          : members.filter((id) => id !== p.id),
                      )
                    }
                  />
                </label>
              ))}
            </div>
            <p className="help">
              You’re included as the owner. Changes apply to future Chains.
            </p>
            <button className="button primary full" disabled={busy}>
              Save group <Check size={17} />
            </button>
          </form>
        </div>
      )}
    </section>
  );
}

function Preferences({
  me,
  setMe,
  action,
  navigate,
  switchPlayer,
  demo,
}: {
  me: Me;
  setMe: (value: Me | null) => void;
  action: Action;
  navigate: Navigate;
  switchPlayer: () => void;
  demo: boolean;
}) {
  const [preferences, setPreferences] = useState(me.settings);
  const [busy, setBusy] = useState(false);
  return (
    <section className="page narrow settings-page">
      <span className="eyebrow">MAKE YOURSELF AT HOME</span>
      <h1>Your settings.</h1>
      <form
        className="panel"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          await action(async () => {
            await api("/me/settings", "PUT", preferences);
            setMe(await api<Me>("/me"));
          }, "Preferences saved.");
          setBusy(false);
        }}
      >
        <div className="settings-person">
          <Avatar person={me} />
          <h3>{me.name}</h3>
        </div>
        <label className="toggle-field">
          <div>
            <h3>Allow random group participation</h3>
            <p>
              Other players can automatically include you in randomly formed
              Chains. No invitation or acceptance step.
            </p>
          </div>
          <input
            type="checkbox"
            checked={preferences.allow_random_participation}
            onChange={(e) =>
              setPreferences({
                ...preferences,
                allow_random_participation: e.target.checked,
              })
            }
          />
        </label>
        <label className="toggle-field">
          <div>
            <h3>In-app notifications</h3>
            <p>
              Hear about new Chains, your turn, finales, and publication
              requests.
            </p>
          </div>
          <input
            type="checkbox"
            checked={preferences.notifications_enabled}
            onChange={(e) =>
              setPreferences({
                ...preferences,
                notifications_enabled: e.target.checked,
              })
            }
          />
        </label>
        <label className="field">
          Language
          <select
            value={preferences.language}
            onChange={(e) =>
              setPreferences({ ...preferences, language: e.target.value })
            }
          >
            <option value="en">English</option>
          </select>
        </label>
        <button className="button primary" disabled={busy}>
          Save preferences
          <Check size={16} />
        </button>
      </form>
      <div className="settings-actions">
        {demo && (
          <button className="button secondary" onClick={switchPlayer}>
            <Users size={17} />
            Switch demo player
          </button>
        )}
        {me.admin && (
          <button
            className="button secondary"
            onClick={() => navigate("admin")}
          >
            <Settings size={17} />
            Admin configuration
          </button>
        )}
        <button
          className="text-button"
          onClick={() =>
            void action(async () => {
              await api("/logout", "POST");
              if (identity) await identity.removeUser();
              setMe(null);
              navigate("discover");
            }, "Signed out.")
          }
        >
          Sign out
          <ArrowRight size={16} />
        </button>
      </div>
    </section>
  );
}
