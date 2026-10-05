import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { api, clearToken, setToken, token } from "./api.js";
import "./app.css";

const STATUS_LABEL = { soaking: "浸茧", reeling: "缫丝中", reeled: "已缫完" };

function Topbar({ page, onNavigate, subtitle }) {
  return (
    <div class="topbar">
      <div>
        <h1>江口缫丝坞</h1>
        <nav class="nav">
          <button
            class={page === "yard" ? "navlink on" : "navlink"}
            onClick={() => onNavigate("yard")}
          >
            环盆作业台
          </button>
          <button
            class={page === "valve" ? "navlink on" : "navlink"}
            onClick={() => onNavigate("valve")}
          >
            蒸汽总阀
          </button>
        </nav>
        {subtitle && <p class="sub">{subtitle}</p>}
      </div>
      <button
        class="logout"
        onClick={() => {
          clearToken();
          location.reload();
        }}
      >
        退出
      </button>
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
      onOk();
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

function Yard({ onNavigate }) {
  const [board, setBoard] = useState(null);
  const [picked, setPicked] = useState(null);
  const [temp, setTemp] = useState("40");
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");

  async function refresh() {
    const data = await api("/api/board");
    setBoard(data);
    setPicked((prev) =>
      prev ? data.basins.find((b) => b.id === prev.id) || data.basins[0] : prev
    );
  }

  useEffect(() => {
    refresh().catch((e) => setErr(e.message));
  }, []);

  if (!board) {
    return (
      <div class="yard">
        <Topbar page="yard" onNavigate={onNavigate} />
        {err || "装载环盆…"}
      </div>
    );
  }

  const n = board.basins.length;
  async function writeTemp() {
    setErr("");
    setNotice("");
    try {
      const row = await api(`/api/basins/${picked.id}/readings`, {
        method: "POST",
        body: JSON.stringify({ waterTempC: Number(temp) }),
      });
      await refresh();
      setPicked(row);
      setNotice("汤温已登记");
    } catch (ex) {
      setErr(ex.message);
    }
  }
  async function setStatus(status) {
    setErr("");
    setNotice("");
    try {
      // 成功后以返回行（库里真实盆态）回写，再拉整盘，保证页面与库一致。
      const row = await api(`/api/basins/${picked.id}/status`, {
        method: "POST",
        body: JSON.stringify({ status }),
      });
      await refresh();
      setPicked(row);
      setNotice(`已改为${STATUS_LABEL[row.status]}`);
    } catch (ex) {
      // 被总阀挡住等失败：刷新整盘，露出真实已用口数，抽屉盆态保持库里状态。
      setErr(ex.message);
      await refresh().catch(() => {});
    }
  }

  return (
    <div class="yard">
      <Topbar
        page="yard"
        onNavigate={onNavigate}
        subtitle={`${board.riverside} · 点盆登记汤温；已缫完须最近汤温 38～42℃；浸茧改缫丝中受蒸汽总阀口数限制`}
      />
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
              onClick={() => {
                setPicked(b);
                setErr("");
                setNotice("");
              }}
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
          <input value={temp} onInput={(e) => setTemp(e.target.value)} />
          <button onClick={writeTemp}>登记汤温</button>
          <div>
            <button onClick={() => setStatus("soaking")}>浸茧</button>
            <button onClick={() => setStatus("reeling")}>缫丝中</button>
            <button onClick={() => setStatus("reeled")}>已缫完</button>
          </div>
          {notice && <p class="ok">{notice}</p>}
          {err && <p class="err">{err}</p>}
        </div>
      )}
    </div>
  );
}

function Valve({ onNavigate }) {
  const [valve, setValve] = useState(null);
  const [role, setRole] = useState("worker");
  const [enabled, setEnabled] = useState(true);
  const [maxInput, setMaxInput] = useState("3");
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    const [v, me] = await Promise.all([
      api("/api/steam-valve"),
      api("/api/auth/me"),
    ]);
    setValve(v);
    setRole(me.role);
    setEnabled(v.enabled);
    setMaxInput(String(v.maxReeling));
  }

  useEffect(() => {
    load().catch((e) => setErr(e.message));
  }, []);

  async function save() {
    setErr("");
    setNotice("");
    const max = Number(maxInput);
    if (!/^\s*\d+\s*$/.test(String(maxInput)) || max <= 0) {
      setErr("同时缫丝口数上限必须是正整数");
      return;
    }
    try {
      const v = await api("/api/steam-valve", {
        method: "PUT",
        body: JSON.stringify({ enabled, maxReeling: max }),
      });
      setValve(v);
      setMaxInput(String(v.maxReeling));
      setEnabled(v.enabled);
      setNotice("蒸汽总阀设置已保存");
    } catch (ex) {
      setErr(ex.message);
    }
  }

  return (
    <div class="yard">
      <Topbar page="valve" onNavigate={onNavigate} subtitle="蒸汽总阀：同时允许处于缫丝中的口数上限" />
      <div class="drawer valve-card">
        {!valve ? (
          <span>{err || "读取总阀…"}</span>
        ) : (
          <>
            <div class={`valve-state ${valve.enabled ? "on" : "off"}`}>
              {valve.enabled ? "总阀启用中" : "总阀已停用"}
            </div>
            <p class="big">
              已用口数 <strong>{valve.usedReeling}</strong> / {valve.maxReeling} 口
              （当前缫丝中盆数）
            </p>
            <p class={valve.full && valve.enabled ? "err" : "hint"}>
              {valve.enabled
                ? valve.full
                  ? "已满：浸茧不能再改成缫丝中"
                  : `尚有 ${valve.maxReeling - valve.usedReeling} 口可开`
                : "停用期间不限制改成缫丝中"}
            </p>

            {role === "admin" ? (
              <div class="valve-form">
                <label class="row">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                  />
                  启用蒸汽总阀
                </label>
                <label class="row">
                  同时缫丝口数上限（正整数）
                  <input
                    value={maxInput}
                    inputmode="numeric"
                    onInput={(e) => setMaxInput(e.target.value)}
                  />
                </label>
                <button onClick={save}>保存总阀设置</button>
              </div>
            ) : (
              <p class="hint">仅管理员可修改上限与启停，当前为只读。</p>
            )}
            {notice && <p class="ok">{notice}</p>}
            {err && <p class="err">{err}</p>}
          </>
        )}
      </div>
    </div>
  );
}

function App() {
  const [ready, setReady] = useState(Boolean(token()));
  const [page, setPage] = useState("yard");
  return ready ? (
    page === "valve" ? (
      <Valve onNavigate={setPage} />
    ) : (
      <Yard onNavigate={setPage} />
    )
  ) : (
    <Login onOk={() => setReady(true)} />
  );
}

render(<App />, document.getElementById("app"));
