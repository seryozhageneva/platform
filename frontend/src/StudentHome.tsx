import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError, errorMessage } from "./api";
import type { Lesson, LessonResponse, LessonState } from "./api";

export function StudentHome({ accountId, onSessionChange }: {
  accountId: string;
  onSessionChange: () => void;
}) {
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [selected, setSelected] = useState<Lesson | null>(null);
  const [lesson, setLesson] = useState<LessonState | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const inFlight = useRef(false);

  useEffect(() => {
    let active = true;
    api.lessons(accountId)
      .then((list) => { if (active) setLessons(list); })
      .catch((failure: unknown) => {
        if (!active) return;
        if (failure instanceof ApiError && [401, 403, 409].includes(failure.status)) onSessionChange();
        else setError(errorMessage(failure));
      })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [accountId, onSessionChange]);

  async function change(target: Lesson, body?: LessonResponse) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setSelected(target);
    try {
      let next;
      if (body) {
        try {
          next = await api.respondToLesson(accountId, target.id, body);
        } catch (failure) {
          if (!(failure instanceof ApiError) || failure.status !== 409) throw failure;
          setLesson(null);
          next = await api.openLesson(accountId, target.id);
          setError("Экран урока обновился. Проверьте текущее задание.");
        }
      } else {
        next = await api.openLesson(accountId, target.id);
      }
      setLesson(next);
    } catch (failure) {
      if (failure instanceof ApiError && [401, 403].includes(failure.status)) onSessionChange();
      else setError(errorMessage(failure));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  const screen = lesson?.screen;

  return (
    <section>
      <h2>Мои уроки</h2>
      {error && <p role="alert">{error}</p>}
      {busy && <p role="status">Загружаем уроки…</p>}
      {!busy && !error && lessons.length === 0 && <p>Вам пока не назначили уроки.</p>}
      {!selected && (
        <ul>
          {lessons.map((item) => (
            <li key={item.id}>
              <button type="button" disabled={busy} onClick={() => void change(item)}>{item.name}</button>
            </li>
          ))}
        </ul>
      )}
      {selected && (
        <>
          <h3>{selected.name}</h3>
          <button type="button" disabled={busy} onClick={() => { setSelected(null); setLesson(null); setError(""); }}>
            К списку уроков
          </button>
          {screen && (
            <AnswerScreen key={screen.revision} screen={screen} busy={busy}
              respond={(response) => void change(selected, {
                node_id: screen.node_id, revision: screen.revision, response,
              })}
            />
          )}
          {lesson?.status === "done" && <p role="status">Урок завершён.</p>}
          {lesson?.status === "error" && <p role="alert">Урок остановился из-за ошибки. Сообщите преподавателю.</p>}
          {lesson?.status === "waiting" && !screen && <p>Этот шаг урока сейчас недоступен в кабинете.</p>}
          {(!lesson || lesson.status === "running" || (lesson.status === "waiting" && !screen)) && !busy && (
            <button type="button" onClick={() => void change(selected)}>Обновить урок</button>
          )}
        </>
      )}
    </section>
  );
}

function AnswerScreen({ screen, busy, respond }: {
  screen: NonNullable<LessonState["screen"]>;
  busy: boolean;
  respond: (response: LessonResponse["response"]) => void;
}) {
  const [form, setForm] = useState(screen.forms[0]);
  const [text, setText] = useState("");
  const formLabels = { text: "Текст", formula: "Формула", code: "Код", photo: "Фото" };
  const inputLabel = form === "formula" || form === "code" ? formLabels[form] : "Ответ";

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form || !text.trim()) return;
    respond({ action: "answer", answer: { task_id: screen.task_id, form, text: form === "code" ? text : text.trim() } });
  }

  return (
    <div>
      <p className="lesson-text">{screen.statement}</p>
      {screen.hint && <p className="lesson-text"><strong>Подсказка.</strong> {screen.hint.text}</p>}
      {form && (
        <form onSubmit={submit}>
          {screen.forms.length > 1 && (
            <label>Форма ответа
              <select value={form} disabled={busy} onChange={(event) => {
                const next = screen.forms.find((item) => item === event.target.value);
                if (next) setForm(next);
              }}>
                {screen.forms.map((item) => (
                  <option key={item} value={item}>{formLabels[item]}</option>
                ))}
              </select>
            </label>
          )}
          <label>{inputLabel}
            {form === "formula" ? (
              <input value={text} onChange={(event) => setText(event.target.value)}
                disabled={busy} required aria-describedby="formula-examples" />
            ) : (
              <textarea className={form === "code" ? "lesson-code" : "lesson-answer"}
                value={text} onChange={(event) => setText(event.target.value)}
                disabled={busy} required rows={form === "code" ? 8 : 4} spellCheck={form !== "code"} />
            )}
          </label>
          {form === "formula" && <p id="formula-examples">Например: <code>1/2</code>, <code>x^2</code>, <code>sqrt(2)</code>.</p>}
          <button disabled={busy || !text.trim()}>Отправить ответ</button>
        </form>
      )}
      {screen.can_ask_hint && (
        <button type="button" disabled={busy} onClick={() => respond({ action: "hint" })}>Попросить подсказку</button>
      )}
    </div>
  );
}
