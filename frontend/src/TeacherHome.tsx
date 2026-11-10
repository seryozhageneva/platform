import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError, errorMessage } from "./api";
import type { Student, Task } from "./api";
import { TeacherPipelines } from "./PipelineEditor";

export function TeacherHome({ accountId, onSessionChange }: {
  accountId: string;
  onSessionChange: () => void;
}) {
  const [students, setStudents] = useState<Student[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [name, setName] = useState("");
  const [link, setLink] = useState<{ studentId: string; url: string } | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([api.students(accountId), api.tasks(accountId)])
      .then(([students, tasks]) => {
        if (active) {
          setStudents(students);
          setTasks(tasks);
        }
      })
      .catch((failure: unknown) => {
        if (!active) return;
        if (failure instanceof ApiError && [401, 403, 409].includes(failure.status)) onSessionChange();
        else setError(errorMessage(failure));
      })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [accountId, onSessionChange]);

  async function change(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      if (failure instanceof ApiError && [401, 403, 409].includes(failure.status)) onSessionChange();
      else setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  function addStudent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void change(async () => {
      const student = await api.createStudent(accountId, name);
      setStudents((current) => [...current, student]);
      setName("");
    });
  }

  function setExpiry(id: string, expiry: string | null) {
    setStudents((current) => current.map((student) => (
      student.id === id ? { ...student, link_expires_at: expiry } : student
    )));
  }

  function issue(id: string) {
    void change(async () => {
      const issued = await api.issueLink(accountId, id);
      const url = new URL(window.location.pathname, window.location.origin);
      url.hash = new URLSearchParams({ student: issued.token }).toString();
      setExpiry(id, issued.expires_at);
      setLink({ studentId: id, url: url.href });
      setCopied(false);
    });
  }

  function revoke(id: string) {
    void change(async () => {
      await api.revokeLink(accountId, id);
      setExpiry(id, null);
      setLink((current) => current?.studentId === id ? null : current);
    });
  }

  async function copyLink(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setError("Не удалось скопировать автоматически. Выделите ссылку и скопируйте её вручную.");
    }
  }

  return (
    <>
      {error && <p role="alert">{error}</p>}
      <TeacherPipelines accountId={accountId} onSessionChange={onSessionChange} />
      <section>
        <h2>Мои задачи</h2>
        {!busy && tasks.length === 0 && <p>В банке пока нет задач.</p>}
        <ul>{tasks.map((task) => <li key={task.id}>{task.topic} — {task.statement}</li>)}</ul>
      </section>
      <section>
        <h2>Ученики</h2>
        <p>По личной ссылке может войти любой, у кого она есть.</p>
        <form onSubmit={addStudent}>
          <label>Псевдоним<input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required /></label>
          <button disabled={busy || !name.trim()}>Добавить ученика</button>
        </form>
        <ul className="students">
          {students.map((student) => (
            <li key={student.id}>
              <strong>{student.name}</strong>
              <span>{student.link_expires_at
                ? `Срок действия до ${new Date(student.link_expires_at).toLocaleString("ru-RU")}`
                : "Ссылки нет"}</span>
              <div className="actions">
                <button type="button" disabled={busy} onClick={() => issue(student.id)}>
                  {student.link_expires_at ? "Выпустить новую" : "Выпустить ссылку"}
                </button>
                <button type="button" disabled={busy || !student.link_expires_at} onClick={() => revoke(student.id)}>
                  Отозвать ссылку
                </button>
              </div>
              {link?.studentId === student.id && (
                <div className="actions">
                  <label>Личная ссылка<input readOnly value={link.url} /></label>
                  <button type="button" onClick={() => void copyLink(link.url)}>Скопировать</button>
                  {copied && <span role="status">Ссылка скопирована</span>}
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
