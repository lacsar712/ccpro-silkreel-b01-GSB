import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { api, clearToken, setToken, token } from "./api.js";
import "./app.css";

const STATUS_LABEL = { soaking: "浸茧", reeling: "缫丝中", reeled: "已缫完" };

function useHashRoute() {
  const [route, setRoute] = useState(window.location.hash || "#/yard");
  useEffect(() => {
    const onChange = () => setRoute(window.location.hash || "#/yard");
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

function logout() {
  clearToken();
  window.location.hash = "#/yard";
  window.location.reload();
}

function TopBar({ route }) {
  return (
    <div class="topbar">
      <nav class="nav">
        <a href="#/yard" class={route.startsWith("#/yard") ? "active" : ""}>
          环盆作业台
        </a>
        <a href="#/valve" class={route.startsWith("#/valve") ? "active" : ""}>
          蒸汽总阀
        </a>
      </nav>
      <button onClick={logout}>退出</button>
    </div>
  );
}

function Login({ onOk }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("123456");
  const [err, setErr] = useState("");
  async function submit(e) {
    e.preventDefault();
    setErr("");
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setToken(data.access_token);
      onOk(data.user);
    } catch (ex) {
      setErr(ex.message);
    }
  }
  return (
    <div class="login">
      <h1>江口缫丝坞</h1>
      <p>汤温环盆作业台，不是列表台账。</p>
      <form onSubmit={submit} autocomplete="off">
        <label>
          用户名
          <input name="username" autocomplete="off" value={username} onInput={(e) => setUsername(e.target.value)} />
        </label>
        <label>
          密码
          <input name="password" type="password" autocomplete="off" value={password} onInput={(e) => setPassword(e.target.value)} />
        </label>
        <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
        <button type="submit">登录</button>
      </form>
      {err && <p class="err">{err}</p>}
    </div>
  );
}

function ValveLine({ valve }) {
  if (!valve) return null;
  if (!valve.enabled) {
    return <p class="valve-off">蒸汽总阀停用中：口数不限，可随时改成缫丝中</p>;
  }
  const full = valve.usedReeling >= valve.maxReeling;
  return (
    <p class={full ? "valve-full" : "valve-ok"}>
      蒸汽总阀已启用 · 缫丝中口数 {valve.usedReeling}/{valve.maxReeling}
      {full && <span class="badge-full">已满</span>}
    </p>
  );
}

function Yard() {
  const [board, setBoard] = useState(null);
  const [picked, setPicked] = useState(null);
  const [temp, setTemp] = useState("40");
  const [err, setErr] = useState("");

  async function refresh() {
    const data = await api("/api/board");
    setBoard(data);
    if (picked) {
      setPicked(data.basins.find((b) => b.id === picked.id) || data.basins[0]);
    }
  }

  useEffect(() => {
    refresh().catch((e) => setErr(e.message));
  }, []);

  if (!board) {
    return (
      <div class="yard">
        <TopBar route="#/yard" />
        {err || "装载环盆…"}
      </div>
    );
  }

  const n = board.basins.length;
  const valve = board.valve;
  const valveFull = valve && valve.enabled && valve.usedReeling >= valve.maxReeling;

  async function writeTemp() {
    setErr("");
    try {
      const row = await api(`/api/basins/${picked.id}/readings`, {
        method: "POST",
        body: JSON.stringify({ waterTempC: Number(temp) }),
      });
      await refresh();
      setPicked(row);
    } catch (ex) {
      // 登记汤温不看总阀；失败后仍以库里最新数据为准。
      setErr(ex.message);
      await refresh().catch(() => {});
    }
  }
  async function setStatus(status) {
    setErr("");
    try {
      const row = await api(`/api/basins/${picked.id}/status`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      await refresh();
      setPicked(row);
    } catch (ex) {
      // 被总阀挡住时，口数可能刚被别人顶满：整盘重拉，页显必须与库态一致。
      setErr(ex.message);
      await refresh().catch(() => {});
    }
  }

  return (
    <div class="yard">
      <TopBar route="#/yard" />
      <div class="heading">
        <h1>{board.filature}</h1>
        <p>{board.riverside} · 点盆登记汤温；已缫完须最近汤温 38～42℃</p>
        <ValveLine valve={valve} />
      </div>
      <div class="ring">
        {board.basins.map((b, i) => {
          const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
          const left = 50 + Math.cos(angle) * 38;
          const top = 50 + Math.sin(angle) * 38;
          return (
            <button
              key={b.id}
              class={`basin ${b.status}`}
              style={{ left: `${left}%`, top: `${top}%` }}
              onClick={() => setPicked(b)}
            >
              <strong>{b.code}</strong>
              <span>{STATUS_LABEL[b.status]}</span>
            </button>
          );
        })}
      </div>
      {picked && (
        <div class="drawer">
          <h3>
            {picked.code} · {STATUS_LABEL[picked.status]}
          </h3>
          <p>最近汤温：{picked.latestTempC ?? "无"} ℃ · 记录 {picked.readingCount} 次</p>
          <ValveLine valve={valve} />
          <input value={temp} onInput={(e) => setTemp(e.target.value)} />
          <button onClick={writeTemp}>登记汤温</button>
          <div>
            <button onClick={() => setStatus("soaking")}>浸茧</button>
            <button
              class={valveFull && picked.status !== "reeling" ? "btn-blocked" : ""}
              onClick={() => setStatus("reeling")}
            >
              缫丝中{valveFull && picked.status !== "reeling" ? "（口数已满）" : ""}
            </button>
            <button onClick={() => setStatus("reeled")}>已缫完</button>
          </div>
          {err && <p class="err">{err}</p>}
        </div>
      )}
    </div>
  );
}

function ValvePage({ user }) {
  const [valve, setValve] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [max, setMax] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");

  async function refresh() {
    const data = await api("/api/valve");
    setValve(data);
    setEnabled(data.enabled);
    setMax(String(data.maxReeling));
  }

  useEffect(() => {
    refresh().catch((e) => setErr(e.message));
  }, []);

  if (!valve) {
    return (
      <div class="yard">
        <TopBar route="#/valve" />
        {err || "装载总阀…"}
      </div>
    );
  }

  const isAdmin = user && user.role === "admin";
  const full = valve.enabled && valve.usedReeling >= valve.maxReeling;

  async function save(e) {
    e.preventDefault();
    setErr("");
    setOk("");
    const value = Number(max);
    if (!Number.isInteger(value) || value < 1) {
      setErr("口数上限必须是正整数");
      return;
    }
    try {
      const data = await api("/api/valve", {
        method: "PUT",
        body: JSON.stringify({ enabled, maxReeling: value }),
      });
      setValve(data);
      setMax(String(data.maxReeling));
      setOk("总阀设置已保存");
    } catch (ex) {
      setErr(ex.message);
      await refresh().catch(() => {});
    }
  }

  return (
    <div class="yard">
      <TopBar route="#/valve" />
      <div class="heading">
        <h1>蒸汽总阀</h1>
        <p>统管全坞同时处于缫丝中的口数；登记汤温、标已缫完不经过总阀。</p>
      </div>
      <div class="drawer valve-card">
        <p class={full ? "valve-full" : "valve-ok"}>
          当前已用口数：{valve.usedReeling}
          {valve.enabled ? ` / 上限 ${valve.maxReeling}` : "（总阀停用，不限口数）"}
          {full && <span class="badge-full">已满</span>}
        </p>
        {isAdmin ? (
          <form onSubmit={save}>
            <label class="row">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              启用蒸汽总阀
            </label>
            <label class="row">
              同时缫丝中口数上限（正整数）
              <input
                value={max}
                onInput={(e) => setMax(e.target.value)}
              />
            </label>
            <button type="submit">保存总阀设置</button>
            {err && <p class="err">{err}</p>}
            {ok && <p class="ok">{ok}</p>}
          </form>
        ) : (
          <div>
            <p>
              总阀{valve.enabled ? `启用中，口数上限 ${valve.maxReeling}` : "停用中"}。
            </p>
            <p class="hint">只有管理员能改总阀设置；口数已满时抽屉里改成缫丝中会被挡住。</p>
            {err && <p class="err">{err}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

function App() {
  const route = useHashRoute();
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!token()) {
      setReady(true);
      return;
    }
    api("/api/auth/me")
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setReady(true));
  }, []);

  if (!ready) {
    return <div class="yard">装载…</div>;
  }
  if (!user) {
    return (
      <Login
        onOk={(u) => {
          setUser(u);
          window.location.hash = "#/yard";
        }}
      />
    );
  }
  if (route.startsWith("#/valve")) {
    return <ValvePage user={user} />;
  }
  return <Yard />;
}

render(<App />, document.getElementById("app"));
