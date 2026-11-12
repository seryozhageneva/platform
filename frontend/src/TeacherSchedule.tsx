import { useEffect, useState } from "react";
import { api, ApiError, errorMessage } from "./api";
import type { MoodleWatchDetails, Pipeline, ScheduleDetails, ScheduleUpdate } from "./api";

type Param = Pipeline["params"][number];
type Details = ScheduleDetails | MoodleWatchDetails;

// Два способа запуска без человека: по расписанию и по событию Moodle (ADR 0032, ADR 0034).
// Настройки у них одинаковые — включено ли и с какими параметрами пайплайна.
const kinds = {
  schedule: {
    title: "Расписание",
    loading: "Загрузка расписания…",
    save: "Сохранить расписание",
    saved: "Настройки расписания сохранены.",
    load: (accountId: string, pipelineId: string): Promise<Details> => api.schedule(accountId, pipelineId),
    store: (accountId: string, pipelineId: string, body: ScheduleUpdate): Promise<Details> =>
      api.saveSchedule(accountId, pipelineId, body),
  },
  moodle: {
    title: "Событие Moodle",
    loading: "Загрузка настроек опроса Moodle…",
    save: "Сохранить запуск по событию Moodle",
    saved: "Настройки запуска по событию Moodle сохранены.",
    load: (accountId: string, pipelineId: string): Promise<Details> => api.moodleWatch(accountId, pipelineId),
    store: (accountId: string, pipelineId: string, body: ScheduleUpdate): Promise<Details> =>
      api.saveMoodleWatch(accountId, pipelineId, body),
  },
};

const moscowTime = new Intl.DateTimeFormat("ru-RU", {
  dateStyle: "short", timeStyle: "short", timeZone: "Europe/Moscow",
});

export function TeacherSchedule({ kind = "schedule", accountId, pipelineId, version, params, disabled, onSessionChange }: {
  kind?: keyof typeof kinds; accountId: string; pipelineId: string; version: number; params: Param[];
  disabled: boolean; onSessionChange: () => void;
}) {
  const text = kinds[kind];
  const [saved, setSaved] = useState<Details>();
  const [enabled, setEnabled] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    let active = true;
    text.load(accountId, pipelineId).then((schedule) => {
      if (!active) return;
      setSaved(schedule);
      setEnabled(schedule.enabled);
      setValues(Object.fromEntries(Object.entries(schedule.params).map(([name, value]) => [name, String(value)])));
    }).catch((failure: unknown) => {
      if (!active) return;
      if (failure instanceof ApiError && [401, 403, 409].includes(failure.status)) onSessionChange();
      setError(errorMessage(failure));
    }).finally(() => {
      if (active) setPending(false);
    });
    return () => { active = false; };
  }, [text, accountId, pipelineId, onSessionChange]);

  async function save() {
    setError("");
    setStatus("");
    const given: ScheduleUpdate["params"] = {};
    for (const param of params) {
      if (!Object.hasOwn(values, param.name)) continue;
      const value = values[param.name];
      if (value === "" && param.type !== "string") continue;
      const typed = param.type === "boolean" ? value === "true"
        : param.type === "string" ? value : Number(value);
      if (typeof typed === "number" && (!Number.isFinite(typed)
        || ((param.type === "integer" || Number.isInteger(typed)) && !Number.isSafeInteger(typed)))) {
        setError(`«${param.title}»: браузер не может точно передать это число.`);
        return;
      }
      given[param.name] = typed;
    }
    setPending(true);
    try {
      setSaved(await text.store(accountId, pipelineId, {
        enabled, params: given, expected_version: version,
      }));
      setStatus(text.saved);
    } catch (failure) {
      if (failure instanceof ApiError && [401, 403].includes(failure.status)) onSessionChange();
      setError(failure instanceof ApiError && failure.problems.length
        ? failure.problems.map((problem) => problem.message).join(" ")
        : errorMessage(failure));
    } finally {
      setPending(false);
    }
  }

  return <section aria-label={text.title}>
    <h3>{text.title}</h3>
    {saved && "cron" in saved && saved.cron && <p>{saved.cron} · время Москвы</p>}
    {saved && "last_fired_at" in saved && saved.last_fired_at &&
      <p>Последний запуск поставлен в очередь {moscowTime.format(new Date(saved.last_fired_at))} (МСК).</p>}
    {saved && "poll_minutes" in saved && <>
      {saved.poll_minutes && <p>Платформа проверяет Moodle раз в {saved.poll_minutes} мин. и запускает
        пайплайн на новые сданные работы.</p>}
      {saved.last_polled_at && <p>Последняя проверка {moscowTime.format(new Date(saved.last_polled_at))} (МСК).
        Уже взято работ: {saved.seen_submissions}.</p>}
      {saved.last_error && <p>Ошибка проверки Moodle: {saved.last_error}</p>}
    </>}
    {pending && !saved && <p role="status">{text.loading}</p>}
    {disabled && <p>Сначала сохраните изменения пайплайна.</p>}
    {error && <p role="alert">{error}</p>}
    {status && <p role="status">{status}</p>}
    {saved && <fieldset disabled={disabled || pending}>
      <label><input type="checkbox" checked={enabled}
        onChange={(event) => setEnabled(event.target.checked)} /> Включено</label>
      {params.map((param) => {
        const isSet = Object.hasOwn(values, param.name);
        const value = isSet ? values[param.name] : "";
        const update = (next: string) => setValues((current) => ({ ...current, [param.name]: next }));
        if (param.type === "string") {
          const action = isSet ? "Сбросить значение" : "Задать пустую строку";
          return <div key={param.name} className="pipeline-setting">
            <label>{param.title}<input value={value}
              placeholder={!isSet && typeof param.default === "string" ? param.default : undefined}
              onChange={(event) => update(event.target.value)} /></label>
            <button type="button" aria-label={`${param.title} · ${action.toLowerCase()}`}
              onClick={() => setValues((current) => {
                const next = { ...current };
                if (Object.hasOwn(next, param.name)) delete next[param.name];
                else next[param.name] = "";
                return next;
              })}>{action}</button>
          </div>;
        }
        return <label key={param.name}>{param.title}
          {param.type === "boolean" ? <select value={value} onChange={(event) => update(event.target.value)}>
            <option value="">{param.default == null ? "Выберите значение" : `По умолчанию: ${param.default ? "да" : "нет"}`}</option>
            <option value="true">Да</option>
            <option value="false">Нет</option>
          </select> : <input type="number"
            step={param.type === "integer" ? 1 : "any"} value={value}
            placeholder={param.default == null ? undefined : String(param.default)}
            onChange={(event) => update(event.target.value)} />}
        </label>;
      })}
      <button type="button" onClick={() => void save()}>{text.save}</button>
    </fieldset>}
  </section>;
}
