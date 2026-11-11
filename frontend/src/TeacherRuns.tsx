import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { ApprovalTable, reviewTable } from "./ApprovalTable";
import { api, ApiError, errorMessage } from "./api";
import type { Pipeline, PipelineSummary, Problem, RunSummary } from "./api";

type Session = { accountId: string; onSessionChange: () => void };
type Run = Awaited<ReturnType<typeof api.run>>;
type Events = Awaited<ReturnType<typeof api.runEvents>>;
type PipelineDetail = Awaited<ReturnType<typeof api.pipeline>>;
type Param = Pipeline["params"][number];

function serverOnlyDefault(param: Param) {
  return typeof param.default === "number" && Number.isInteger(param.default)
    && !Number.isSafeInteger(param.default);
}

const statusLabels: Record<RunSummary["status"], string> = {
  running: "Выполняется",
  waiting: "На паузе",
  done: "Завершён",
  error: "Ошибка",
};
const eventLabels: Record<string, string> = {
  run_queued: "Запуск принят в очередь",
  worker_failed: "Ошибка фонового запуска",
  run_started: "Запуск начался",
  node_done: "Шаг завершён",
  node_waiting: "Шаг ждёт ответа",
  node_resumed: "Шаг продолжен",
  approval_decided: "Решение преподавателя",
  node_failed: "Ошибка на шаге",
  file_missing: "Файл не найден",
  document_unreadable: "Документ не прочитан",
  run_done: "Запуск завершён",
};

function reportError(failure: unknown, onSessionChange: () => void) {
  if (failure instanceof ApiError && [401, 403, 409].includes(failure.status)) onSessionChange();
  return errorMessage(failure);
}

function RunProgress({ run }: { run: Pick<Run, "status" | "current" | "waiting" | "error"> | RunSummary }) {
  return <>
    <span>{statusLabels[run.status]}</span>
    {run.status === "waiting" && run.waiting.length > 0
      ? <ul>{run.waiting.map(({ node_id, who }) => (
        <li key={node_id}>{node_id} · {who === "teacher" ? "ждёт преподавателя" : "ждёт ученика"}</li>
      ))}</ul>
      : run.current.length > 0 && <span> · Шаг: {run.current.join(", ")}</span>}
    {run.error && <p>{run.error}</p>}
  </>;
}

const POLL_DELAY = 2000;
const JOURNAL_FINAL_RETRIES = 3;

function shouldRetry(failure: unknown) {
  return !(failure instanceof ApiError) || failure.status >= 500;
}

function hasStopEvent(run: Run, events: Events) {
  const last = events.at(-1)?.type;
  return (run.status === "done" && last === "run_done")
    || (run.status === "waiting" && last === "node_waiting")
    || (run.status === "error" && (last === "node_failed" || last === "worker_failed"));
}

