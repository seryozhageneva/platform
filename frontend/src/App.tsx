import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError, errorMessage } from "./api";
import type { User } from "./api";
import { StudentHome } from "./StudentHome";
import { TeacherHome } from "./TeacherHome";

const sessionChange = "platform-session-change";

function notifySessionChange() {
  try {
    window.localStorage.setItem(sessionChange, crypto.randomUUID());
  } catch {
    // Вкладки всё равно перепроверят сеанс при возвращении фокуса.
  }
}

async function readSession() {
  try {
    return await api.me();
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 401) return null;
    throw failure;
  }
}

export function App({ link }: { link: string | null }) {
  const [user, setUser] = useState<User | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const revision = useRef(0);
  const pending = useRef(true);
  const mounted = useRef(false);
  const invalidate = useCallback(() => { revision.current++; }, []);

  const refresh = useCallback(async function loadSession(clear: boolean, token: string | null = null) {
    const request = ++revision.current;
    pending.current = true;
    if (clear) {
      setUser(null);
      setBusy(true);
      setError("");
    }
    let linkError = "";
    try {
      let current: User | null;
      if (token === null) {
        current = await readSession();
      } else {
        try {
          current = await api.student(token);
          notifySessionChange();
          if (revision.current !== request && mounted.current) {
            await loadSession(true);
            return;
          }
        } catch (failure) {
          linkError = errorMessage(failure);
          current = await readSession();
        }
      }
      if (revision.current === request) {
        setUser(current);
        if (linkError) setError(linkError);
      }
    } catch (failure) {
      if (revision.current === request) setError(linkError || errorMessage(failure));
    } finally {
      if (revision.current === request) {
        pending.current = false;
        setBusy(false);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;

    function onStorage(event: StorageEvent) {
      if (event.key === sessionChange) void refresh(true);
    }

    function onFocus() {
      if (!pending.current) void refresh(false);
    }

    void refresh(true, link);
    window.addEventListener("storage", onStorage);
    window.addEventListener("focus", onFocus);
    return () => {
      mounted.current = false;
      invalidate();
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("focus", onFocus);
    };
  }, [invalidate, link, refresh]);

  const refreshSession = useCallback(() => { void refresh(true); }, [refresh]);

  async function act(request: () => Promise<User | null>) {
    const started = ++revision.current;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const current = await request();
      notifySessionChange();
      if (revision.current === started) setUser(current);
      else if (mounted.current) await refresh(true);
    } catch (failure) {
      if (revision.current === started) setError(errorMessage(failure));
    } finally {
      if (revision.current === started) {
        pending.current = false;
        setBusy(false);
      }
    }
  }

  function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    void act(() => api.teacher(String(fields.get("email")), String(fields.get("password"))));
  }

  function signOut() {
    void act(async () => {
      await api.logout();
      return null;
    });
  }

  return (
    <main>
      <h1>Учебная платформа</h1>
      {error && <p role="alert">{error}</p>}
      {busy && !user && <p role="status">Подключение…</p>}
      {!user && !busy && (
        <section>
          <h2>Вход преподавателя</h2>
          <form onSubmit={signIn}>
            <label>Почта<input name="email" type="email" autoComplete="username" required /></label>
            <label>Пароль<input name="password" type="password" autoComplete="current-password" required /></label>
            <button>Войти</button>
          </form>
          <p>Ученик входит по личной ссылке от преподавателя.</p>
        </section>
      )}
      {user && (
        <>
          <p>Вы вошли как {user.name}.</p>
          <button type="button" disabled={busy} onClick={signOut}>Выйти</button>
          {user.role === "student" && <StudentHome key={user.id} accountId={user.id} onSessionChange={refreshSession} />}
          {user.role === "teacher" && <TeacherHome key={user.id} accountId={user.id} onSessionChange={refreshSession} />}
        </>
      )}
    </main>
  );
}
