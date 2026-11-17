import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, errorText, locale, readBootstrap, session, t } from "./api";
import {
  activeMember,
  audioURL,
  books,
  download,
  openReader,
  purge,
  removeBook,
  setIdentity,
  type License,
  type LocalBook,
} from "./offline";
interface Boot {
  edition_revision_id?: string;
  unit_ids?: string[];
  units?: { unit_id: string; title: string }[];
  formats?: string[];
  title?: string;
  locale?: string;
  offline?: boolean;
}
function Downloads({ boot }: { boot: Boot }) {
  const [items, setItems] = useState<LocalBook[]>([]);
  const [licenses, setLicenses] = useState<License[]>([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedUnits, setSelectedUnits] = useState<string[]>(
    (boot.unit_ids || []).slice(0, 10),
  );
  const [listening, setListening] = useState<{
    book: LocalBook;
    url: string;
  }>();
  const audio = useRef<HTMLAudioElement>(null);
  const [reading, setReading] = useState<{
    book: LocalBook;
    paragraphs: { text: string; kind: string; anchor_id: string }[];
  }>();
  useEffect(() => {
    const book = reading?.book || listening?.book;
    if (!book) return;
    const deadline =
      performance.now() +
      Math.max(0, Date.parse(book.license.valid_until) - Date.now());
    const validate = () => {
      if (
        Date.now() >= Date.parse(book.license.valid_until) ||
        Date.now() < book.last_seen - 60000 ||
        performance.now() >= deadline
      ) {
        audio.current?.pause();
        setReading(undefined);
        setListening(undefined);
        setStatus(t("download_expired"));
      }
    };
    const timer = setInterval(validate, 1000);
    document.addEventListener("visibilitychange", validate);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", validate);
    };
  }, [reading, listening]);
  async function refresh() {
    if (navigator.onLine) {
      const identity = await session(true);
      if (!identity.authenticated || !identity.member || !identity.device_id) {
        await purge();
        audio.current?.pause();
        setReading(undefined);
        setListening(undefined);
        setItems([]);
        setStatus(t("sign_in_save"));
        return;
      }
      await setIdentity(identity.member.member_id, identity.device_id);
      const response = await api<{ items: License[] }>("/me/downloads");
      setLicenses(response.items);
      const local = await books(identity.member.member_id);
      for (const book of local) {
        const remote = response.items.find(
          (l) => l.license_id === book.license.license_id,
        );
        if (
          !remote ||
          remote.status !== "active" ||
          Date.parse(remote.valid_until) <= Date.now()
        ) {
          await removeBook(book);
          if (
            reading?.book.key === book.key ||
            listening?.book.key === book.key
          ) {
            audio.current?.pause();
            setReading(undefined);
            setListening(undefined);
            setStatus(t("download_expired"));
          }
        }
      }
      setItems(await books(identity.member.member_id));
    } else {
      const member = await activeMember();
      setItems(member ? await books(member) : []);
    }
  }
  useEffect(() => {
    refresh().catch((e) => setStatus(errorText(e)));
  }, []);
  useEffect(() => {
    const reconnect = () =>
      void refresh().catch((e) => setStatus(errorText(e)));
    window.addEventListener("online", reconnect);
    return () => window.removeEventListener("online", reconnect);
  }, [reading, listening]);
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
  async function save(format: "reader" | "audio") {
    if (!("serviceWorker" in navigator)) throw new Error("download_failed");
    await Promise.race([
      navigator.serviceWorker.ready,
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error("download_failed")), 10000),
      ),
    ]);
    const identity = await session();
    if (!identity.member || !identity.device_id)
      throw new Error(t("sign_in_save"));
    const license = await api<License>("/me/downloads", {
      method: "POST",
      key: crypto.randomUUID(),
      body: {
        edition_revision_id: boot.edition_revision_id,
        format,
        unit_ids: selectedUnits,
        device_id: identity.device_id,
      },
    });
    await setIdentity(identity.member.member_id, identity.device_id);
    await download(
      identity.member.member_id,
      license,
      boot.title || t("downloads"),
      boot.locale || locale,
      (done, total) =>
        setStatus(`${t("downloading")} ${Math.floor((done / total) * 100)}%`),
    );
    await refresh();
    setStatus(t("offline_ready"));
  }
  return (
    <section className="downloads-panel">
      <p role="status" aria-live="polite">
        {status}
      </p>
      {boot.edition_revision_id ? (
        <div>
          {(boot.units?.length || 0) > 1 ? (
            <fieldset>
              <legend>{t("download_chapters")}</legend>
              {boot.units!.map((unit) => (
                <label key={unit.unit_id}>
                  <input
                    type="checkbox"
                    checked={selectedUnits.includes(unit.unit_id)}
                    disabled={
                      busy ||
                      (!selectedUnits.includes(unit.unit_id) &&
                        selectedUnits.length >= 10)
                    }
                    onChange={(event) =>
                      setSelectedUnits((current) =>
                        event.target.checked
                          ? [...current, unit.unit_id]
                          : current.filter((id) => id !== unit.unit_id),
                      )
                    }
                  />
                  {unit.title}
                </label>
              ))}
            </fieldset>
          ) : null}
          <div className="actions">
            {(boot.formats || [])
              .filter((f) => f === "reader" || f === "audio")
              .map((f) => (
                <button
                  key={f}
                  disabled={busy || !navigator.onLine || !selectedUnits.length}
                  onClick={() => void act(() => save(f as "reader" | "audio"))}
                >
                  {t("download")} · {t(f)}
                </button>
              ))}
          </div>
        </div>
      ) : null}
      {items.length ? (
        <div className="stack">
          {items.map((book) => (
            <article key={book.key}>
              <h2 lang={book.locale}>{book.title}</h2>
              <p>
                {t(
                  book.state === "ready"
                    ? "offline_ready"
                    : book.state === "failed"
                      ? "download_failed"
                      : "downloading",
                )}{" "}
                · {t(book.license.format)} ·{" "}
                {new Date(book.license.valid_until).toLocaleString(locale)}
              </p>
              {book.license.format === "reader" ? (
                <button
                  disabled={busy || book.state !== "ready"}
                  onClick={() =>
                    void act(async () =>
                      setReading({ book, paragraphs: await openReader(book) }),
                    )
                  }
                >
                  {t("read_edition")}
                </button>
              ) : null}
              {book.license.format === "audio" && book.state === "ready" ? (
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(async () =>
                      setListening({
                        book,
                        url: await audioURL(
                          book,
                          book.license.assets[0].asset_id,
                        ),
                      }),
                    )
                  }
                >
                  {t("audio")}
                </button>
              ) : null}
              <button
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    await removeBook(book);
                    setReading(undefined);
                    setListening(undefined);
                    if (navigator.onLine)
                      await api("/me/downloads/" + book.license.license_id, {
                        method: "DELETE",
                        key: crypto.randomUUID(),
                      });
                    await refresh();
                  })
                }
              >
                {t("remove")}
              </button>
              {navigator.onLine ? (
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      await api(
                        "/me/downloads/" + book.license.license_id + "/renew",
                        { method: "POST", key: crypto.randomUUID(), body: {} },
                      );
                      await refresh();
                      setStatus(t("download_again"));
                    })
                  }
                >
                  {t("renew_access")}
                </button>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <p>{t("empty")}</p>
      )}
      {listening ? (
        <section className="player-panel">
          <h2>{listening.book.title}</h2>
          <audio ref={audio} src={listening.url} controls preload="metadata" />
          <ol className="unit-list">
            {listening.book.license.assets.map((asset, index) => (
              <li key={asset.asset_id}>
                <button
                  onClick={() =>
                    void act(async () =>
                      setListening({
                        book: listening.book,
                        url: await audioURL(listening.book, asset.asset_id),
                      }),
                    )
                  }
                >
                  {t("chapter")} {index + 1}
                </button>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      {reading ? (
        <section className="reader reader-paper">
          <button onClick={() => setReading(undefined)}>{t("close")}</button>
          <h1 lang={reading.book.locale}>{reading.book.title}</h1>
          <div className="reading-text" lang={reading.book.locale}>
            {reading.paragraphs.map((p) =>
              p.kind === "heading" ? (
                <h2 key={p.anchor_id}>{p.text}</h2>
              ) : (
                <p
                  key={p.anchor_id}
                  className={p.kind === "verse" ? "verse" : undefined}
                >
                  {p.text}
                </p>
              ),
            )}
          </div>
        </section>
      ) : null}
    </section>
  );
}
const host = document.getElementById("downloads-island");
if (host)
  createRoot(host).render(
    <Downloads boot={readBootstrap<Boot>("downloads-bootstrap")} />,
  );