function RunJournal({ accountId, onSessionChange, id, revision, onRefresh }: Session & {
  id: string; revision: number; onRefresh: () => void;
}) {
  const [journal, setJournal] = useState<{ run: Run; events: Events }>();
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let running = false;
    let poll: ReturnType<typeof setTimeout> | undefined;

    async function read(retriesLeft = JOURNAL_FINAL_RETRIES) {
      try {
        // Сначала читаем статус: параллельное чтение могло бы вернуть события до этого статуса.
        const run = await api.run(accountId, id);
        if (!active) return;
        if (run.status === "running") running = true;
        const events = await api.runEvents(accountId, id);
        if (!active) return;
        running = run.status === "running";
        setJournal({ run, events });
        setError("");
        if (running) {
          poll = setTimeout(() => void read(), POLL_DELAY);
        } else if (retriesLeft > 0 && events.some(({ type }) => type === "run_queued")
          && !hasStopEvent(run, events)) {
          // Состояние появляется раньше событий. Дочитываем журнал, но не ждём его бесконечно.
          poll = setTimeout(() => void read(retriesLeft - 1), POLL_DELAY);
        }
      } catch (failure: unknown) {
        if (!active) return;
        setError(reportError(failure, onSessionChange));
        if (!shouldRetry(failure)) return;
        if (running) poll = setTimeout(() => void read(), POLL_DELAY);
        else if (retriesLeft > 0 && retriesLeft < JOURNAL_FINAL_RETRIES) {
          poll = setTimeout(() => void read(retriesLeft - 1), POLL_DELAY);
        }
      }
    }

    void read();
    return () => { active = false; clearTimeout(poll); };
  }, [accountId, id, revision, onSessionChange]);

  const waiting = journal?.run.status === "waiting" && journal.run.waiting.find((item) =>
    item.who === "teacher" && item.screen === "review_table" && item.approval_id);
  const table = waiting && reviewTable(waiting.data);

  return <section aria-label="Журнал запуска">
    <h3>Журнал запуска</h3>
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert">{error}</p>}
    {!journal ? !error && <p role="status">Загрузка журнала…</p> : <>
      <RunProgress run={journal.run} />
      {waiting && waiting.approval_id && table && <ApprovalTable
        key={waiting.approval_id} table={table} accountId={accountId} runId={id}
        approvalId={waiting.approval_id} nodeId={waiting.node_id} onSessionChange={onSessionChange}
        onRefresh={(message) => { setNotice(message); onRefresh(); }} />}
      {journal.events.length === 0 ? <p>Событий пока нет.</p> : <ol>
        {journal.events.map((event) => <li key={event.id}>
          <time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString("ru-RU")}</time>
          {" · "}{event.node_id}{" · "}{Object.hasOwn(eventLabels, event.type) ? eventLabels[event.type] : event.type}
          {(event.type === "file_missing" || event.type === "document_unreadable") &&
            typeof event.data.message === "string" && <> · {event.data.message}</>}
          {event.type === "approval_decided" && typeof event.data.kept === "number" &&
            typeof event.data.changed === "number" && typeof event.data.skipped === "number" &&
            <> · {event.data.outcome === "approved" ? "подтверждено" : "отклонено"}.
              Оставлено {event.data.kept}, исправлено {event.data.changed}, пропущено {event.data.skipped}.</>}
        </li>)}
      </ol>}
    </>}
  </section>;
}

