import { useEffect, useState } from "react";
import { api, ApiError, errorMessage } from "./api";
import type { Pipeline, ScheduleDetails, ScheduleUpdate } from "./api";

type Param = Pipeline["params"][number];

const moscowTime = new Intl.DateTimeFormat("ru-RU", {
  dateStyle: "short", timeStyle: "short", timeZone: "Europe/Moscow",
});

export function TeacherSchedule({ accountId, pipelineId, version, params, disabled, onSessionChange }: {
  accountId: string; pipelineId: string; version: number; params: Param[];
  disabled: boolean; onSessionChange: () => void;
}) {
  const [saved, setSaved] = useState<ScheduleDetails>();
  const [enabled, setEnabled] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    let active = true;
    api.schedule(accountId, pipelineId).then((schedule) => {
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
  }, [accountId, pipelineId, onSessionChange]);

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
      setSaved(await api.saveSchedule(accountId, pipelineId, {
        enabled, params: given, expected_version: version,
      }));
      setStatus("Настройки расписания сохранены.");
    } catch (failure) {
      if (failure instanceof ApiError && [401, 403].includes(failure.status)) onSessionChange();
      setError(failure instanceof ApiError && failure.problems.length
        ? failure.problems.map((problem) => problem.message).join(" ")
        : errorMessage(failure));
    } finally {
      setPending(false);
    }
  }

  return <section aria-label="Расписание">
    <h3>Расписание</h3>
    {saved?.cron && <p>{saved.cron} · время Москвы</p>}
    {saved?.last_fired_at && <p>Последний запуск поставлен в очередь {moscowTime.format(new Date(saved.last_fired_at))} (МСК).</p>}
    {pending && !saved && <p role="status">Загрузка расписания…</p>}
    {disabled && <p>Сначала сохраните изменения пайплайна.</p>}
    {error && <p role="alert">{error}</p>}
    {status && <p role="status">{status}</p>}
    {saved && <fieldset disabled={disabled || pending}>
      <label><input type="checkbox" checked={enabled}
        onChange={(event) => setEnabled(event.target.checked)} /> Включено</label>
      {params.map((param) => {
        const value = Object.hasOwn(values, param.name) ? values[param.name] : "";
        const update = (next: string) => setValues((current) => ({ ...current, [param.name]: next }));
        return <label key={param.name}>{param.title}
          {param.type === "boolean" ? <select value={value} onChange={(event) => update(event.target.value)}>
            <option value="">{param.default == null ? "Выберите значение" : `По умолчанию: ${param.default ? "да" : "нет"}`}</option>
            <option value="true">Да</option>
            <option value="false">Нет</option>
          </select> : <input type={param.type === "string" ? "text" : "number"}
            step={param.type === "integer" ? 1 : "any"} value={value}
            placeholder={param.default == null ? undefined : String(param.default)}
            onChange={(event) => update(event.target.value)} />}
        </label>;
      })}
      <button type="button" onClick={() => void save()}>Сохранить расписание</button>
    </fieldset>}
  </section>;
}
