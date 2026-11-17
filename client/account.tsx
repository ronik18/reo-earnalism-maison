import { useEffect, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import { api, errorText, readBootstrap, t, type Preferences } from "./api";
interface Device {
  device_id: string;
  label: string;
  current: boolean;
  revoked_at: string | null;
}
interface Privacy {
  privacy_request_id: string;
  kind: string;
  status: string;
  requested_at: string;
}
interface MFA {
  configured: boolean;
  session_verified: boolean;
  recovery_codes_remaining: number;
}
function Account({ staff }: { staff: boolean }) {
  const [prefs, setPrefs] = useState<Preferences>();
  const [devices, setDevices] = useState<Device[]>([]);
  const [privacy, setPrivacy] = useState<Privacy[]>([]);
  const [mfa, setMfa] = useState<MFA>();
  const [setup, setSetup] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState(false);
  const [deleting, setDeleting] = useState(false);
  async function load() {
    if (staff) {
      const security = await api<MFA>("/me/mfa/totp");
      setMfa(security);
      if (!security.session_verified) return;
    }
    const [p, d, r] = await Promise.all([
      api<Preferences>("/me/preferences"),
      api<{ items: Device[] }>("/me/devices"),
      api<{ items: Privacy[] }>("/me/privacy/requests"),
    ]);
    setPrefs(p);
    setDevices(d.items);
    setPrivacy(r.items);
  }
  useEffect(() => {
    load().catch((e) => setStatus(errorText(e)));
    const timer = window.setInterval(() => {
      if (!document.hidden)
        api<{ items: Privacy[] }>("/me/privacy/requests")
          .then((p) => setPrivacy(p.items))
          .catch(() => {});
    }, 30000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!fresh) return;
    const timer = setTimeout(() => setFresh(false), 300000);
    return () => clearTimeout(timer);
  }, [fresh]);
  async function act(action: () => Promise<void>) {
    setBusy(true);
    setStatus("");
    try {
      await action();
    } catch (e) {
      setStatus(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function reauthenticate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    await act(async () => {
      await api("/me/reauthenticate", {
        method: "POST",
        body: { password: new FormData(form).get("password") },
        key: crypto.randomUUID(),
      });
      setFresh(true);
      form.reset();
      setStatus(t("reauthenticated"));
    });
  }
  return (
    <>
      <p id="account-status" role="status" aria-live="polite">
        {status}
      </p>
      {prefs ? (
        <form
          id="account-settings-form"
          className="narrow"
          onSubmit={(e) => {
            e.preventDefault();
            void act(async () => {
              const form = new FormData(e.currentTarget);
              const updated = await api<Preferences>("/me/preferences", {
                method: "PATCH",
                version: prefs.version,
                key: crypto.randomUUID(),
                body: {
                  theme: form.get("theme"),
                  reduced_motion: form.get("reduced_motion") === "on",
                },
              });
              setPrefs(updated);
              for (const theme of ["light", "dark", "true_black"])
                document.body.classList.remove("theme-" + theme);
              document.body.classList.add("theme-" + updated.theme);
              document.body.classList.toggle(
                "reduced-motion",
                updated.reduced_motion,
              );
              setStatus(t("saved_server"));
            });
          }}
        >
          <label>
            {t("theme")}
            <select name="theme" defaultValue={prefs.theme}>
              {["light", "dark", "true_black"].map((v) => (
                <option key={v} value={v}>
                  {t(v === "true_black" ? "black" : v)}
                </option>
              ))}
            </select>
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              name="reduced_motion"
              defaultChecked={prefs.reduced_motion}
            />
            {t("reduced_motion")}
          </label>
          <button className="button" disabled={busy}>
            {t("save")}
          </button>
        </form>
      ) : null}
      <section>
        <h2>{t("devices")}</h2>
        <p>{t("offline_revoke_limit")}</p>
        <div id="devices">
          {devices.map((d) => (
            <article key={d.device_id}>
              <p>
                {d.label}
                {d.current ? " · " + t("current_device") : ""}
              </p>
              {!d.revoked_at ? (
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      await api("/me/devices/" + d.device_id, {
                        method: "DELETE",
                        key: crypto.randomUUID(),
                      });
                      if (d.current)
                        window.location.assign(
                          "/" + document.documentElement.lang + "/sign-in/",
                        );
                      else await load();
                    })
                  }
                >
                  {t("revoke_device")}
                </button>
              ) : null}
            </article>
          ))}
        </div>
      </section>
      <section>
        <h2>{t("sensitive_actions")}</h2>
        <form className="narrow" onSubmit={reauthenticate}>
          <label>
            {t("password")}
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              required
            />
          </label>
          <button disabled={busy}>{t("confirm_password")}</button>
        </form>
        <p>{t("reauthentication_window")}</p>
      </section>
      {staff ? (
        <section id="mfa-settings">
          <h2>{t("staff_security")}</h2>
          <p>{t(mfa?.session_verified ? "mfa_verified" : "mfa_required")}</p>
          {!mfa?.configured ? (
            <button
              disabled={busy || !fresh}
              onClick={() =>
                void act(async () => {
                  const result = await api<{ configuration_uri: string }>(
                    "/me/mfa/totp",
                    { method: "POST", key: crypto.randomUUID(), body: {} },
                  );
                  setSetup(result.configuration_uri);
                })
              }
            >
              {t("mfa_setup")}
            </button>
          ) : null}
          {setup ? (
            <div className="narrow">
              <p>{t("mfa_setup_help")}</p>
              <a href={setup}>{t("open_authenticator")}</a>
              <label>
                {t("authenticator_secret")}
                <input
                  readOnly
                  value={new URL(setup).searchParams.get("secret") || ""}
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const token = new FormData(e.currentTarget).get("token");
                  void act(async () => {
                    const result = await api<{ recovery_codes: string[] }>(
                      "/me/mfa/totp/confirm",
                      {
                        method: "POST",
                        key: crypto.randomUUID(),
                        body: { token },
                      },
                    );
                    setCodes(result.recovery_codes);
                    setSetup("");
                    await load();
                  });
                }}
              >
                <label>
                  {t("verification_code")}
                  <input
                    name="token"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]{6}"
                    required
                  />
                </label>
                <button disabled={busy}>{t("confirm")}</button>
              </form>
            </div>
          ) : null}
          {mfa?.configured && !mfa.session_verified ? (
            <form
              className="narrow"
              onSubmit={(e) => {
                e.preventDefault();
                const token = new FormData(e.currentTarget).get("token");
                void act(async () => {
                  await api("/me/mfa/verify", {
                    method: "POST",
                    key: crypto.randomUUID(),
                    body: { token },
                  });
                  await load();
                });
              }}
            >
              <label>
                {t("verification_code")}
                <input
                  name="token"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required
                />
              </label>
              <button disabled={busy}>{t("verify")}</button>
            </form>
          ) : null}
          {codes.length ? (
            <div className="notice">
              <p>{t("recovery_codes_once")}</p>
              <ul>
                {codes.map((code) => (
                  <li key={code}>
                    <code>{code}</code>
                  </li>
                ))}
              </ul>
              <button onClick={() => setCodes([])}>{t("saved_codes")}</button>
            </div>
          ) : null}
          {mfa?.configured ? (
            <details>
              <summary>{t("use_recovery_code")}</summary>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const code = new FormData(e.currentTarget).get("code");
                  void act(async () => {
                    await api("/me/mfa/recovery", {
                      method: "POST",
                      key: crypto.randomUUID(),
                      body: { code },
                    });
                    await load();
                  });
                }}
              >
                <label>
                  {t("recovery_code")}
                  <input name="code" autoComplete="off" required />
                </label>
                <button disabled={busy || !fresh}>{t("verify")}</button>
              </form>
            </details>
          ) : null}
        </section>
      ) : null}
      <section>
        <h2>{t("privacy")}</h2>
        <p>{t("privacy_retention")}</p>
        <div className="actions">
          <button
            disabled={busy || !fresh}
            onClick={() =>
              void act(async () => {
                await api("/me/privacy/requests", {
                  method: "POST",
                  key: crypto.randomUUID(),
                  body: { kind: "export", confirm: true },
                });
                await load();
                setStatus(t("request_queued"));
              })
            }
          >
            {t("export_data")}
          </button>
          <button disabled={busy || !fresh} onClick={() => setDeleting(true)}>
            {t("delete_account")}
          </button>
        </div>
        {deleting ? (
          <div className="notice">
            <p>{t("delete_confirmation")}</p>
            <button
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  await api("/me/privacy/requests", {
                    method: "POST",
                    key: crypto.randomUUID(),
                    body: { kind: "delete", confirm: true },
                  });
                  setDeleting(false);
                  await load();
                  setStatus(t("request_queued"));
                })
              }
            >
              {t("confirm_delete")}
            </button>
            <button onClick={() => setDeleting(false)}>{t("cancel")}</button>
          </div>
        ) : null}
        <div className="stack">
          {privacy.map((request) => (
            <article key={request.privacy_request_id}>
              <p>
                {t(
                  request.kind === "export" ? "export_data" : "delete_account",
                )}{" "}
                · {t("privacy_" + request.status)}
              </p>
              {request.status === "queued" ? (
                <button
                  disabled={busy || !fresh}
                  onClick={() =>
                    void act(async () => {
                      await api(
                        "/me/privacy/requests/" +
                          request.privacy_request_id +
                          "/cancel",
                        { method: "POST", key: crypto.randomUUID(), body: {} },
                      );
                      await load();
                    })
                  }
                >
                  {t("cancel_request")}
                </button>
              ) : null}
              {request.kind === "export" && request.status === "completed" ? (
                <button
                  disabled={busy || !fresh}
                  onClick={() =>
                    void act(async () => {
                      const result = await api<{ url: string }>(
                        "/me/privacy/requests/" +
                          request.privacy_request_id +
                          "/download",
                        { method: "POST", key: crypto.randomUUID(), body: {} },
                      );
                      window.location.assign(result.url);
                    })
                  }
                >
                  {t("download_export")}
                </button>
              ) : null}
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
const host = document.getElementById("account-island");
if (host)
  createRoot(host).render(
    <Account
      staff={readBootstrap<{ staff: boolean }>("account-bootstrap").staff}
    />,
  );