function LaunchForm({
  accountId, onSessionChange, pipeline, onLaunched, onUncertain, pending, setPending,
}: Session & {
  pipeline: PipelineDetail;
  onLaunched: (id: string) => void;
  onUncertain: () => void;
  pending: boolean;
  setPending: (pending: boolean) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [problems, setProblems] = useState<Problem[]>([]);
  const [uncertain, setUncertain] = useState(false);
  const sending = useRef(false);
  const manual = pipeline.graph.nodes.some((node) =>
    node.type === "trigger" && node.launches.some((launch) => launch.type === "manual"));

  function valueOf(param: Param) {
    return Object.hasOwn(values, param.name) ? values[param.name] ?? ""
      : param.default == null || serverOnlyDefault(param) ? "" : String(param.default);
  }

  async function launch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!manual || pending || uncertain || sending.current) return;

    setError("");
    setProblems([]);
    const entries: [string, string | number | boolean][] = [];
    for (const param of pipeline.graph.params) {
      if (param.default != null && !Object.hasOwn(values, param.name)) continue;
      const value = valueOf(param);
      if (value === "" && param.type !== "string") continue;
      const typed = param.type === "boolean" ? value === "true"
        : param.type === "string" ? value : Number(value);
      const exactInteger = param.type === "integer" || /^[+-]?\d+$/.test(value);
      if (typeof typed === "number" &&
          (!Number.isFinite(typed) || (exactInteger && !Number.isSafeInteger(typed)))) {
        setError(`«${param.title || param.name}»: браузер не может точно передать это число.`);
        return;
      }
      entries.push([param.name, typed]);
    }

    sending.current = true;
    setPending(true);
    try {
      const run = await api.launchRun(accountId, pipeline.id, {
        params: Object.fromEntries(entries), expected_version: pipeline.latest_version,
      });
      onLaunched(run.id);
    } catch (failure) {
      const refusedByQueue = failure instanceof ApiError && failure.status === 503
        && failure.problems.some(({ code }) => code === "queue_unavailable");
      if (failure instanceof ApiError && (failure.status < 500 || refusedByQueue)) {
        setError(reportError(failure, onSessionChange));
        setProblems(refusedByQueue ? [] : failure.problems);
      } else {
        setError("Сервер не подтвердил результат. Запуск мог состояться. Проверьте список запусков перед повторной отправкой.");
        setUncertain(true);
        onUncertain();
      }
    } finally {
      sending.current = false;
      setPending(false);
    }
  }

  if (!manual) return <p>Этот пайплайн нельзя запустить вручную.</p>;

  return <form onSubmit={(event) => void launch(event)}>
    <fieldset disabled={pending}>
      <legend>Параметры запуска · версия {pipeline.latest_version}</legend>
      {pipeline.graph.params.map((param) => {
        const update = (value: string) => setValues((current) => ({ ...current, [param.name]: value }));
        return <label key={param.name}>{param.title || param.name}
          {param.type === "boolean" ? <select required value={valueOf(param)} onChange={(event) => update(event.target.value)}>
            <option value="">Выберите значение</option>
            <option value="true">Да</option>
            <option value="false">Нет</option>
          </select> : <input
            type={param.type === "string" ? "text" : "number"}
            step={param.type === "integer" ? 1 : param.type === "number" ? "any" : undefined}
            required={param.type !== "string" && param.default == null}
            placeholder={serverOnlyDefault(param) ? "Значение по умолчанию с сервера" : undefined}
            value={valueOf(param)}
            onChange={(event) => update(event.target.value)}
          />}
        </label>;
      })}
      <button type="submit" disabled={uncertain}>{pending ? "Запуск выполняется…" : "Запустить"}</button>
    </fieldset>
    {error && <div role="alert">
      <p>{error}</p>
      {problems.length > 0 && <ul>{problems.map((problem, index) =>
        <li key={index}>{problem.node && `${problem.node} · `}{problem.message}</li>)}</ul>}
    </div>}
    {uncertain && <button type="button" onClick={() => setUncertain(false)}>Разрешить повторный запуск</button>}
  </form>;
}

function ManualLaunch({ accountId, onSessionChange, revision, onLaunched, onUncertain }: Session & {
  revision: number;
  onLaunched: (id: string) => void;
  onUncertain: () => void;
}) {
  const [pipelines, setPipelines] = useState<PipelineSummary[]>();
  const [choice, setChoice] = useState("");
  const [pipeline, setPipeline] = useState<PipelineDetail>();
  const [listError, setListError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [launching, setLaunching] = useState(false);
  const version = pipelines?.find((item) => item.id === choice)?.latest_version;

  useEffect(() => {
    let active = true;
    api.pipelines(accountId).then((items) => {
      if (active) {
        setPipelines(items);
        setListError("");
      }
    }).catch((failure: unknown) => {
      if (active) setListError(reportError(failure, onSessionChange));
    });
    return () => { active = false; };
  }, [accountId, revision, onSessionChange]);

  useEffect(() => {
    if (!choice || version === undefined) return;
    let active = true;
    api.pipeline(accountId, choice).then((detail) => {
      if (active) {
        setPipeline(detail);
        setDetailError("");
      }
    }).catch((failure: unknown) => {
      if (active) setDetailError(reportError(failure, onSessionChange));
    });
    return () => { active = false; };
  }, [accountId, choice, version, revision, onSessionChange]);

  return <section aria-label="Ручной запуск">
    <h3>Ручной запуск</h3>
    {listError && <p role="alert">{listError}</p>}
    {pipelines?.length === 0 && <p>Сначала сохраните пайплайн.</p>}
    <label>Пайплайн для запуска
      <select value={choice} disabled={!pipelines?.length || launching} onChange={(event) => {
        setChoice(event.target.value);
        setPipeline(undefined);
        setDetailError("");
      }}>
        <option value="">Выберите пайплайн</option>
        {pipelines?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
    </label>
    {detailError && <p role="alert">{detailError}</p>}
    {choice && version !== undefined && !detailError && (!pipeline || pipeline.latest_version < version)
      && <p role="status">Загрузка параметров…</p>}
    {!detailError && pipeline?.id === choice && version !== undefined && pipeline.latest_version >= version
      && <LaunchForm key={`${pipeline.id}:${pipeline.latest_version}`} accountId={accountId}
        onSessionChange={onSessionChange} pipeline={pipeline} onLaunched={onLaunched}
        onUncertain={onUncertain} pending={launching} setPending={setLaunching} />}
  </section>;
}

export function TeacherRuns({ accountId, onSessionChange, pipelineRevision = 0 }: Session & {
  pipelineRevision?: number;
}) {
  const [runs, setRuns] = useState<RunSummary[]>();
  const [selected, setSelected] = useState<string>();
  const [revision, setRevision] = useState(0);
  const [manualRevision, setManualRevision] = useState(0);
  const [error, setError] = useState("");
  const lastRunning = useRef<{ accountId: string; running: boolean } | null>(null);

  useEffect(() => {
    let active = true;
    let running = lastRunning.current?.accountId === accountId && lastRunning.current.running;
    let poll: ReturnType<typeof setTimeout> | undefined;

    async function read() {
      try {
        const items = await api.runs(accountId);
        if (!active) return;
        setRuns(items);
        setError("");
        running = items.some((run) => run.status === "running");
        lastRunning.current = { accountId, running };
      } catch (failure: unknown) {
        if (!active) return;
        setError(reportError(failure, onSessionChange));
        if (!shouldRetry(failure)) return;
      }
      if (running) poll = setTimeout(() => void read(), POLL_DELAY);
    }

    void read();
    return () => { active = false; clearTimeout(poll); };
  }, [accountId, revision, onSessionChange]);

  const approvals = runs?.filter((run) => run.status === "waiting" &&
    run.waiting.some((item) => item.who === "teacher"));
  const selectedRun = runs?.find((run) => run.id === selected);
  const refresh = () => setRevision((current) => current + 1);

  return <section className="teacher-runs">
    <h2>Запуски</h2>
    <button type="button" onClick={() => {
      refresh();
      setManualRevision((current) => current + 1);
    }}>Обновить запуски</button>
    <ManualLaunch accountId={accountId} onSessionChange={onSessionChange}
      revision={manualRevision + pipelineRevision} onUncertain={refresh} onLaunched={(id) => {
      setSelected(id);
      refresh();
    }} />
    {error && <p role="alert">{error}</p>}
    {!runs && !error && <p role="status">Загрузка запусков…</p>}
    {runs && <>
      <section aria-label="Очередь подтверждений">
        <h3>Очередь подтверждений</h3>
        {approvals?.length ? <ul>{approvals.map((run) => <li key={run.id}>
          <button type="button" onClick={() => setSelected(run.id)}>{run.pipeline_name}</button>
          {" · "}{run.waiting.filter(({ who }) => who === "teacher").map(({ node_id }) => node_id).join(", ")}
        </li>)}</ul> : <p>Нет запусков на подтверждении.</p>}
      </section>
      <section aria-label="Все запуски">
        <h3>Все запуски</h3>
        {runs.length === 0 ? <p>Запусков пока нет.</p> : <ul>{runs.map((run) => <li key={run.id}>
          <button type="button" aria-pressed={selected === run.id}
            onClick={() => setSelected(run.id)}>{run.pipeline_name}</button>
          {" · версия "}{run.pipeline_version}{" · "}{run.student_name ?? "Без ученика"}
          {" · "}<time dateTime={run.updated_at}>{new Date(run.updated_at).toLocaleString("ru-RU")}</time>
          <div><RunProgress run={run} /></div>
        </li>)}</ul>}
      </section>
    </>}
    {selected && <div>
      {selectedRun && <p>{selectedRun.pipeline_name} · версия {selectedRun.pipeline_version}</p>}
      <RunJournal key={selected} accountId={accountId} onSessionChange={onSessionChange}
        id={selected} revision={revision} onRefresh={refresh} />
    </div>}
  </section>;
}
